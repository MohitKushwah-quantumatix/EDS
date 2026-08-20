"""Microsoft SQL Server connector — write target.

Inherits all shared write logic from
:class:`~eds_loader.connectors._sql_base.BaseSQLConnector`.
Only MSSQL-specific details live here: pyodbc connection, square-bracket
identifier style, T-SQL type map, and schema-based namespacing.

Driver
------
:pypi:`pyodbc` (``pip install eds-loader[mssql]``).

Unlike psycopg/pymysql, pyodbc is a thin wrapper around a *native* ODBC
driver that must be installed on the OS separately — e.g. "ODBC Driver 17
for SQL Server" (Windows/Linux/macOS installers from Microsoft). The
``driver`` config field names exactly which installed driver to use.

When pyodbc is not installed, this module still imports cleanly and
registers the connector with ``connector_class=None``.

MSSQL-specific behaviour worth knowing
---------------------------------------
- **No FOREIGN_KEY_CHECKS-style session switch.** SQL Server refuses to
  ``DROP TABLE`` any table still referenced by a ``FOREIGN KEY``
  constraint, and T-SQL has no MySQL-style "disable all FK checks for
  this session" flag. :meth:`MSSQLConnector._pre_drop_hook` works around
  this by dropping every FK constraint in the target schema up front
  (safe, since every table is about to be fully recreated anyway).
- **``NVARCHAR(MAX)`` can't be a key column** — same class of error as
  MySQL's ``TEXT``/error-1170 issue. Handled via
  :meth:`MSSQLConnector._indexable_string_type`.
- **``fast_executemany``** is turned on for bulk inserts — without it,
  pyodbc issues one round-trip per row, which is dramatically slower for
  the larger EDS tables.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from eds_loader.connectors._sql_base import BaseSQLConnector
from eds_loader.connectors.registry import ConnectorSpec, register_connector
from eds_loader.exceptions import LoadError

__all__ = ["MSSQLConnector"]

# Optional dependency — wrapped so the module always imports cleanly.
try:
    import pyodbc as _pyodbc  # type: ignore[import]
    _PYODBC_AVAILABLE = True
except ImportError:
    _pyodbc = None  # type: ignore[assignment]
    _PYODBC_AVAILABLE = False

# ---------------------------------------------------------------------------
# Polars → MSSQL (T-SQL) type map
# ---------------------------------------------------------------------------
_MSSQL_TYPE_MAP: dict[str, str] = {
    "Int8":        "SMALLINT",
    "Int16":       "SMALLINT",
    "Int32":       "INT",
    "Int64":       "BIGINT",
    "UInt8":       "INT",
    "UInt16":      "INT",
    "UInt32":      "BIGINT",
    "UInt64":      "BIGINT",
    "Float32":     "REAL",
    "Float64":     "FLOAT",
    "String":      "NVARCHAR(MAX)",
    "Utf8":        "NVARCHAR(MAX)",
    "Categorical": "NVARCHAR(MAX)",
    "Enum":        "NVARCHAR(MAX)",
    "Boolean":     "BIT",
    "Date":        "DATE",
    "Datetime":    "DATETIME2",
    "Duration":    "BIGINT",
    "Time":        "TIME",
    "List":        "NVARCHAR(MAX)",   # stored as JSON text — no native JSON type pre-2022
    "Array":       "NVARCHAR(MAX)",
    "Struct":      "NVARCHAR(MAX)",
}


def _polars_dtype_to_mssql(dtype: pl.DataType) -> str:
    """Map a Polars dtype to an MSSQL type string.

    Kept as a module-level function for the same reason as the Postgres/
    MySQL equivalents: convenient direct import from tests.
    """
    return _MSSQL_TYPE_MAP.get(type(dtype).__name__, "NVARCHAR(MAX)")


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class MSSQLConnector(BaseSQLConnector):
    """Write EDS datasets to a Microsoft SQL Server database.

    Implements :class:`~eds_loader.connectors.base.Writable` via
    :class:`~eds_loader.connectors._sql_base.BaseSQLConnector`.

    Config fields
    -------------
    ``host`` (required)
        SQL Server hostname or IP.
    ``database`` (required)
        Target database name.
    ``user`` (required)
        Login username (SQL authentication).
    ``password`` / ``password_env``
        Inline password or env-var name. ``password_env`` is preferred.
    ``port``
        Server port (default: ``1433``).
    ``schema``
        Target schema (default: ``"dbo"``).
    ``driver``
        Installed ODBC driver name (default: ``"ODBC Driver 17 for SQL
        Server"``). Must match a driver actually installed on this
        machine — run ``python -c "import pyodbc; print(pyodbc.drivers())"``
        to list what's available.
    ``encrypt``
        Whether to require an encrypted connection (default: ``True`` —
        matches modern SQL Server / Azure SQL defaults).
    ``trust_server_certificate``
        Skip certificate validation — useful for self-signed certs on a
        local/dev server (default: ``False``).
    ``connect_timeout``
        Seconds (default: ``10``).

    Example config::

        target:
          kind: mssql
          host: localhost
          database: eds_db
          user: eds_loader
          password_env: EDS_MSSQL_PASSWORD
    """

    def __init__(
        self,
        host: str,
        database: str,
        user: str,
        port: int = 1433,
        schema: str = "dbo",
        driver: str = "ODBC Driver 17 for SQL Server",
        encrypt: bool = True,
        trust_server_certificate: bool = False,
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
        self._driver = driver
        self._encrypt = encrypt
        self._trust_server_certificate = trust_server_certificate

    # ------------------------------------------------------------------
    # Abstract method overrides — dialect-specific
    # ------------------------------------------------------------------

    def _connect(self) -> Any:
        if self._conn is not None:
            try:
                # pyodbc has no `.closed`; a lightweight probe query
                # confirms whether the connection is still usable.
                self._conn.cursor().execute("SELECT 1")
                return self._conn
            except Exception:
                self._conn = None
        password = self._resolve_password()
        conn_str = (
            f"DRIVER={{{self._driver}}};"
            f"SERVER={self._host},{self._port};"
            f"DATABASE={self._database};"
            f"UID={self._user};"
            f"PWD={password};"
            f"Encrypt={'yes' if self._encrypt else 'no'};"
            f"TrustServerCertificate={'yes' if self._trust_server_certificate else 'no'};"
            f"Connection Timeout={self._connect_timeout};"
        )
        try:
            self._conn = _pyodbc.connect(conn_str, autocommit=False)
            return self._conn
        except Exception as exc:
            raise LoadError(
                f"Cannot connect to MSSQL at "
                f"{self._user}@{self._host}:{self._port}/{self._database}: {exc}\n"
                f"If this is a driver error, confirm {self._driver!r} is installed "
                f"(list installed drivers with "
                f"`python -c \"import pyodbc; print(pyodbc.drivers())\"`)."
            ) from exc

    def _disconnect(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _quote(self, name: str) -> str:
        # MSSQL escapes a literal ']' inside a bracketed identifier as ']]'.
        return f"[{name.replace(']', ']]')}]"

    def _table_ref(self, name: str) -> str:
        return f"{self._quote(self._schema)}.{self._quote(name)}"

    def _sql_type_map(self) -> dict[str, str]:
        return _MSSQL_TYPE_MAP

    def _drop_table_sql(self, name: str) -> str:
        # SQL Server 2016+ / Azure SQL support `DROP TABLE IF EXISTS`.
        # There is no CASCADE keyword in T-SQL — FK constraints referencing
        # this table are removed up front by `_pre_drop_hook` instead.
        return f"DROP TABLE IF EXISTS {self._table_ref(name)}"

    def _build_location(self, name: str) -> str:
        return (
            f"mssql://{self._host}:{self._port}"
            f"/{self._database}/{self._schema}.{name}"
        )

    # ------------------------------------------------------------------
    # Overridable defaults — MSSQL-specific behaviour
    # ------------------------------------------------------------------

    def _placeholder(self) -> str:
        return "?"

    def _ensure_namespace_sql(self) -> str:
        return (
            f"IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'{self._schema}') "
            f"EXEC('CREATE SCHEMA {self._quote(self._schema)}')"
        )

    def _pre_drop_hook(self, cursor: Any) -> None:
        # SQL Server blocks DROP TABLE on any table still referenced by a
        # FOREIGN KEY constraint, and T-SQL has no per-session "disable FK
        # checks" switch like MySQL's SET FOREIGN_KEY_CHECKS=0. Since every
        # table is about to be fully recreated from schema_metadata anyway,
        # drop every FK constraint in this schema up front so the DROP TABLE
        # loop never fails regardless of dependency direction.
        cursor.execute(
            """
            DECLARE @sql NVARCHAR(MAX) = N'';
            SELECT @sql += N'ALTER TABLE ' + QUOTENAME(SCHEMA_NAME(t.schema_id))
                + N'.' + QUOTENAME(t.name) + N' DROP CONSTRAINT '
                + QUOTENAME(fk.name) + N';'
            FROM sys.foreign_keys AS fk
            JOIN sys.tables AS t ON fk.parent_object_id = t.object_id
            WHERE SCHEMA_NAME(t.schema_id) = ?;
            EXEC sp_executesql @sql;
            """,
            (self._schema,),
        )

    def _indexable_string_type(self, sql_type: str) -> str | None:
        # MSSQL error: "Column 'x' in table 'y' is of a type that is
        # invalid for use as a key column in an index." NVARCHAR(MAX) has
        # no defined max length, so it can't back a PK/UNIQUE/FK — same
        # class of problem as MySQL's TEXT (see mysql.py).
        if sql_type == "NVARCHAR(MAX)":
            return "NVARCHAR(255)"
        return None

    def _bulk_insert(self, cursor: Any, table_name: str, df: pl.DataFrame) -> None:
        # Without fast_executemany, pyodbc sends one round-trip per row —
        # dramatically slower than psycopg/pymysql's native batching for
        # the larger EDS tables. Safe to enable unconditionally here.
        cursor.fast_executemany = True
        super()._bulk_insert(cursor, table_name, df)


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------
register_connector(
    "mssql",
    ConnectorSpec(
        connector_class=MSSQLConnector if _PYODBC_AVAILABLE else None,
        required_packages=["pyodbc"],
        install_extra="mssql",
        can_read=False,
        can_write=True,
        description=(
            "Microsoft SQL Server — writes datasets as relational tables with "
            "optional PK/UNIQUE/FK enforcement. Requires an installed ODBC "
            "driver in addition to the Python package. "
            "Requires: pip install eds-loader[mssql]"
        ),
    ),
)
