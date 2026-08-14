"""Abstract base class for all SQL write-target connectors.

All shared write logic lives here — FK-ordered topological sort, column-def
DDL building, bulk INSERT, and the full ``write_datasets`` orchestration.
Dialect-specific connectors (``postgres.py``, ``mysql.py``, …) subclass this
and override a small set of abstract methods to provide driver and quoting
details.

Adding a new SQL database
-------------------------
Override the 7 abstract methods and add a driver-specific ``_connect()`` and
``_disconnect()``.  Everything else — sort, DDL, insert, commit loop, error
wrapping — is inherited for free.
"""

from __future__ import annotations

import abc
import os
import time
from typing import Any

import polars as pl

from eds_loader._logging import get_logger
from eds_loader.connectors.base import WriteResult
from eds_loader.exceptions import ConfigError, LoadError

logger = get_logger(__name__)

__all__ = ["BaseSQLConnector"]


class BaseSQLConnector(abc.ABC):
    """Abstract base for SQL write-target connectors.

    Shared constructor
    ------------------
    ``host``, ``database``, ``user``, ``port``, ``password`` /
    ``password_env``, and ``connect_timeout`` are stored here.
    Subclasses add their own extra attributes by calling ``super().__init__``
    then setting them.

    Context-manager support
    -----------------------
    ``with connector: ...`` opens the connection on entry and closes it on
    exit.  ``__del__`` provides a safety-net close.
    """

    def __init__(
        self,
        host: str,
        database: str,
        user: str,
        port: int,
        password: str | None = None,
        password_env: str | None = None,
        connect_timeout: int = 10,
        **_kwargs: Any,  # absorb unknown future config fields
    ) -> None:
        self._host = host
        self._database = database
        self._user = user
        self._port = int(port)
        self._password = password
        self._password_env = password_env
        self._connect_timeout = int(connect_timeout)
        self._conn: Any = None

    # ------------------------------------------------------------------
    # Abstract — every dialect must override
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def _connect(self) -> Any:
        """Open (or return cached) a DB-API 2 connection.

        Raises:
            ~eds_loader.exceptions.LoadError: On auth or network failure.
        """

    @abc.abstractmethod
    def _disconnect(self) -> None:
        """Close the connection gracefully.  Must be safe to call repeatedly."""

    @abc.abstractmethod
    def _quote(self, name: str) -> str:
        """Quote a single SQL identifier.

        Postgres: ``'"name"'``   MySQL: `` '`name`' ``   MSSQL: ``'[name]'``
        """

    @abc.abstractmethod
    def _table_ref(self, name: str) -> str:
        """Return a fully-qualified table reference.

        Postgres: ``'"public"."customers"'``
        MySQL: `` '`eds_db`.`customers`' ``
        """

    @abc.abstractmethod
    def _sql_type_map(self) -> dict[str, str]:
        """Polars dtype class name → SQL type name for this dialect.

        Example::

            {"Int64": "BIGINT", "Float64": "DOUBLE PRECISION", ...}
        """

    @abc.abstractmethod
    def _drop_table_sql(self, name: str) -> str:
        """SQL to drop a table if it exists.

        Postgres: ``'DROP TABLE IF EXISTS "s"."t" CASCADE'``
        MySQL: ``'DROP TABLE IF EXISTS `db`.`t`'`` (no CASCADE)
        """

    @abc.abstractmethod
    def _build_location(self, name: str) -> str:
        """Return the location URL string for a :class:`~eds_loader.connectors.base.WriteResult`.

        Example: ``'postgres://host:5432/mydb/public.customers'``
        """

    # ------------------------------------------------------------------
    # Concrete with overridable defaults
    # ------------------------------------------------------------------

    def _placeholder(self) -> str:
        """SQL parameter placeholder string.

        ``%s`` for psycopg / pymysql (default).
        Override to ``"?"`` for pyodbc (MSSQL).
        """
        return "%s"

    def _ensure_namespace_sql(self) -> str | None:
        """SQL to create the target namespace if it doesn't exist.

        Return ``None`` (default) if no setup is required.

        Postgres override: ``'CREATE SCHEMA IF NOT EXISTS "public"'``
        MySQL override: ``'CREATE DATABASE IF NOT EXISTS `eds_db`'``
        """
        return None

    def _pre_drop_hook(self, cursor: Any) -> None:
        """Called once (with an open cursor) before the DROP TABLE loop.

        Default: no-op.
        MySQL override: ``SET FOREIGN_KEY_CHECKS = 0``
        """

    def _post_write_hook(self, cursor: Any) -> None:
        """Called once (with an open cursor) after all tables are written.

        **Always called** — even when a write error occurs — so hook
        implementations can safely restore state.

        Default: no-op.
        MySQL override: ``SET FOREIGN_KEY_CHECKS = 1``
        """

    # ------------------------------------------------------------------
    # Shared concrete implementations
    # ------------------------------------------------------------------

    def _resolve_password(self) -> str | None:
        """Return the DB password, never logging its value.

        Raises:
            LoadError: If ``password_env`` is set but the variable is absent.
        """
        if self._password_env:
            val = os.environ.get(self._password_env)
            if val is None:
                raise LoadError(
                    f"Environment variable {self._password_env!r} is not set."
                )
            return val
        return self._password

    def _polars_dtype_to_sql(self, dtype: pl.DataType) -> str:
        """Map a Polars dtype to a SQL type string for this dialect.

        Delegates to :meth:`_sql_type_map`.  Unknown dtypes fall back to
        ``TEXT`` — always safe for storage.
        """
        return self._sql_type_map().get(type(dtype).__name__, "TEXT")

    def _indexable_string_type(self, sql_type: str) -> str | None:
        """Return a bounded replacement for *sql_type* if it can't be keyed.

        Most dialects can put a PRIMARY KEY / UNIQUE / FK on an unbounded
        text column directly (e.g. Postgres ``TEXT``). Dialects that can't
        (e.g. MySQL's ``TEXT``/``BLOB`` -- error 1170) override this to
        return a bounded type such as ``VARCHAR(255)``. Return ``None`` to
        leave *sql_type* unchanged.
        """
        return None

    @staticmethod
    def _topological_sort(
        schema_metadata: dict[str, Any],
        names: list[str],
    ) -> list[str]:
        """Return *names* ordered so FK-referenced tables are created first.

        Only intra-set FK dependencies are considered; tables not in *names*
        are assumed to already exist in the database.

        Args:
            schema_metadata: Parsed ``schema.json`` contents.
            names: Dataset names that will be written this run.

        Returns:
            Ordered list — safe for sequential ``CREATE TABLE`` with FKs.

        Raises:
            ~eds_loader.exceptions.ConfigError: Circular FK dependency detected.
        """
        name_set = set(names)
        deps: dict[str, set[str]] = {n: set() for n in names}
        for name in names:
            for fk in schema_metadata.get(name, {}).get("foreign_keys", []):
                ref = fk.get("references")
                # Self-referencing FKs (e.g. categories.parent_category_id ->
                # categories.category_id) don't block table creation order --
                # the column is defined inline in the same CREATE TABLE
                # statement, so they must not be treated as a dependency.
                if ref and ref in name_set and ref != name:
                    deps[name].add(ref)

        result: list[str] = []
        remaining = set(names)
        while remaining:
            ready = sorted(n for n in remaining if not (deps[n] & remaining))
            if not ready:
                raise ConfigError(
                    f"Circular foreign-key dependency detected among tables: "
                    f"{sorted(remaining)}. Cannot determine CREATE TABLE order. "
                    "Check schema.json for cycles."
                )
            result.extend(ready)
            remaining -= set(ready)
        return result

    def _build_column_defs(
        self,
        df: pl.DataFrame,
        schema_entry: dict[str, Any],
        enforce: bool,
    ) -> str:
        """Build the column-definition string for a ``CREATE TABLE`` statement.

        Uses :meth:`_quote` for identifier quoting and :meth:`_table_ref`
        for ``REFERENCES`` clauses — both delegated to the concrete subclass.

        Args:
            df: The dataset whose columns drive the DDL.
            schema_entry: The ``schema.json`` entry for this dataset.
            enforce: Whether to add PK / UNIQUE / FK constraints.

        Returns:
            Comma-separated column definitions, ready to embed between
            ``CREATE TABLE name (`` and ``)``.
        """
        pk_col: str | None = schema_entry.get("primary_key") if enforce else None
        unique_set: set[str] = set(schema_entry.get("unique_columns", [])) if enforce else set()
        fk_map: dict[str, dict] = {}
        if enforce:
            for fk in schema_entry.get("foreign_keys", []):
                col = fk.get("column")
                if col:
                    fk_map[col] = fk

        col_defs: list[str] = []
        for col_name in df.columns:
            sql_type = self._polars_dtype_to_sql(df[col_name].dtype)
            parts: list[str] = [self._quote(col_name), sql_type]

            is_pk = col_name == pk_col
            is_fk = col_name in fk_map
            is_keyed = is_pk or is_fk or col_name in unique_set

            # Some dialects (MySQL) can't index/key an unbounded TEXT/BLOB
            # column without an explicit key length. Swap in a bounded type
            # for columns that will be part of a PK / UNIQUE / FK.
            if is_keyed:
                bounded = self._indexable_string_type(sql_type)
                if bounded:
                    parts[-1] = bounded

            # NOT NULL for non-nullable FK (PK already implies NOT NULL)
            if is_fk and not is_pk:
                if not fk_map[col_name].get("nullable", True):
                    parts.append("NOT NULL")

            if is_pk:
                parts.append("PRIMARY KEY")

            # UNIQUE only when not already a PK (PK implies uniqueness)
            if col_name in unique_set and not is_pk:
                parts.append("UNIQUE")

            if is_fk:
                fk = fk_map[col_name]
                ref_table = fk["references"]
                ref_col = fk["referenced_column"]
                parts.append(
                    f"REFERENCES {self._table_ref(ref_table)}({self._quote(ref_col)})"
                )

            col_defs.append(" ".join(parts))

        return ",\n    ".join(col_defs)

    def _bulk_insert(
        self,
        cursor: Any,
        table_name: str,
        df: pl.DataFrame,
    ) -> None:
        """Bulk-insert all rows of *df* into ``<table_ref>``.

        Uses :meth:`_placeholder` and :meth:`_table_ref` from the subclass.
        Polars ``null`` values become ``None`` → SQL ``NULL`` via the driver.

        Args:
            cursor: An open DB-API 2 cursor.
            table_name: Unquoted target table name.
            df: Dataset to insert (empty DataFrames are silently skipped).
        """
        if df.height == 0:
            return
        quoted_cols = ", ".join(self._quote(c) for c in df.columns)
        ph = self._placeholder()
        placeholders = ", ".join([ph] * len(df.columns))
        sql = (
            f"INSERT INTO {self._table_ref(table_name)} "
            f"({quoted_cols}) VALUES ({placeholders})"
        )
        cursor.executemany(sql, df.rows())

    def __enter__(self) -> "BaseSQLConnector":
        self._connect()
        return self

    def __exit__(self, *_args: object) -> None:
        self._disconnect()

    def __del__(self) -> None:
        self._disconnect()

    # ------------------------------------------------------------------
    # Writable interface — shared orchestration
    # ------------------------------------------------------------------

    def write_datasets(
        self,
        datasets: dict[str, pl.DataFrame],
        schema_metadata: dict[str, Any],
    ) -> list[WriteResult]:
        """Write datasets to SQL tables — full replace, FK-ordered (NFR-3).

        Orchestration:

        1. Ensure target namespace (schema / database) exists.
        2. Call :meth:`_pre_drop_hook` (MySQL: ``SET FOREIGN_KEY_CHECKS=0``).
        3. For each table in FK dependency order:
           ``DROP`` → ``CREATE TABLE`` → bulk ``INSERT`` → ``COMMIT``.
        4. Call :meth:`_post_write_hook` (always, even on error).

        Args:
            datasets: Dataset name → Polars DataFrame.
            schema_metadata: Parsed ``schema.json``.  Empty dict skips
                constraint enforcement and FK sort.

        Returns:
            One :class:`~eds_loader.connectors.base.WriteResult` per
            dataset, in original *datasets* iteration order.

        Raises:
            ~eds_loader.exceptions.ConfigError: Circular FK dependency.
            ~eds_loader.exceptions.LoadError: Connection, DDL, or insert
                error.
        """
        conn = self._connect()
        logger.info(
            "Connected to %s@%s:%s/%s", self._user, self._host, self._port, self._database,
            extra={"progress": {"stage": "connect_target", "label": f"{self._host}:{self._port}"}},
        )
        enforce = bool(schema_metadata)
        names = list(datasets)
        ordered_names = (
            self._topological_sort(schema_metadata, names)
            if schema_metadata
            else names
        )
        if schema_metadata:
            logger.debug("Table write order (FK-sorted): %s", ", ".join(ordered_names))

        # 1. Ensure namespace exists.
        ns_sql = self._ensure_namespace_sql()
        if ns_sql:
            logger.debug("Ensuring namespace exists: %s", ns_sql)
            try:
                with conn.cursor() as cur:
                    cur.execute(ns_sql)
                conn.commit()
            except Exception as exc:
                raise LoadError(
                    f"Cannot ensure namespace in "
                    f"{self._database}@{self._host}: {exc}"
                ) from exc

        # 2. Pre-drop hook.
        try:
            with conn.cursor() as cur:
                self._pre_drop_hook(cur)
            conn.commit()
        except Exception as exc:
            raise LoadError(f"Pre-drop hook failed: {exc}") from exc

        results_map: dict[str, WriteResult] = {}
        write_error: BaseException | None = None

        try:
            # 3. Per-table: DROP → CREATE → INSERT.
            total_tables = len(ordered_names)
            for i, name in enumerate(ordered_names, start=1):
                df = datasets[name]
                schema_entry = schema_metadata.get(name, {})
                t0 = time.monotonic()
                try:
                    with conn.cursor() as cur:
                        drop_sql = self._drop_table_sql(name)
                        logger.debug("[%s] %s", name, drop_sql)
                        cur.execute(drop_sql)

                        col_defs = self._build_column_defs(df, schema_entry, enforce)
                        create_sql = f"CREATE TABLE {self._table_ref(name)} (\n    {col_defs}\n)"
                        logger.debug("[%s] %s", name, create_sql)
                        cur.execute(create_sql)

                        logger.debug("[%s] inserting %d row(s)", name, df.height)
                        self._bulk_insert(cur, name, df)
                    conn.commit()
                except (ConfigError, LoadError):
                    raise
                except Exception as exc:
                    logger.error("[%s] write failed: %s", name, exc)
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    raise LoadError(
                        f"Failed to write dataset {name!r} to "
                        f"{self._table_ref(name)} in "
                        f"{self._database}@{self._host}: {exc}"
                    ) from exc

                elapsed = time.monotonic() - t0
                logger.info(
                    "[%s] wrote %d row(s) in %.2fs", name, df.height, elapsed,
                    extra={"progress": {"stage": "write", "current": i, "total": total_tables, "label": name}},
                )

                results_map[name] = WriteResult(
                    dataset=name,
                    location=self._build_location(name),
                    rows=df.height,
                )

        except BaseException as exc:
            write_error = exc

        finally:
            # 4. Post-write hook — always runs, best-effort.
            try:
                with conn.cursor() as cur:
                    self._post_write_hook(cur)
                conn.commit()
            except Exception:
                pass  # Never mask the real error.

        if write_error is not None:
            raise write_error

        return [results_map[n] for n in names]
