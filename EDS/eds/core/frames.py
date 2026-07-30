"""Helpers for building schema-conformant Polars frames.

Every generator produces its output through :func:`build_frame`, so a column
that is missing, misspelled, or of the wrong length fails immediately at the
point of construction rather than surfacing later as a confusing Parquet or
join error.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import polars as pl

from eds.core.schema import Dataset

__all__ = ["build_frame", "empty_frame", "format_code"]


def build_frame(dataset: Dataset, columns: Mapping[str, Sequence[Any]]) -> pl.DataFrame:
    """Build a DataFrame matching a dataset declaration exactly.

    Args:
        dataset: The dataset whose schema the frame must satisfy.
        columns: Column name to values. Must cover the declared columns
            exactly, with every column the same length.

    Returns:
        A DataFrame with the declared column order and dtypes.

    Raises:
        ValueError: If columns are missing, unexpected, or of unequal length.
    """
    expected = set(dataset.column_names)
    provided = set(columns)
    if missing := expected - provided:
        raise ValueError(f"{dataset.name}: missing columns {sorted(missing)}")
    if unexpected := provided - expected:
        raise ValueError(f"{dataset.name}: unexpected columns {sorted(unexpected)}")

    lengths = {name: len(values) for name, values in columns.items()}
    if len(set(lengths.values())) > 1:
        raise ValueError(f"{dataset.name}: columns have differing lengths {lengths}")

    ordered = {name: list(columns[name]) for name in dataset.column_names}
    return pl.DataFrame(ordered, schema=dataset.polars_schema())


def empty_frame(dataset: Dataset) -> pl.DataFrame:
    """Return an empty DataFrame with the dataset's schema.

    Args:
        dataset: The dataset declaration.

    Returns:
        A zero-row DataFrame with the declared columns and dtypes.
    """
    return pl.DataFrame(schema=dataset.polars_schema())


def format_code(prefix: str, number: int, width: int = 6) -> str:
    """Format a zero-padded business code such as ``SKU-000042``.

    Args:
        prefix: Code prefix.
        number: Numeric part.
        width: Minimum digits, zero-padded.

    Returns:
        The formatted code.

    Raises:
        ValueError: If ``number`` is negative.
    """
    if number < 0:
        raise ValueError(f"code number must not be negative, got {number}")
    return f"{prefix}-{number:0{width}d}"
