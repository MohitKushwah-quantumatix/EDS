"""MongoDB connector — write target.

Writes EDS-generated datasets to MongoDB as schemaless BSON document
collections.  Each dataset becomes a collection; each row becomes one
document.

This connector does **not** inherit from
:class:`~eds_loader.connectors._sql_base.BaseSQLConnector` — MongoDB is
a document store with no DDL, no ``CREATE TABLE``, and no FK ordering
requirement between collections.

Driver
------
:pypi:`pymongo` v4+ (``pip install eds-loader[mongodb]``).

When pymongo is not installed, this module still imports cleanly and
registers the connector with ``connector_class=None``.

Write strategy
--------------
For each collection (in original *datasets* iteration order):

1. ``collection.drop()`` — removes the existing collection (no-op if absent).
2. ``collection.insert_many(documents)`` — bulk-inserts all rows as BSON
   documents.  Empty DataFrames skip the insert step.
3. ``collection.create_index(...)`` — creates indexes derived from
   ``schema.json`` when ``enforce_constraints=True``.

Collections are independent — no topological sort needed.

Type conversion
---------------
``df.to_dicts()`` serialises each Polars DataFrame row to a Python dict with
native types (``int``, ``float``, ``str``, ``bool``, ``datetime``, ``list``,
``dict``, ``None``). pymongo then maps those to BSON automatically.

Index creation
--------------
When ``schema_metadata`` is non-empty:

* ``primary_key`` column → ``unique`` index
* ``unique_columns`` → ``unique`` index each
* FK ``column`` entries → regular (non-unique) index each — aids lookups
  but does not enforce referential integrity (MongoDB is schemaless)
"""

from __future__ import annotations

import os
import time
from typing import Any

import polars as pl

from eds_loader._logging import get_logger
from eds_loader.connectors.base import UpsertResult, WriteResult
from eds_loader.connectors.registry import ConnectorSpec, register_connector
from eds_loader.exceptions import LoadError

logger = get_logger(__name__)

__all__ = ["MongoDBConnector"]

# Optional dependency — wrapped so the module always imports cleanly.
try:
    import pymongo as _pymongo  # type: ignore[import]
    _PYMONGO_AVAILABLE = True
except ImportError:
    _pymongo = None  # type: ignore[assignment]
    _PYMONGO_AVAILABLE = False


class MongoDBConnector:
    """Write EDS datasets to a MongoDB database as document collections.

    Implements :class:`~eds_loader.connectors.base.Writable`.

    Config fields
    -------------
    ``host`` (required)
        MongoDB server hostname or IP.
    ``database`` (required)
        Target database name.
    ``port``
        Server port (default: ``27017``).
    ``username``
        Login username.  Leave unset for unauthenticated connections.
    ``password`` / ``password_env``
        Inline password or env-var name.  ``password_env`` is preferred.
    ``auth_source``
        Database used for authentication (default: ``"admin"``).
    ``connect_timeout``
        Server-selection timeout in **milliseconds** (default: ``10000``).

    Example config::

        target:
          kind: mongodb
          host: localhost
          port: 27017
          database: eds_db
          username: eds_loader
          password_env: EDS_MONGO_PASSWORD
    """

    def __init__(
        self,
        host: str,
        database: str,
        port: int = 27017,
        username: str | None = None,
        password: str | None = None,
        password_env: str | None = None,
        auth_source: str = "admin",
        connect_timeout: int = 10000,
        **_kwargs: Any,
    ) -> None:
        self._host = host
        self._database = database
        self._port = int(port)
        self._username = username
        self._password = password
        self._password_env = password_env
        self._auth_source = auth_source
        self._connect_timeout = int(connect_timeout)
        self._mongo_client: Any = None  # pymongo.MongoClient, lazily created

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_password(self) -> str | None:
        """Return the DB password, never logging it.

        Raises:
            LoadError: If ``password_env`` is set but the env-var is absent.
        """
        if self._password_env:
            val = os.environ.get(self._password_env)
            if val is None:
                raise LoadError(
                    f"Environment variable {self._password_env!r} is not set."
                )
            return val
        return self._password

    def _client(self) -> Any:
        """Return (or create) the cached :class:`pymongo.MongoClient`.

        pymongo connects lazily, so this only builds the client object.
        Actual network errors surface on the first real operation.

        Raises:
            LoadError: If client construction fails (e.g. invalid params).
        """
        if self._mongo_client is not None:
            return self._mongo_client

        password = self._resolve_password()
        try:
            kwargs: dict[str, Any] = {
                "host": self._host,
                "port": self._port,
                "serverSelectionTimeoutMS": self._connect_timeout,
            }
            if self._username:
                kwargs["username"] = self._username
                kwargs["password"] = password or ""
                kwargs["authSource"] = self._auth_source

            self._mongo_client = _pymongo.MongoClient(**kwargs)
            return self._mongo_client
        except Exception as exc:
            raise LoadError(
                f"Cannot create MongoDB client for "
                f"{self._host}:{self._port}/{self._database}: {exc}"
            ) from exc

    def _db(self) -> Any:
        """Return the target :class:`pymongo.Database`."""
        return self._client()[self._database]

    def _close(self) -> None:
        """Close the MongoDB client connection pool gracefully."""
        if self._mongo_client is not None:
            try:
                self._mongo_client.close()
            except Exception:
                pass
            self._mongo_client = None

    def __enter__(self) -> "MongoDBConnector":
        self._client()
        return self

    def __exit__(self, *_args: object) -> None:
        self._close()

    def __del__(self) -> None:
        self._close()

    # ------------------------------------------------------------------
    # Index creation from schema.json
    # ------------------------------------------------------------------

    @staticmethod
    def _create_indexes(
        collection: Any,
        schema_entry: dict[str, Any],
    ) -> None:
        """Create MongoDB indexes derived from a ``schema.json`` entry.

        * ``primary_key`` → unique index
        * ``unique_columns`` → unique index per column
        * ``foreign_keys[].column`` → regular index (aids lookups only)

        Args:
            collection: A :class:`pymongo.Collection` instance.
            schema_entry: The ``schema.json`` entry for this dataset.
        """
        pk = schema_entry.get("primary_key")
        if pk:
            collection.create_index(pk, unique=True)

        for col in schema_entry.get("unique_columns", []):
            collection.create_index(col, unique=True)

        for fk in schema_entry.get("foreign_keys", []):
            col = fk.get("column")
            if col:
                collection.create_index(col, unique=False)

    # ------------------------------------------------------------------
    # Writable interface
    # ------------------------------------------------------------------

    def write_datasets(
        self,
        datasets: dict[str, pl.DataFrame],
        schema_metadata: dict[str, Any],
    ) -> list[WriteResult]:
        """Write datasets to MongoDB collections — full replace (NFR-3).

        Steps per collection:

        1. ``collection.drop()``
        2. ``collection.insert_many(df.to_dicts())``  (skipped if empty)
        3. Index creation from ``schema_metadata`` (if non-empty)

        Collections are written in *datasets* iteration order.  No
        topological sort is applied — MongoDB has no FK enforcement
        between collections.

        Args:
            datasets: Dataset name → Polars DataFrame.
            schema_metadata: Parsed ``schema.json``.  Non-empty triggers
                constraint-derived index creation.

        Returns:
            One :class:`~eds_loader.connectors.base.WriteResult` per
            dataset in original order.  ``location`` is formatted as
            ``mongodb://<host>:<port>/<database>/<collection>``.

        Raises:
            ~eds_loader.exceptions.LoadError: Connection, drop, insert,
                or index creation error.
        """
        db = self._db()
        logger.info(
            "Connected to MongoDB %s:%s/%s", self._host, self._port, self._database,
            extra={"progress": {"stage": "connect_target", "label": f"{self._host}:{self._port}"}},
        )
        enforce = bool(schema_metadata)
        results: list[WriteResult] = []
        total = len(datasets)

        for i, (name, df) in enumerate(datasets.items(), start=1):
            schema_entry = schema_metadata.get(name, {})
            location = (
                f"mongodb://{self._host}:{self._port}"
                f"/{self._database}/{name}"
            )
            t0 = time.monotonic()
            try:
                collection = db[name]

                # Full replace — drop existing collection first.
                logger.debug("[%s] dropping existing collection", name)
                collection.drop()

                # Bulk insert using Polars' native Python-dict serialiser.
                # df.to_dicts() converts Polars types -> Python native types;
                # pymongo handles Python -> BSON mapping automatically.
                #
                # Exception: Polars `Date` columns become `datetime.date`,
                # which BSON cannot encode (only `datetime.datetime` is
                # supported). Cast any Date columns to Datetime (midnight)
                # first so they serialise cleanly.
                if df.height > 0:
                    date_cols = [
                        c for c, dt in df.schema.items() if dt == pl.Date
                    ]
                    if date_cols:
                        logger.debug(
                            "[%s] casting Date -> Datetime for column(s): %s",
                            name, ", ".join(date_cols),
                        )
                        df = df.with_columns(
                            [pl.col(c).cast(pl.Datetime) for c in date_cols]
                        )
                    logger.debug("[%s] inserting %d document(s)", name, df.height)
                    collection.insert_many(df.to_dicts())

                # Create indexes derived from schema.json.
                if enforce:
                    logger.debug("[%s] creating indexes from schema metadata", name)
                    self._create_indexes(collection, schema_entry)

            except LoadError:
                raise
            except Exception as exc:
                logger.error("[%s] write failed: %s", name, exc)
                raise LoadError(
                    f"Failed to write dataset {name!r} to collection "
                    f"{name!r} in {self._database}@{self._host}: {exc}"
                ) from exc

            elapsed = time.monotonic() - t0
            logger.info(
                "[%s] wrote %d document(s) in %.2fs", name, df.height, elapsed,
                extra={"progress": {"stage": "write", "current": i, "total": total, "label": name}},
            )

            results.append(
                WriteResult(dataset=name, location=location, rows=df.height)
            )

        return results

    # ------------------------------------------------------------------
    # Upsertable interface — incremental / delta load
    # ------------------------------------------------------------------

    def upsert_datasets(
        self,
        datasets: dict[str, pl.DataFrame],
        schema_metadata: dict[str, Any],
    ) -> list[UpsertResult]:
        """Upsert datasets into MongoDB using ``replace_one(upsert=True)``.

        For each collection:

        - If a ``primary_key`` is present in *schema_metadata*, each document
          is upserted with ``replace_one({pk: value}, doc, upsert=True)``.
          ``upserted_id is not None`` → new insert; ``None`` → update.
        - If no primary key is available the collection is **fully replaced**
          (drop + insert_many) with a warning, matching the SQL fallback.

        Args:
            datasets: Dataset name → Polars DataFrame.
            schema_metadata: Parsed ``schema.json``.

        Returns:
            One :class:`~eds_loader.connectors.base.UpsertResult` per dataset.

        Raises:
            ~eds_loader.exceptions.LoadError: Connection or write failure.
        """
        db = self._db()
        logger.info(
            "Connected to MongoDB %s:%s/%s for upsert",
            self._host, self._port, self._database,
            extra={"progress": {"stage": "connect_target",
                                "label": f"{self._host}:{self._port}"}},
        )
        enforce = bool(schema_metadata)
        results: list[UpsertResult] = []
        total = len(datasets)

        for i, (name, df) in enumerate(datasets.items(), start=1):
            schema_entry = schema_metadata.get(name, {})
            pk_field: str | None = schema_entry.get("primary_key") if enforce else None
            location = (
                f"mongodb://{self._host}:{self._port}"
                f"/{self._database}/{name}"
            )
            t0 = time.monotonic()
            collection = db[name]

            try:
                if not pk_field:
                    # No PK — full replace with a warning.
                    logger.warning(
                        "[%s] No primary key in schema — falling back to full replace", name
                    )
                    collection.drop()
                    docs: list[dict] = []
                    if df.height > 0:
                        date_cols = [c for c, dt in df.schema.items() if dt == pl.Date]
                        if date_cols:
                            df = df.with_columns(
                                [pl.col(c).cast(pl.Datetime) for c in date_cols]
                            )
                        docs = df.to_dicts()
                        collection.insert_many(docs)
                    if enforce:
                        self._create_indexes(collection, schema_entry)
                    elapsed = time.monotonic() - t0
                    logger.info(
                        "[%s] full-replace wrote %d document(s) in %.2fs",
                        name, len(docs), elapsed,
                        extra={"progress": {"stage": "write", "current": i,
                                            "total": total, "label": name}},
                    )
                    results.append(UpsertResult(
                        dataset=name, location=location,
                        rows_inserted=len(docs), rows_updated=0,
                    ))
                    continue

                # PK available — upsert each document.
                rows_inserted = 0
                rows_updated = 0
                if df.height > 0:
                    date_cols = [c for c, dt in df.schema.items() if dt == pl.Date]
                    if date_cols:
                        df = df.with_columns(
                            [pl.col(c).cast(pl.Datetime) for c in date_cols]
                        )
                    for doc in df.to_dicts():
                        res = collection.replace_one(
                            filter={pk_field: doc[pk_field]},
                            replacement=doc,
                            upsert=True,
                        )
                        if res.upserted_id is not None:
                            rows_inserted += 1
                        else:
                            rows_updated += 1

                # Ensure indexes exist (idempotent).
                if enforce:
                    self._create_indexes(collection, schema_entry)

            except (LoadError, UpsertResult.__class__):
                raise
            except Exception as exc:
                logger.error("[%s] upsert failed: %s", name, exc)
                raise LoadError(
                    f"Failed to upsert dataset {name!r} into collection "
                    f"{name!r} in {self._database}@{self._host}: {exc}"
                ) from exc

            elapsed = time.monotonic() - t0
            logger.info(
                "[%s] upserted %d doc(s) (%d inserted, %d updated) in %.2fs",
                name, df.height, rows_inserted, rows_updated, elapsed,
                extra={"progress": {"stage": "write", "current": i,
                                    "total": total, "label": name}},
            )
            results.append(UpsertResult(
                dataset=name, location=location,
                rows_inserted=rows_inserted, rows_updated=rows_updated,
            ))

        return results

    # ------------------------------------------------------------------
    # Appendable interface — append-only / growing-history load
    # ------------------------------------------------------------------

    def append_datasets(
        self,
        datasets: dict[str, pl.DataFrame],
        schema_metadata: dict[str, Any],
    ) -> list["AppendResult"]:
        """Append documents to MongoDB collections without dropping existing data.

        For each collection:

        1. ``insert_many`` all documents unconditionally — no drop, no duplicates check.
        2. Ensure indexes from schema.json exist (idempotent).

        The collection grows with every run.

        Args:
            datasets:        Dataset name → Polars DataFrame of new documents.
            schema_metadata: Parsed ``schema.json`` for index creation.

        Returns:
            One :class:`~eds_loader.connectors.base.AppendResult` per dataset.

        Raises:
            ~eds_loader.exceptions.LoadError: On connection or insert failure.
        """
        from eds_loader.connectors.base import AppendResult

        if not _PYMONGO_AVAILABLE:
            raise LoadError(
                "pymongo is not installed. Run: pip install eds-loader[mongodb]"
            )

        db = self._connect()
        enforce = bool(schema_metadata)
        results: list[AppendResult] = []
        total = len(datasets)

        for i, (name, df) in enumerate(datasets.items(), start=1):
            schema_entry = schema_metadata.get(name, {})
            location = f"mongodb://{self._host}:{self._port}/{self._database}/{name}"
            t0 = time.monotonic()

            try:
                collection = db[name]
                if df.height > 0:
                    docs = _sanitise_docs(df.to_dicts())
                    collection.insert_many(docs, ordered=False)
                if enforce:
                    self._create_indexes(collection, schema_entry)
            except Exception as exc:
                logger.error("[%s] append failed: %s", name, exc)
                raise LoadError(
                    f"Failed to append dataset {name!r} into collection "
                    f"{name!r} in {self._database}@{self._host}: {exc}"
                ) from exc

            elapsed = time.monotonic() - t0
            logger.info(
                "[%s] appended %d doc(s) in %.2fs", name, df.height, elapsed,
                extra={"progress": {"stage": "write", "current": i,
                                    "total": total, "label": name}},
            )
            results.append(AppendResult(
                dataset=name, location=location, rows_appended=df.height,
            ))

        return results


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------
register_connector(
    "mongodb",
    ConnectorSpec(
        connector_class=MongoDBConnector if _PYMONGO_AVAILABLE else None,
        required_packages=["pymongo"],
        install_extra="mongodb",
        can_read=False,
        can_write=True,
        description=(
            "MongoDB — writes datasets as schemaless document collections. "
            "Creates indexes for PK/unique columns from schema.json. "
            "Requires: pip install eds-loader[mongodb]"
        ),
    ),
)
