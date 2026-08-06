"""PostgreSQL export for generated datasets.

Each dataset is written to ``<schema>.<dataset>`` via ``sqlalchemy`` and
``polars.DataFrame.write_database``. The table is replaced on every write --
the same "regenerate, don't patch" behaviour the Parquet writer has always
had -- so a dataset never accumulates rows across two runs against the same
target.

**Constraints (PADR-018).** ``write_dataset``/``write_datasets`` accept an
optional ``schemas`` mapping of dataset name to
:class:`eds.core.schema.Dataset`. A dataset named in ``schemas`` gets a table
created from DDL derived in
:mod:`eds.adapters.postgres.schema_ddl` -- primary key, foreign keys, and
uniqueness constraints included -- with rows then appended into that table
rather than letting Polars infer and create it. A dataset *not* named in
``schemas`` (or when ``schemas`` is omitted entirely) falls back to Polars'
inferred schema, since there is no declaration to build DDL from.

This module itself has no idea which datasets are "the 39 Retail datasets" --
that would mean importing ``eds.domains``, which PADR-003 forbids an adapter
from doing. The mapping is the caller's to supply; see
:mod:`eds.adapters.postgres.schema_ddl` for where a Retail caller gets one.

**Dropping a table drops what references it.** ``DROP TABLE ... CASCADE`` is
used so that recreating a table already replaced with a different shape does
not fail against its own old foreign keys, but the same CASCADE also drops
any *other* table's foreign key pointing at this one -- and, if that other
table only has this constraint standing between it and nothing else, drops
the table itself. Writing a full, correctly ordered set of datasets in one
:func:`write_datasets` call never triggers this; only writing a single
upstream dataset in isolation, against a database that already holds
downstream data referencing it, can.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

import polars as pl
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from eds.adapters.postgres.schema_ddl import create_table_statement, write_order
from eds.core.schema import Dataset

__all__ = ["ExportError", "write_dataset", "write_datasets"]

# Once a table is created from DDL, rows are appended into that exact shape;
# "replace" is Polars' own create-from-inference path and would discard the
# constraints just declared.
_APPEND: Final[Literal["append"]] = "append"
# Every existing dataset is regenerated in full on each run (PADR-016 domains
# keep no execution state of their own), so "replace" is the only mode that
# keeps a Postgres target consistent with a fresh Parquet export of the same
# run, for datasets with no DDL to create a table from instead.
_REPLACE: Final[Literal["replace"]] = "replace"


class ExportError(RuntimeError):
    """Raised when a dataset cannot be written to PostgreSQL."""


def _write_constrained(name: str, frame: pl.DataFrame, engine: Engine, dataset: Dataset, *, schema: str) -> None:
    """Drop, recreate from DDL, and populate one dataset's table."""
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{name}" CASCADE'))
        conn.execute(text(create_table_statement(dataset, schema=schema)))
    frame.write_database(f"{schema}.{name}", connection=engine, if_table_exists=_APPEND)


def write_dataset(
    name: str,
    frame: pl.DataFrame,
    engine: Engine,
    *,
    schema: str = "public",
    dataset_schema: Dataset | None = None,
) -> str:
    """Write a single dataset to a PostgreSQL table.

    Args:
        name: Dataset name, used as the table name.
        frame: The data to write.
        engine: An open SQLAlchemy engine pointed at the target database.
        schema: The PostgreSQL schema to write into. Must already exist;
            this function does not create schemas, only tables.
        dataset_schema: If given, the table is created from this
            declaration's primary key, foreign keys, and uniqueness
            constraints rather than from Polars' inferred schema.

    Returns:
        The qualified table name written, as ``"<schema>.<name>"``.

    Raises:
        ExportError: If the schema is absent, a foreign key references a
            table that does not yet exist, or the write otherwise fails.
    """
    qualified = f"{schema}.{name}"
    try:
        if dataset_schema is not None:
            _write_constrained(name, frame, engine, dataset_schema, schema=schema)
        else:
            frame.write_database(qualified, connection=engine, if_table_exists=_REPLACE)
    except SQLAlchemyError as exc:
        raise ExportError(f"Could not write {qualified}: {exc}") from exc
    return qualified


def write_datasets(
    datasets: Mapping[str, pl.DataFrame],
    engine: Engine,
    *,
    schema: str = "public",
    schemas: Mapping[str, Dataset] | None = None,
) -> dict[str, str]:
    """Write every dataset to PostgreSQL.

    Datasets named in ``schemas`` are written in foreign-key-safe order
    (:func:`~eds.adapters.postgres.schema_ddl.write_order`) before any
    dataset not named in it, so a table is never created before the tables
    its own foreign keys reference.

    Args:
        datasets: Dataset name to frame.
        engine: An open SQLAlchemy engine pointed at the target database.
        schema: The PostgreSQL schema to write into.
        schemas: Dataset name to declaration, for datasets that should be
            created with constraints. Datasets in ``datasets`` but not in
            ``schemas`` fall back to inferred, unconstrained tables.

    Returns:
        Dataset name to qualified table name, in write order.

    Raises:
        ExportError: If any dataset cannot be written.
    """
    constrained = {name: ds for name, ds in (schemas or {}).items() if name in datasets}
    order = [*write_order(constrained), *(name for name in datasets if name not in constrained)]
    return {
        name: write_dataset(name, datasets[name], engine, schema=schema, dataset_schema=constrained.get(name))
        for name in order
    }
