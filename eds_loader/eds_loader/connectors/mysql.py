"""MySQL connector — write target.

Inherits all shared write logic from
:class:`~eds_loader.connectors._sql_base.BaseSQLConnector`.
Only MySQL-specific details live here: pymysql connection, backtick quoting,
MySQL type map, DATABASE namespace, and FK-check disabling for DROP TABLE.

Driver
------
:pypi:`pymysql` (``pip install eds-loader[mysql]``).

When pymysql is not installed, this module still imports cleanly and
registers the connector with ``connector_class=None``.

MySQL vs Postgres — key differences
-------------------------------------
* Identifier quoting: backtick ( `` ` `` ) instead of double-quote.
* Namespace: ``DATABASE`` not ``SCHEMA``.  Tables are referenced as
  `` `database`.`table` ``.
* No ``CASCADE`` on ``DROP TABLE`` — FK checks are temporarily disabled
  via ``SET FOREIGN_KEY_CHECKS = 0`` before the drop loop and restored
  via ``SET FOREIGN_KEY_CHECKS = 1`` afterwards (even on error).
* Type differences: ``DOUBLE`` not ``DOUBLE PRECISION``; ``JSON`` not
  ``JSONB``; ``DURATION`` stored as ``BIGINT`` (microseconds).
"""

from __future__ import annotations

from typing import Any

import polars as pl

from eds_loader.connectors._sql_base import BaseSQLConnector
from eds_loader.connectors.registry import ConnectorSpec, register_connector
from eds_loader.exceptions import LoadError

__all__ = ["MySQLConnector"]

# Optional dependency — wrapped so the module always imports cleanly.
try:
    import pymysql as _pymysql  # type: ignore[import]
    _PYMYSQL_AVAILABLE = True
except ImportError:
    _pymysql = None  # type: ignore[assignment]
    _PYMYSQL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Polars → MySQL type map
# ---------------------------------------------------------------------------
_MYSQL_TYPE_MAP: dict[str, str] = {
    "Int8":        "TINYINT",
    "Int16":       "SMALLINT",
    "Int32":       "INT",
    "Int64":       "BIGINT",
    "UInt8":       "TINYINT UNSIGNED",
    "UInt16":      "SMALLINT UNSIGNED",
    "UInt32":      "INT UNSIGNED",
    "UInt64":      "BIGINT UNSIGNED",
    "Float32":     "FLOAT",
    "Float64":     "DOUBLE",          # not DOUBLE PRECISION
    "String":      "TEXT",
    "Utf8":        "TEXT",
    "Categorical": "TEXT",
    "Enum":        "TEXT",
    "Boolean":     "BOOLEAN",
    "Date":        "DATE",
    "Datetime":    "DATETIME",
    "Duration":    "BIGINT",          # MySQL has no INTERVAL; store µs
    "Time":        "TIME",
    "List":        "JSON",            # not JSONB
    "Array":       "JSON",
    "Struct":      "JSON",
}


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class MySQLConnector(BaseSQLConnector):
    """Write EDS datasets to a MySQL database.

    Implements :class:`~eds_loader.connectors.base.Writable` via
    :class:`~eds_loader.connectors._sql_base.BaseSQLConnector`.

    Config fields
    -------------
    ``host`` (required)
        MySQL server hostname or IP.
    ``database`` (required)
        Target database name.
    ``user`` (required)
        Login username.
    ``password`` / ``password_env``
        Inline password or env-var name.  ``password_env`` is preferred.
    ``port``
        Server port (default: ``3306``).
    ``charset``
        Character set (default: ``"utf8mb4"``).
    ``connect_timeout``
        Seconds (default: ``10``).

    Example config::

        target:
          kind: mysql
          host: localhost
          database: eds_db
          user: eds_loader
          password_env: EDS_MYSQL_PASSWORD
    """

    def __init__(
        self,
        host: str,
        database: str,
        user: str,
        port: int = 3306,
        password: str | None = None,
        password_env: str | None = None,
        charset: str = "utf8mb4",
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
        self._charset = charset

    # ------------------------------------------------------------------
    # Abstract method overrides — dialect-specific
    # ------------------------------------------------------------------

    def _connect(self) -> Any:
        if self._conn is not None:
            try:
                # ping() raises if the connection is dead.
                self._conn.ping(reconnect=False)
                return self._conn
            except Exception:
                self._conn = None

        password = self._resolve_password()
        try:
            self._conn = _pymysql.connect(
                host=self._host,
                port=self._port,
                database=self._database,
                user=self._user,
                password=password or "",
                charset=self._charset,
                connect_timeout=self._connect_timeout,
                autocommit=False,
            )
            return self._conn
        except Exception as exc:
            raise LoadError(
                f"Cannot connect to MySQL at "
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
        return f"`{name}`"

    def _table_ref(self, name: str) -> str:
        return f"`{self._database}`.`{name}`"

    def _sql_type_map(self) -> dict[str, str]:
        return _MYSQL_TYPE_MAP

    def _drop_table_sql(self, name: str) -> str:
        # MySQL does not support DROP TABLE … CASCADE.
        # FK checks are disabled via _pre_drop_hook instead.
        return f"DROP TABLE IF EXISTS `{self._database}`.`{name}`"

    def _build_location(self, name: str) -> str:
        return f"mysql://{self._host}:{self._port}/{self._database}/{name}"

    def _ensure_namespace_sql(self) -> str:
        return f"CREATE DATABASE IF NOT EXISTS `{self._database}`"

    def _pre_drop_hook(self, cursor: Any) -> None:
        """Disable FK enforcement before the DROP TABLE loop."""
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

    def _post_write_hook(self, cursor: Any) -> None:
        """Re-enable FK enforcement after all tables are written."""
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

    # _placeholder → "%s" (base default — correct for pymysql)
    # _topological_sort, write_datasets, etc. — fully inherited


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------
register_connector(
    "mysql",
    ConnectorSpec(
        connector_class=MySQLConnector if _PYMYSQL_AVAILABLE else None,
        required_packages=["pymysql"],
        install_extra="mysql",
        can_read=False,
        can_write=True,
        description=(
            "MySQL — writes datasets as relational tables with optional "
            "PK/UNIQUE/FK enforcement. "
            "Requires: pip install eds-loader[mysql]"
        ),
    ),
)
