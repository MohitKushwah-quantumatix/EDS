"""The PostgreSQL adapter.

Binds :mod:`~eds.adapters.postgres.writer` and
:mod:`~eds.adapters.postgres.reader` to the
:class:`~eds.adapters.base.DatasetWriter` and
:class:`~eds.adapters.base.DatasetReader` protocols, the same way
:class:`~eds.adapters.parquet.adapter.ParquetAdapter` binds the Parquet
functions (PADR-003: no generator imports this module, and this module
imports no generator -- the two meet only at :class:`polars.DataFrame`).

This is the second adapter, and the first proof that the protocol in
``eds.adapters.base`` was actually storage-agnostic: nothing in
``eds.domains`` changed to make it possible. What *did* have to change is
what this adapter is allowed to know: it has no idea what "Retail" is, or
which 39 tables belong to it. A caller that wants primary keys, foreign
keys, and uniqueness constraints enforced passes their declarations in as
``dataset_schemas`` -- plain :class:`eds.core.schema.Dataset` values, which
``eds.adapters`` may depend on (they live in ``eds.core``) even though it
may not depend on the domain that defines them (PADR-003). See
:mod:`eds.runners.retail.postgres_schema` for where a Retail caller gets
that mapping from.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import polars as pl
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from eds.adapters.base import AdapterError, WriteResult
from eds.adapters.postgres.reader import DatasetNotFoundError, read_datasets
from eds.adapters.postgres.writer import ExportError, write_datasets
from eds.core.schema import Dataset

__all__ = ["POSTGRES_ADAPTER_NAME", "PostgresAdapter"]

#: Registry name for this adapter.
POSTGRES_ADAPTER_NAME = "postgres"


def _mask(dsn: str) -> str:
    """Render a DSN with its password hidden, for safe use in error messages.

    A raw DSN must never reach a log, a stack trace, or an error-tracking
    service -- ``postgresql+psycopg://user:realpassword@host/db`` is a
    credential, not a label. If the DSN cannot even be parsed (the one case
    this module raises an error over), there is nothing safe to show at all,
    so the message says so instead of falling back to the raw string.

    Args:
        dsn: The connection string that failed to build an engine.

    Returns:
        The DSN with its password replaced by ``***``, or a fixed placeholder
        if it could not be parsed well enough to know where the password is.
    """
    try:
        return make_url(dsn).render_as_string(hide_password=True)
    except ArgumentError:
        return "<DSN could not be parsed; not shown, since a parse failure means it isn't safe to assume where the password is>"


class PostgresAdapter:
    """Reads and writes datasets as tables in a PostgreSQL schema.

    Satisfies both :class:`~eds.adapters.base.DatasetWriter` and
    :class:`~eds.adapters.base.DatasetReader`.

    The connection is bound at construction, exactly as the directory is for
    :class:`~eds.adapters.parquet.adapter.ParquetAdapter` -- the constructor
    argument is what varies per adapter (a path, a DSN, a topic), never the
    ``write``/``read`` call signature.

    Each dataset becomes one table, named ``<schema>.<dataset>``. A write
    replaces the table in full; this adapter does not append or upsert.
    """

    def __init__(
        self,
        dsn: str,
        *,
        schema: str = "public",
        dataset_schemas: Mapping[str, Dataset] | None = None,
    ) -> None:
        """Point the adapter at a database.

        Args:
            dsn: A SQLAlchemy connection URL, e.g.
                ``"postgresql+psycopg://user:pass@host:5432/dbname"``. The
                adapter does not create the database or the schema -- both
                must already exist.
            schema: The PostgreSQL schema tables are read from and written
                to. Defaults to ``"public"``.
            dataset_schemas: Dataset name to declaration (PADR-018). A
                dataset named here is created with its declared primary key,
                foreign keys, and uniqueness constraints. A dataset written
                but not named here falls back to a table Polars infers from
                the frame, with no constraints beyond column types. Left
                empty by default, since this adapter has no declarations of
                its own to fall back on -- see
                :mod:`eds.runners.retail.postgres_schema` for the Retail
                mapping.

        Raises:
            AdapterError: If the DSN cannot be parsed into an engine.
        """
        try:
            self._engine: Engine = create_engine(dsn)
        except SQLAlchemyError as exc:
            raise AdapterError(f"Could not create an engine for {_mask(dsn)}: {exc}") from exc
        self._schema = schema
        self._dataset_schemas = dataset_schemas or {}

    @classmethod
    def from_engine(
        cls,
        engine: Engine,
        *,
        schema: str = "public",
        dataset_schemas: Mapping[str, Dataset] | None = None,
    ) -> PostgresAdapter:
        """Build an adapter around an already-open engine.

        Used by tests and by callers that manage connection pooling
        themselves; the public constructor covers the common case of one
        adapter, one database.

        Args:
            engine: An open SQLAlchemy engine.
            schema: The PostgreSQL schema tables are read from and written to.
            dataset_schemas: See :meth:`__init__`.

        Returns:
            An adapter bound to the given engine.
        """
        instance = cls.__new__(cls)
        instance._engine = engine
        instance._schema = schema
        instance._dataset_schemas = dataset_schemas or {}
        return instance

    @property
    def name(self) -> str:
        """Return the adapter's registry name."""
        return POSTGRES_ADAPTER_NAME

    @property
    def schema(self) -> str:
        """Return the PostgreSQL schema this adapter is bound to."""
        return self._schema

    def write(self, datasets: Mapping[str, pl.DataFrame]) -> tuple[WriteResult, ...]:
        """Write every dataset as one table each, replacing any existing table.

        Args:
            datasets: Dataset name to frame.

        Returns:
            One result per dataset, carrying the qualified table name and row
            count.

        Raises:
            AdapterError: If any dataset cannot be written.
        """
        try:
            written = write_datasets(
                datasets, self._engine, schema=self._schema, schemas=self._dataset_schemas
            )
        except ExportError as exc:
            raise AdapterError(str(exc)) from exc
        return tuple(
            WriteResult(dataset=name, location=location, rows=datasets[name].height)
            for name, location in written.items()
        )

    def read(self, names: Iterable[str]) -> dict[str, pl.DataFrame]:
        """Read the named datasets from PostgreSQL.

        Args:
            names: Dataset names to read.

        Returns:
            Dataset name to frame.

        Raises:
            AdapterError: If any dataset is missing or unreadable.
        """
        try:
            return read_datasets(names, self._engine, schema=self._schema)
        except (DatasetNotFoundError, OSError) as exc:
            raise AdapterError(str(exc)) from exc

    def dispose(self) -> None:
        """Close the underlying connection pool.

        Not part of :class:`~eds.adapters.base.DatasetWriter` or
        :class:`~eds.adapters.base.DatasetReader` -- those protocols describe
        no lifecycle beyond construction, since a ``Path``-backed adapter has
        nothing to close. A connection-backed adapter does, so it is offered
        here rather than forced onto the protocol every adapter must satisfy.
        """
        self._engine.dispose()
