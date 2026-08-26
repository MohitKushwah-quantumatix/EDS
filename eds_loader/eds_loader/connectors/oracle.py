"""Oracle Database connector — write target.

Inherits all shared write logic from
:class:`~eds_loader.connectors._sql_base.BaseSQLConnector`.
Oracle-specific details: oracledb connection, double-quote identifiers,
Oracle type map, and schema-based namespacing.

Driver
------
:pypi:`oracledb` v2+ (``pip install eds-loader[oracle]``).

When oracledb is not installed, this module still imports cleanly and
registers the connector with ``connector_class=None``.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from eds_loader.connectors._sql_base import BaseSQLConnector
from eds_loader.connectors.registry import ConnectorSpec, register_connector
from eds_loader.exceptions import LoadError

__all__ = ["OracleConnector"]

try:
    import oracledb as _oracledb  # type: ignore[import]
    _ORACLEDB_AVAILABLE = True
except ImportError:
    _oracledb = None  # type: ignore[assignment]
    _ORACLEDB_AVAILABLE = False

# ---------------------------------------------------------------------------
# Oracle type map
# ---------------------------------------------------------------------------
_ORA_TYPE_MAP: dict[str, str] = {
    "Int8":        "NUMBER(5)",
    "Int16":       "NUMBER(5)",
    "Int32":       "NUMBER(10)",
    "Int64":       "NUMBER(19)",
    "UInt8":       "NUMBER(5)",
    "UInt16":      "NUMBER(5)",
    "UInt32":      "NUMBER(10)",
    "UInt64":      "NUMBER(20)",
    "Float32":     "BINARY_FLOAT",
    "Float64":     "BINARY_DOUBLE",
    "String":      "VARCHAR2(4000)",
    "Utf8":        "VARCHAR2(4000)",
    "Boolean":     "NUMBER(1)",
    "Date":        "DATE",
    "Datetime":    "TIMESTAMP",
    "Duration":    "INTERVAL DAY TO SECOND",
    "List":        "CLOB",
    "Struct":      "CLOB",
    "Null":        "VARCHAR2(4000)",
}


class OracleConnector(BaseSQLConnector):
    """Write datasets to Oracle Database.

    Config fields
    -------------
    ``host``         : Oracle DB hostname / IP (required).
    ``database``     : Service name or SID (required).
    ``user``         : Username (required).
    ``password`` / ``password_env``: Credentials.
    ``port``         : Default 1521.
    ``schema``       : Target schema (defaults to ``user``).
    ``mode``         : ``"thin"`` (default, no Oracle Client needed) or ``"thick"``.
    """

    def __init__(
        self,
        host: str,
        database: str,
        user: str,
        password: str | None = None,
        password_env: str | None = None,
        port: int = 1521,
        schema: str | None = None,
        mode: str = "thin",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            host=host, database=database, user=user, port=port,
            password=password, password_env=password_env, **kwargs,
        )
        self._schema = (schema or user).upper()
        self._mode = mode

    # ------------------------------------------------------------------
    # Abstract implementations
    # ------------------------------------------------------------------

    def _connect(self) -> Any:
        if self._conn is not None:
            return self._conn
        if _oracledb is None:
            raise LoadError(
                "oracledb is not installed. Fix: pip install eds-loader[oracle]"
            )
        password = self._resolve_password()
        if not password:
            raise LoadError("Oracle connector requires a password (password or password_env).")
        try:
            if self._mode == "thick":
                _oracledb.init_oracle_client()
            dsn = f"{self._host}:{self._port}/{self._database}"
            self._conn = _oracledb.connect(user=self._user, password=password, dsn=dsn)
            return self._conn
        except Exception as exc:
            raise LoadError(
                f"Cannot connect to Oracle at {self._user}@{self._host}:{self._port}"
                f"/{self._database}: {exc}"
            ) from exc

    def _disconnect(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _quote(self, name: str) -> str:
        return f'"{name.upper()}"'

    def _table_ref(self, name: str) -> str:
        return f'"{self._schema}"."{name.upper()}"'

    def _sql_type_map(self) -> dict[str, str]:
        return _ORA_TYPE_MAP

    def _drop_table_sql(self, name: str) -> str:
        # Oracle has no DROP TABLE IF EXISTS; wrap in PL/SQL block
        return (
            f"BEGIN\n"
            f"  EXECUTE IMMEDIATE 'DROP TABLE {self._table_ref(name)} CASCADE CONSTRAINTS';\n"
            f"EXCEPTION\n"
            f"  WHEN OTHERS THEN\n"
            f"    IF SQLCODE != -942 THEN RAISE; END IF;\n"
            f"END;"
        )

    def _build_location(self, name: str) -> str:
        return f"oracle://{self._host}:{self._port}/{self._database}/{self._schema}.{name}"

    def _ensure_namespace_sql(self) -> str:
        # Oracle schemas = users; we can't CREATE SCHEMA generically here.
        # Return empty string — assume the schema/user already exists.
        return ""

    def _placeholder(self) -> str:
        # oracledb uses :1, :2, … positional bind variables
        return ":%d"

    def _placeholder_list(self, n: int) -> str:
        return ", ".join(f":{i}" for i in range(1, n + 1))

    def _create_if_not_exists_sql(self, name: str, df: pl.DataFrame,
                                   schema_entry: dict, enforce: bool) -> str:
        col_defs = self._build_column_defs(df, schema_entry, enforce)
        table_ref = self._table_ref(name)
        return (
            f"BEGIN\n"
            f"  EXECUTE IMMEDIATE 'CREATE TABLE {table_ref} ({col_defs})';\n"
            f"EXCEPTION\n"
            f"  WHEN OTHERS THEN\n"
            f"    IF SQLCODE != -955 THEN RAISE; END IF;\n"  # ORA-00955: name already in use
            f"END;"
        )

    def _upsert_sql(self, table_name: str, df: pl.DataFrame, pk_col: str) -> str:
        """Oracle MERGE INTO ... USING DUAL ..."""
        cols = df.columns
        placeholders = self._placeholder_list(len(cols))
        quoted_cols = ", ".join(self._quote(c) for c in cols)
        non_pk = [c for c in cols if c != pk_col]
        source_aliases = ", ".join(f":{i} AS {self._quote(c)}" for i, c in enumerate(cols, 1))
        on_clause = f"target.{self._quote(pk_col)} = source.{self._quote(pk_col)}"
        insert_vals = ", ".join(f"source.{self._quote(c)}" for c in cols)

        merge = (
            f"MERGE INTO {self._table_ref(table_name)} target\n"
            f"USING (SELECT {source_aliases} FROM DUAL) source\n"
            f"ON ({on_clause})\n"
        )
        if non_pk:
            update_set = ", ".join(
                f"target.{self._quote(c)} = source.{self._quote(c)}" for c in non_pk
            )
            merge += f"WHEN MATCHED THEN UPDATE SET {update_set}\n"
        merge += (
            f"WHEN NOT MATCHED THEN INSERT ({quoted_cols})\n"
            f"VALUES ({insert_vals})"
        )
        return merge

    def _bulk_insert(self, cursor: Any, table_name: str, df: pl.DataFrame) -> None:
        cols = df.columns
        placeholders = self._placeholder_list(len(cols))
        quoted_cols = ", ".join(self._quote(c) for c in cols)
        sql = f"INSERT INTO {self._table_ref(table_name)} ({quoted_cols}) VALUES ({placeholders})"
        if df.height > 0:
            cursor.executemany(sql, df.rows())


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------
register_connector(
    "oracle",
    ConnectorSpec(
        connector_class=OracleConnector if _ORACLEDB_AVAILABLE else None,
        required_packages=["oracledb"],
        install_extra="oracle",
        can_read=False,
        can_write=True,
        description=(
            "Oracle Database — writes datasets as relational tables. "
            "Supports MERGE-based upsert. "
            "Requires: pip install eds-loader[oracle]"
        ),
    ),
)
