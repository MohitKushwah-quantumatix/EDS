"""The Parquet adapter.

Binds the existing :mod:`~eds.adapters.parquet.writer` and
:mod:`~eds.adapters.parquet.reader` functions to the
:class:`~eds.adapters.base.DatasetWriter` and
:class:`~eds.adapters.base.DatasetReader` protocols.

This is a binding, not a rewrite. The read and write implementations are the
ones the retail simulator has always used, byte for byte, and the CLI still
calls those functions directly. The adapter exists so that a second output
target has a shape to conform to (PADR-003).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

import polars as pl

from eds.adapters.base import AdapterError, WriteResult
from eds.adapters.parquet.reader import DatasetNotFoundError, read_datasets
from eds.adapters.parquet.writer import ExportError, write_datasets

__all__ = ["PARQUET_ADAPTER_NAME", "ParquetAdapter"]

#: Registry name for this adapter.
PARQUET_ADAPTER_NAME = "parquet"


class ParquetAdapter:
    """Reads and writes datasets as Snappy-compressed Parquet files.

    Satisfies both :class:`~eds.adapters.base.DatasetWriter` and
    :class:`~eds.adapters.base.DatasetReader`.

    The directory is bound at construction rather than passed per call, which
    is what makes the protocol implementable by adapters whose destination is
    not a directory at all.
    """

    def __init__(self, directory: Path) -> None:
        """Point the adapter at a directory.

        Args:
            directory: Where Parquet files are read from and written to. It is
                created on write if absent.
        """
        self._directory = directory

    @property
    def name(self) -> str:
        """Return the adapter's registry name."""
        return PARQUET_ADAPTER_NAME

    @property
    def directory(self) -> Path:
        """Return the directory this adapter is bound to."""
        return self._directory

    def write(self, datasets: Mapping[str, pl.DataFrame]) -> tuple[WriteResult, ...]:
        """Write every dataset as one Parquet file.

        Args:
            datasets: Dataset name to frame.

        Returns:
            One result per dataset, carrying the file path and row count.

        Raises:
            AdapterError: If any dataset cannot be written.
        """
        try:
            written = write_datasets(datasets, self._directory)
        except ExportError as exc:
            raise AdapterError(str(exc)) from exc
        return tuple(
            WriteResult(dataset=name, location=str(path), rows=datasets[name].height)
            for name, path in written.items()
        )

    def read(self, names: Iterable[str]) -> dict[str, pl.DataFrame]:
        """Read the named datasets from Parquet.

        Args:
            names: Dataset names to read.

        Returns:
            Dataset name to frame.

        Raises:
            AdapterError: If any dataset is missing or unreadable.
        """
        try:
            return read_datasets(names, self._directory)
        except (DatasetNotFoundError, OSError) as exc:
            raise AdapterError(str(exc)) from exc
