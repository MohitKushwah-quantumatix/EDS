"""PostgreSQL connector — write target.

Inherits all shared write logic from
:class:`~eds_loader.connectors._sql_base.BaseSQLConnector`.
Only PostgreSQL-specific details live here: psycopg3 connection,
double-quote identifier style, PG type map, and schema-based namespacing.

Driver
------
:pypi:`psycopg` v3 (``pip install eds-loader[postgres]``).

When psycopg is not installed, this module still imports cleanly and
registers the connector with ``connector_class=None``.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from eds_loader.connectors._sql_base import BaseSQLConnector
from eds_loader.connectors.registry import ConnectorSpec, register_connector
from eds_loader.exceptions import LoadError

__all__ = ["PostgresConnector"]

# Optional dependency — wrapped so the module always imports cleanly.
try:
    import psycopg as _psycopg  # type: ignore[import]
    _PSYCOPG_AVAILABLE = True
except ImportError:
    _psycopg = None  # type: ignore[assignment]
    _PSYCOPG_AVAILABLE = False

# ---------------------------------------------------------------------------
# Polars → PostgreSQL type map
# ---------------------------------------------------------------------------
_PG_TYPE_MAP: dict[str, str] = {
    "Int8":        "SMALLINT",
    "Int16":       "SMALLINT",
    "Int32":       "INTEGER",
    "Int64":       "BIGINT",
    "UInt8":       "INTEGER",
    "UInt16":      "INTEGER",
    "UInt32":      "BIGINT",
    "UInt64":      "BIGINT",
    "Float32":     "REAL",
    "Float64":     "DOUBLE PRECISION",
    "String":      "TEXT",
    "Utf8":        "TEXT",
    "Categorical": "TEXT",
    "Enum":        "TEXT",
    "Boolean":     "BOOLEAN",
    "Date":        "DATE",
    "Datetime":    "TIMESTAMP",
    "Duration":    "INTERVAL",
    "Time":        "TIME",
    "List":        "JSONB",
    "Array":       "JSONB",
    "Struct":      "JSONB",
}


def _polars_dtype_to_pg(dtype: pl.DataType) -> str:
    """Map a Polars dtype to a PostgreSQL type string.

    Kept as a module-level function for backward compatibility with existing
    tests that import it directly.
    """
    return _PG_TYPE_MAP.get(type(dtype).__name__, "TEXT")


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class PostgresConnector(BaseSQLConnector):
    """Write EDS datasets to a PostgreSQL database.

    Implements :class:`~eds_loader.connectors.base.Writable` via
    :class:`~eds_loader.connectors._sql_base.BaseSQLConnector`.

    Config fields
    -------------
    ``host`` (required)
        Postgres server hostname or IP.
    ``database`` (required)
        Target database name.
    ``user`` (required)
        Login username.
    ``password`` / ``password_env``
        Inline password or env-var name.  ``password_env`` is preferred.
    ``port``
        Server port (default: ``5432``).
    ``schema``
        Target schema (default: ``"public"``).
    ``connect_timeout``
        Seconds (default: ``10``).

    Example config::

        target:
          kind: postgres
          host: localhost
          database: eds_db
          user: eds_loader
          password_env: EDS_PG_PASSWORD
    """

    def __init__(
        self,
        host: str,
        database: str,
        user: str,
        port: int = 5432,
        schema: str = "public",
        password: str | None = None,
        password_env: str | None = None,
        connect_timeout: int = 10,
        **_kwargs: Any,
    ) -> None:
        super().__init__(
            host=host,
            database=database,
            user=user,
            port=port,
            password=password,
            password_env=password_env,
            connect_timeout=connect_timeout,
        )
        self._schema = schema

    # ------------------------------------------------------------------
    # Abstract method overrides — dialect-specific
    # ------------------------------------------------------------------

    def _connect(self) -> Any:
        if self._conn is not None:
            try:
                if not self._conn.closed:
                    return self._conn
            except Exception:
                pass
        password = self._resolve_password()
        try:
            self._conn = _psycopg.connect(
                host=self._host,
                port=self._port,
                dbname=self._database,
                user=self._user,
                password=password,
                connect_timeout=self._connect_timeout,
            )
            return self._conn
        except Exception as exc:
            raise LoadError(
                f"Cannot connect to PostgreSQL at "
                f"{self._user}@{self._host}:{self._port}/{self._database}: {exc}"
            ) from exc

    def _disconnect(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _quote(self, name: str) -> str:
        return f'"{name}"'

    def _table_ref(self, name: str) -> str:
        return f'"{self._schema}"."{name}"'

    def _sql_type_map(self) -> dict[str, str]:
        return _PG_TYPE_MAP

    def _drop_table_sql(self, name: str) -> str:
        return f'DROP TABLE IF EXISTS "{self._schema}"."{name}" CASCADE'

    def _build_location(self, name: str) -> str:
        return (
            f"postgres://{self._host}:{self._port}"
            f"/{self._database}/{self._schema}.{name}"
        )

    def _ensure_namespace_sql(self) -> str:
        return f'CREATE SCHEMA IF NOT EXISTS "{self._schema}"'

    def _upsert_sql(self, table_name: str, df: pl.DataFrame, pk_col: str) -> str:
        """Postgres: INSERT ... ON CONFLICT (pk) DO UPDATE SET ..."""
        quoted_cols = ", ".join(self._quote(c) for c in df.columns)
        non_pk = [c for c in df.columns if c != pk_col]
        placeholders = ", ".join(["%s"] * len(df.columns))
        if non_pk:
            update_set = ", ".join(
                f"{self._quote(c)} = EXCLUDED.{self._quote(c)}" for c in non_pk
            )
            conflict_action = f"DO UPDATE SET {update_set}"
        else:
            # Only a PK column — nothing to update, just ignore duplicates.
            conflict_action = "DO NOTHING"
        return (
            f"INSERT INTO {self._table_ref(table_name)} ({quoted_cols}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT ({self._quote(pk_col)}) {conflict_action}"
        )

    # _placeholder, _pre_drop_hook, _post_write_hook — base defaults OK
    # _topological_sort, write_datasets, upsert_datasets — fully inherited


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------
register_connector(
    "postgres",
    ConnectorSpec(
        connector_class=PostgresConnector if _PSYCOPG_AVAILABLE else None,
        required_packages=["psycopg"],
        install_extra="postgres",
        can_read=False,
        can_write=True,
        description=(
            "PostgreSQL — writes datasets as relational tables with optional "
            "PK/UNIQUE/FK enforcement. "
            "Requires: pip install eds-loader[postgres]"
        ),
    ),
)
