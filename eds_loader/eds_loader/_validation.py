"""Row-level data validation engine.

Validates Polars DataFrames against rules declared in ``schema.json``
(or ``loader.yaml``) before writing to the target.

Rule syntax (in ``schema.json`` per dataset)::

    {
      "patients": {
        "primary_key": "patient_id",
        "validation": {
          "patient_id": {"not_null": true},
          "age":        {"not_null": true, "min": 0, "max": 150},
          "gender":     {"allowed_values": ["M", "F", "Other"]},
          "email":      {"regex": "^[\\\\w.+-]+@[\\\\w-]+\\\\.[\\\\w.]+$"},
          "admit_date": {"not_null": true}
        }
      }
    }

Supported rules
---------------
``not_null``
    Row is invalid if the column value is ``null``.
``min`` / ``max``
    Numeric range check (inclusive).
``min_length`` / ``max_length``
    String length check.
``allowed_values``
    Value must be in the given list.
``regex``
    String must match the pattern (full match via Polars ``str.contains``).

Outcomes (``on_validation_error`` in ``loader.yaml``)
------------------------------------------------------
- ``warn``       — log violations, load all rows anyway.
- ``fail``       — raise :exc:`~eds_loader.exceptions.LoadError` if any row violates a rule.
- ``quarantine`` — load only valid rows; write rejected rows to
                   ``./rejected/<dataset>_<date>.parquet``.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

import polars as pl

from eds_loader.exceptions import LoadError

__all__ = ["validate_dataset", "ValidationResult"]

logger = logging.getLogger("eds_loader._validation")


class ValidationResult:
    """Summary of validation for one dataset.

    Attributes:
        dataset: Dataset name.
        total_rows: Total rows before validation.
        valid_rows: Rows that passed all rules.
        rejected_rows: Rows that failed at least one rule.
        violations: Human-readable violation messages per column.
        valid_df: DataFrame containing only rows that passed.
        rejected_df: DataFrame containing only rows that failed.
    """

    def __init__(
        self,
        dataset: str,
        total_rows: int,
        valid_df: pl.DataFrame,
        rejected_df: pl.DataFrame,
        violations: list[str],
    ) -> None:
        self.dataset = dataset
        self.total_rows = total_rows
        self.valid_df = valid_df
        self.rejected_df = rejected_df
        self.violations = violations

    @property
    def valid_rows(self) -> int:
        return self.valid_df.height

    @property
    def rejected_rows(self) -> int:
        return self.rejected_df.height

    @property
    def passed(self) -> bool:
        return self.rejected_rows == 0

    def summary(self) -> str:
        lines = [
            f"Validation — {self.dataset} ({self.total_rows:,} rows):"
        ]
        for msg in self.violations:
            lines.append(f"  ✗ {msg}")
        if self.passed:
            lines.append("  ✓ All rows passed")
        else:
            lines.append(
                f"  → {self.rejected_rows:,} row(s) rejected, "
                f"{self.valid_rows:,} valid"
            )
        return "\n".join(lines)


def validate_dataset(
    name: str,
    df: pl.DataFrame,
    validation_rules: dict[str, dict[str, Any]],
) -> ValidationResult:
    """Apply *validation_rules* to *df* and return a :class:`ValidationResult`.

    Args:
        name: Dataset name (used in messages and rejection file names).
        df: The source DataFrame to validate.
        validation_rules: Column-name → rule dict from ``schema.json``.

    Returns:
        :class:`ValidationResult` with ``valid_df`` and ``rejected_df``
        partitions.
    """
    if not validation_rules:
        return ValidationResult(
            dataset=name,
            total_rows=df.height,
            valid_df=df,
            rejected_df=df.clear(),
            violations=[],
        )

    # Build a combined boolean mask: True = row is valid.
    valid_mask = pl.lit(True)
    violations: list[str] = []

    for col, rules in validation_rules.items():
        if col not in df.columns:
            logger.warning("[%s] Validation rule for unknown column %r — skipped", name, col)
            continue

        series = pl.col(col)
        col_mask = pl.lit(True)

        # not_null
        if rules.get("not_null"):
            col_mask = col_mask & series.is_not_null()
            null_count = df[col].null_count()
            if null_count:
                violations.append(f"{col}: {null_count:,} null value(s) (not_null rule)")

        # min / max (numeric)
        if "min" in rules:
            min_val = rules["min"]
            col_mask = col_mask & (series >= min_val)
            bad = df.filter(pl.col(col).is_not_null() & (pl.col(col) < min_val)).height
            if bad:
                violations.append(f"{col}: {bad:,} value(s) below minimum {min_val}")

        if "max" in rules:
            max_val = rules["max"]
            col_mask = col_mask & (series <= max_val)
            bad = df.filter(pl.col(col).is_not_null() & (pl.col(col) > max_val)).height
            if bad:
                violations.append(f"{col}: {bad:,} value(s) above maximum {max_val}")

        # min_length / max_length (strings)
        if "min_length" in rules:
            min_len = rules["min_length"]
            col_mask = col_mask & (series.str.len_chars() >= min_len)
            bad = df.filter(
                pl.col(col).is_not_null() & (pl.col(col).str.len_chars() < min_len)
            ).height
            if bad:
                violations.append(f"{col}: {bad:,} string(s) shorter than {min_len} chars")

        if "max_length" in rules:
            max_len = rules["max_length"]
            col_mask = col_mask & (series.str.len_chars() <= max_len)
            bad = df.filter(
                pl.col(col).is_not_null() & (pl.col(col).str.len_chars() > max_len)
            ).height
            if bad:
                violations.append(f"{col}: {bad:,} string(s) longer than {max_len} chars")

        # allowed_values
        if "allowed_values" in rules:
            allowed = rules["allowed_values"]
            col_mask = col_mask & series.is_in(allowed)
            bad = df.filter(
                pl.col(col).is_not_null() & ~pl.col(col).is_in(allowed)
            ).height
            if bad:
                violations.append(
                    f"{col}: {bad:,} value(s) not in allowed list {allowed}"
                )

        # regex
        if "regex" in rules:
            pattern = rules["regex"]
            try:
                col_mask = col_mask & series.str.contains(pattern)
                bad = df.filter(
                    pl.col(col).is_not_null() & ~pl.col(col).str.contains(pattern)
                ).height
                if bad:
                    violations.append(f"{col}: {bad:,} value(s) failed regex {pattern!r}")
            except Exception as exc:
                logger.warning("[%s] regex rule on %r failed: %s", name, col, exc)

        valid_mask = valid_mask & col_mask

    valid_df = df.filter(valid_mask)
    rejected_df = df.filter(~valid_mask)

    return ValidationResult(
        dataset=name,
        total_rows=df.height,
        valid_df=valid_df,
        rejected_df=rejected_df,
        violations=violations,
    )


def quarantine_rejected(
    result: ValidationResult,
    rejected_dir: Path,
) -> Path | None:
    """Write *result.rejected_df* to a dated Parquet file in *rejected_dir*.

    Args:
        result: Completed :class:`ValidationResult` with rejected rows.
        rejected_dir: Directory where rejected Parquet files are written.
            Created if it does not exist.

    Returns:
        Path to the written file, or ``None`` if there were no rejected rows.
    """
    if result.rejected_rows == 0:
        return None

    today = datetime.date.today().isoformat()
    rejected_dir.mkdir(parents=True, exist_ok=True)
    out = rejected_dir / f"{result.dataset}_{today}.parquet"
    result.rejected_df.write_parquet(out)
    logger.info(
        "[%s] %d rejected row(s) quarantined → %s",
        result.dataset, result.rejected_rows, out,
    )
    return out


def apply_validation(
    name: str,
    df: pl.DataFrame,
    schema_entry: dict[str, Any],
    on_error: str,          # "warn" | "fail" | "quarantine"
    rejected_dir: Path,
) -> pl.DataFrame:
    """Validate *df* and return the rows to load based on *on_error* policy.

    Args:
        name: Dataset name.
        df: Source DataFrame.
        schema_entry: One dataset's schema dict (may contain ``"validation"``).
        on_error: ``"warn"``, ``"fail"``, or ``"quarantine"``.
        rejected_dir: Where to write rejected rows when ``on_error="quarantine"``.

    Returns:
        The DataFrame to pass on to the write/upsert step:
        - ``"warn"``:       the original *df* (all rows, violations logged).
        - ``"fail"``:       raises :exc:`~eds_loader.exceptions.LoadError`
                            if any violations found.
        - ``"quarantine"``: only the valid rows.

    Raises:
        ~eds_loader.exceptions.LoadError: When ``on_error="fail"`` and
            validation finds violations.
    """
    rules: dict[str, Any] = schema_entry.get("validation", {})
    if not rules:
        return df

    result = validate_dataset(name, df, rules)

    # Always log the summary.
    for line in result.summary().splitlines():
        if "✗" in line:
            logger.warning(line)
        else:
            logger.info(line)

    if result.passed:
        return df

    if on_error == "fail":
        raise LoadError(
            f"Validation failed for dataset {name!r}: "
            f"{result.rejected_rows:,} row(s) violated rules.\n"
            + "\n".join(f"  - {v}" for v in result.violations)
        )

    if on_error == "quarantine":
        quarantine_rejected(result, rejected_dir)
        return result.valid_df  # only load valid rows

    # on_error == "warn" — load everything, just emit warnings above.
    return df
