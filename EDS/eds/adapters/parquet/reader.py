"""Reading previously exported Parquet datasets.

F002 consumes the geography datasets F001 wrote rather than regenerating
them, so it needs to load Parquet from the output directory. Keeping the
reader beside the writer means the file naming convention is defined once.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import polars as pl

__all__ = ["DatasetNotFoundError", "read_dataset", "read_datasets"]


class DatasetNotFoundError(FileNotFoundError):
    """Raised when a required dataset is absent from the input directory."""


def read_dataset(name: str, input_dir: Path) -> pl.DataFrame:
    """Read one dataset from Parquet.

    Args:
        name: Dataset name, used as the file stem.
        input_dir: Directory to read from.

    Returns:
        The loaded frame.

    Raises:
        DatasetNotFoundError: If the file does not exist.
        OSError: If the file exists but cannot be read.
    """
    path = input_dir / f"{name}.parquet"
    if not path.is_file():
        raise DatasetNotFoundError(
            f"Required dataset {name!r} not found at {path}. Run `eds generate master-data` first."
        )
    return pl.read_parquet(path)


def read_datasets(names: Iterable[str], input_dir: Path) -> dict[str, pl.DataFrame]:
    """Read several datasets from Parquet.

    Args:
        names: Dataset names to load.
        input_dir: Directory to read from.

    Returns:
        Dataset name to frame, in the order requested.

    Raises:
        DatasetNotFoundError: If any dataset is absent.
        OSError: If a file exists but cannot be read.
    """
    return {name: read_dataset(name, input_dir) for name in names}
