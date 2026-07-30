"""Declarative dataset schemas shared by generators, validators, and exporters.

Master data is carried as Polars DataFrames rather than as one object per row,
because the generator must scale to product counts far beyond what per-row
Python objects allow. A :class:`Dataset` records the column types, primary key,
and foreign key edges for one output file, so schema conformance and
referential integrity are checked against a single declaration instead of
hand-written assertions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import polars as pl

__all__ = ["Dataset", "ForeignKey"]


@dataclass(frozen=True, slots=True)
class ForeignKey:
    """A foreign key edge from one dataset to another.

    Attributes:
        column: Column in the referencing dataset.
        references: Name of the referenced dataset.
        referenced_column: Column in the referenced dataset.
        nullable: Whether the referencing column may contain nulls. Null values
            are exempt from the integrity check.
    """

    column: str
    references: str
    referenced_column: str
    nullable: bool = False


@dataclass(frozen=True, slots=True)
class Dataset:
    """The schema of a single master data output file.

    Attributes:
        name: Dataset name, used as the Parquet file stem.
        columns: Ordered mapping of column name to Polars dtype.
        primary_key: Column holding unique, non-null row identifiers.
        foreign_keys: Referential edges to other datasets.
        unique_columns: Additional columns that must hold unique values.
    """

    name: str
    columns: Mapping[str, pl.DataType]
    primary_key: str
    foreign_keys: tuple[ForeignKey, ...] = ()
    unique_columns: tuple[str, ...] = field(default=())

    @property
    def column_names(self) -> tuple[str, ...]:
        """Return the declared column names in order."""
        return tuple(self.columns)

    @property
    def file_name(self) -> str:
        """Return the Parquet file name for this dataset."""
        return f"{self.name}.parquet"

    def polars_schema(self) -> dict[str, pl.DataType]:
        """Return the schema as a plain dict for Polars constructors."""
        return dict(self.columns)
