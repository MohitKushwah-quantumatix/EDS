"""Schema conformance and referential integrity checks.

These enforce that referential integrity is maintained and no orphan records
exist. Every check is driven by :class:`~eds.core.schema.Dataset`
declarations, so a new foreign key is covered as soon as it is declared and
the framework never needs to know which domain produced the data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import polars as pl

from eds.core.schema import Dataset
from eds.core.validation.issues import ValidationIssue

__all__ = [
    "validate_foreign_keys",
    "validate_primary_key",
    "validate_referential_integrity",
    "validate_schema",
]

_MAX_REPORTED_VALUES = 5


def _sample(values: list[object]) -> str:
    """Render up to a handful of offending values for an error message.

    Args:
        values: Offending values.

    Returns:
        A comma-separated sample, with an ellipsis when truncated.
    """
    head = values[:_MAX_REPORTED_VALUES]
    rendered = ", ".join(repr(value) for value in head)
    if len(values) > _MAX_REPORTED_VALUES:
        return f"{rendered}, ... ({len(values)} total)"
    return rendered


def validate_schema(dataset: Dataset, frame: pl.DataFrame) -> list[ValidationIssue]:
    """Check that a frame matches its declared columns and dtypes.

    Args:
        dataset: The dataset declaration.
        frame: The generated frame.

    Returns:
        One issue per missing column, unexpected column, or dtype mismatch.
    """
    issues: list[ValidationIssue] = []
    expected = dataset.polars_schema()
    actual = dict(frame.schema)

    for column, dtype in expected.items():
        if column not in actual:
            issues.append(
                ValidationIssue(dataset.name, "missing_column", f"column {column!r} is absent")
            )
        elif actual[column] != dtype:
            issues.append(
                ValidationIssue(
                    dataset.name,
                    "dtype_mismatch",
                    f"column {column!r} is {actual[column]}, expected {dtype}",
                )
            )

    for column in actual:
        if column not in expected:
            issues.append(
                ValidationIssue(
                    dataset.name, "unexpected_column", f"column {column!r} is not declared"
                )
            )
    return issues


def validate_primary_key(dataset: Dataset, frame: pl.DataFrame) -> list[ValidationIssue]:
    """Check primary key and unique column constraints.

    Args:
        dataset: The dataset declaration.
        frame: The generated frame.

    Returns:
        One issue per null primary key, duplicate primary key, or duplicate
        value in a declared unique column.
    """
    issues: list[ValidationIssue] = []
    key = dataset.primary_key
    if key not in frame.columns:
        return [ValidationIssue(dataset.name, "missing_primary_key", f"column {key!r} is absent")]

    null_count = int(frame[key].null_count())
    if null_count:
        issues.append(
            ValidationIssue(dataset.name, "null_primary_key", f"{null_count} null {key} value(s)")
        )

    duplicates = frame.height - int(frame[key].n_unique())
    if duplicates:
        issues.append(
            ValidationIssue(
                dataset.name, "duplicate_primary_key", f"{duplicates} duplicate {key} value(s)"
            )
        )

    for column in dataset.unique_columns:
        if column not in frame.columns:
            continue
        repeated = frame.height - int(frame[column].n_unique())
        if repeated:
            issues.append(
                ValidationIssue(
                    dataset.name,
                    "duplicate_unique_column",
                    f"{repeated} duplicate {column} value(s)",
                )
            )
    return issues


def validate_foreign_keys(
    dataset: Dataset, frame: pl.DataFrame, datasets: Mapping[str, pl.DataFrame]
) -> list[ValidationIssue]:
    """Check that every foreign key value exists in its target dataset.

    Args:
        dataset: The dataset declaration.
        frame: The generated frame.
        datasets: All generated datasets, keyed by name.

    Returns:
        One issue per orphan reference, missing target dataset, or null in a
        non-nullable foreign key column.
    """
    issues: list[ValidationIssue] = []

    for foreign_key in dataset.foreign_keys:
        if foreign_key.column not in frame.columns:
            issues.append(
                ValidationIssue(
                    dataset.name,
                    "missing_foreign_key_column",
                    f"column {foreign_key.column!r} is absent",
                )
            )
            continue

        target = datasets.get(foreign_key.references)
        if target is None:
            issues.append(
                ValidationIssue(
                    dataset.name,
                    "missing_reference_dataset",
                    f"{foreign_key.column} references {foreign_key.references}, "
                    "which was not generated",
                )
            )
            continue

        column = frame[foreign_key.column]
        null_count = int(column.null_count())
        if null_count and not foreign_key.nullable:
            issues.append(
                ValidationIssue(
                    dataset.name,
                    "null_foreign_key",
                    f"{null_count} null value(s) in non-nullable {foreign_key.column}",
                )
            )

        known = set(target[foreign_key.referenced_column].to_list())
        orphans = sorted({value for value in column.drop_nulls().to_list() if value not in known})
        if orphans:
            issues.append(
                ValidationIssue(
                    dataset.name,
                    "orphan_reference",
                    f"{foreign_key.column} has values absent from "
                    f"{foreign_key.references}.{foreign_key.referenced_column}: "
                    f"{_sample(list(orphans))}",
                )
            )
    return issues


def validate_referential_integrity(
    datasets: Mapping[str, pl.DataFrame],
    declarations: Sequence[Dataset],
) -> list[ValidationIssue]:
    """Run every schema, key, and foreign key check over a set of datasets.

    ``declarations`` is required here because the framework is domain
    independent: which datasets are being checked is a question only a domain
    can answer. Retail supplies its own default in
    :mod:`eds.domains.retail.validation.referential`.

    Args:
        datasets: Generated datasets, keyed by name. This may contain more
            datasets than are being checked, so that foreign keys pointing at
            another feature's output still resolve.
        declarations: The dataset declarations to check.

    Returns:
        Every issue found, in dataset declaration order. Empty means the data
        is referentially sound.
    """
    issues: list[ValidationIssue] = []
    for dataset in declarations:
        frame = datasets.get(dataset.name)
        if frame is None:
            issues.append(
                ValidationIssue(dataset.name, "missing_dataset", "dataset was not generated")
            )
            continue
        issues.extend(validate_schema(dataset, frame))
        issues.extend(validate_primary_key(dataset, frame))
        issues.extend(validate_foreign_keys(dataset, frame, datasets))
    return issues
