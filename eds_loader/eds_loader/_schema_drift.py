"""Schema drift detection — compare current source schema against stored schema.

After the first run, the dataset column schemas are stored in the state file.
On subsequent runs this module compares the new schema against the stored one
and reports any drift (added, removed, or renamed columns; type changes).

Outcome options (``schema_drift`` in ``loader.yaml``)
------------------------------------------------------
- ``warn``    — log the diff, continue the load.
- ``fail``    — raise :exc:`~eds_loader.exceptions.LoadError` if any drift is detected.
- ``ignore``  — silently continue (useful in dev environments).

Note: ``migrate`` (ALTER TABLE) is not yet implemented — use ``warn`` or
``fail`` and handle schema changes manually.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import polars as pl

from eds_loader.exceptions import LoadError

__all__ = ["detect_drift", "DriftReport"]

logger = logging.getLogger("eds_loader._schema_drift")


@dataclass
class ColumnChange:
    column: str
    change_type: str   # "added" | "removed" | "type_changed"
    old_type: str | None = None
    new_type: str | None = None

    def __str__(self) -> str:
        if self.change_type == "added":
            return f"+ Added:   {self.column}  {self.new_type}"
        if self.change_type == "removed":
            return f"- Removed: {self.column}  {self.old_type}"
        return f"~ Changed: {self.column}  {self.old_type} → {self.new_type}"


@dataclass
class DriftReport:
    """Summary of schema changes for one dataset.

    Attributes:
        dataset: Dataset name.
        changes: List of individual column changes.
        has_drift: ``True`` if any changes were detected.
    """

    dataset: str
    changes: list[ColumnChange]

    @property
    def has_drift(self) -> bool:
        return bool(self.changes)

    def summary(self) -> str:
        if not self.has_drift:
            return f"[{self.dataset}] Schema unchanged."
        lines = [f"Schema drift detected for dataset '{self.dataset}':"]
        for c in self.changes:
            lines.append(f"  {c}")
        return "\n".join(lines)


def _schema_to_dict(df: pl.DataFrame) -> dict[str, str]:
    """Return ``{column_name: dtype_string}`` for *df*."""
    return {name: str(dtype) for name, dtype in df.schema.items()}


def detect_drift(
    name: str,
    df: pl.DataFrame,
    stored_schema: dict[str, str] | None,
) -> DriftReport:
    """Compare the current DataFrame schema against the *stored_schema*.

    Args:
        name: Dataset name (for logging).
        df: The current source DataFrame.
        stored_schema: Column → dtype mapping from the state file, or
            ``None`` if this is the first run (no drift to detect).

    Returns:
        :class:`DriftReport` describing what changed.  ``has_drift`` is
        always ``False`` when *stored_schema* is ``None``.
    """
    if stored_schema is None:
        return DriftReport(dataset=name, changes=[])

    current_schema = _schema_to_dict(df)
    changes: list[ColumnChange] = []

    # Columns added in source (not in stored)
    for col, dtype in current_schema.items():
        if col not in stored_schema:
            changes.append(ColumnChange(col, "added", new_type=dtype))

    # Columns removed from source (were in stored)
    for col, dtype in stored_schema.items():
        if col not in current_schema:
            changes.append(ColumnChange(col, "removed", old_type=dtype))

    # Type changes
    for col in set(current_schema) & set(stored_schema):
        if current_schema[col] != stored_schema[col]:
            changes.append(ColumnChange(
                col, "type_changed",
                old_type=stored_schema[col],
                new_type=current_schema[col],
            ))

    return DriftReport(dataset=name, changes=changes)


def check_drift(
    name: str,
    df: pl.DataFrame,
    stored_schema: dict[str, str] | None,
    on_drift: str,    # "warn" | "fail" | "ignore"
) -> None:
    """Run drift detection and act according to *on_drift* policy.

    Args:
        name: Dataset name.
        df: Current source DataFrame.
        stored_schema: Stored schema from the previous run's state file.
        on_drift: ``"warn"``, ``"fail"``, or ``"ignore"``.

    Raises:
        ~eds_loader.exceptions.LoadError: When ``on_drift="fail"`` and
            drift is detected.
    """
    report = detect_drift(name, df, stored_schema)

    if not report.has_drift:
        return

    summary = report.summary()

    if on_drift == "ignore":
        logger.debug(summary)
        return

    if on_drift == "fail":
        raise LoadError(
            f"{summary}\n"
            "Set schema_drift: warn or schema_drift: ignore to proceed anyway."
        )

    # warn (default)
    for line in summary.splitlines():
        logger.warning(line)
