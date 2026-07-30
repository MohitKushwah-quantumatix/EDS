"""Parquet export for master datasets.

Each dataset is written to ``<output_dir>/<dataset>.parquet``. Parquet is the
F001 output format because it preserves the declared schema, which keeps the
files loadable by Spark, Databricks, Fabric, and Snowflake without a
separate DDL step.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal

import polars as pl

__all__ = ["ExportError", "write_dataset", "write_datasets"]

# Snappy balances read speed against file size and is the format every target
# engine (Spark, Databricks, Fabric, Snowflake) reads without configuration.
_COMPRESSION: Final[Literal["snappy"]] = "snappy"


class ExportError(RuntimeError):
    """Raised when a dataset cannot be written to disk."""


def write_dataset(name: str, frame: pl.DataFrame, output_dir: Path) -> Path:
    """Write a single dataset to Parquet.

    Args:
        name: Dataset name, used as the file stem.
        frame: The data to write.
        output_dir: Directory to write into. Created if absent.

    Returns:
        The path written.

    Raises:
        ExportError: If the directory cannot be created or the write fails.
    """
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(f"Could not create output directory {output_dir}: {exc}") from exc

    path = output_dir / f"{name}.parquet"
    try:
        frame.write_parquet(path, compression=_COMPRESSION)
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise ExportError(f"Could not write {path}: {exc}") from exc
    return path


def write_datasets(datasets: Mapping[str, pl.DataFrame], output_dir: Path) -> dict[str, Path]:
    """Write every dataset to Parquet.

    Args:
        datasets: Dataset name to frame.
        output_dir: Directory to write into. Created if absent.

    Returns:
        Dataset name to written path, in input order.

    Raises:
        ExportError: If any dataset cannot be written.
    """
    return {name: write_dataset(name, frame, output_dir) for name, frame in datasets.items()}
