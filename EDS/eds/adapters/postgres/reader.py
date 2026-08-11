"""Reading previously exported PostgreSQL datasets.

Kept beside the writer so the table naming and schema-qualification
convention (``<schema>.<dataset>``) is defined once, the same reasoning
``eds.adapters.parquet.reader`` gives for sitting beside its writer.
"""

from __future__ import annotations

from collections.abc import Iterable

import polars as pl
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

__all__ = ["DatasetNotFoundError", "read_dataset", "read_datasets"]


class DatasetNotFoundError(RuntimeError):
    """Raised when a required dataset table is absent from the schema."""


def read_dataset(name: str, engine: Engine, *, schema: str = "public") -> pl.DataFrame:
    """Read one dataset from a PostgreSQL table.

    Args:
        name: Dataset name, used as the table name.
        engine: An open SQLAlchemy engine pointed at the source database.
        schema: The PostgreSQL schema to read from.

    Returns:
        The loaded frame.

    Raises:
        DatasetNotFoundError: If the table does not exist in the schema.
        OSError: If the table exists but cannot be read.
    """
    if not inspect(engine).has_table(name, schema=schema):
        raise DatasetNotFoundError(
            f"Required dataset {name!r} not found as {schema}.{name}. "
            "Run the write stage against this database first."
        )
    try:
        return pl.read_database(f'SELECT * FROM "{schema}"."{name}"', connection=engine)
    except SQLAlchemyError as exc:
        raise OSError(f"Could not read {schema}.{name}: {exc}") from exc


def read_datasets(names: Iterable[str], engine: Engine, *, schema: str = "public") -> dict[str, pl.DataFrame]:
    """Read several datasets from PostgreSQL.

    Args:
        names: Dataset names to load.
        engine: An open SQLAlchemy engine pointed at the source database.
        schema: The PostgreSQL schema to read from.

    Returns:
        Dataset name to frame, in the order requested.

    Raises:
        DatasetNotFoundError: If any dataset table is absent.
        OSError: If a table exists but cannot be read.
    """
    return {name: read_dataset(name, engine, schema=schema) for name in names}
