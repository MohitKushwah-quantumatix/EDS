"""Tests for MySQLConnector.

All tests use mocked pymysql — no real MySQL server required.

pymysql is in [dev] deps so it is always installed in a dev environment.
``pytest.importorskip("pymysql")`` skips the whole file if it's absent.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

pymysql = pytest.importorskip("pymysql")  # skip if not installed

from eds_loader.connectors.mysql import MySQLConnector, _MYSQL_TYPE_MAP
from eds_loader.connectors.registry import CONNECTORS
from eds_loader.connectors._sql_base import BaseSQLConnector
from eds_loader.exceptions import LoadError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(**kwargs: Any) -> MySQLConnector:
    defaults: dict[str, Any] = dict(
        host="localhost",
        database="test_db",
        user="test_user",
        password="test_pass",
    )
    defaults.update(kwargs)
    return MySQLConnector(**defaults)


def _inject_conn(conn: MySQLConnector) -> tuple[MagicMock, MagicMock]:
    """Inject a mock pymysql connection + cursor, bypassing _connect()."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = False
    conn._conn = mock_conn
    return mock_conn, mock_cursor


def _sample_schema() -> dict:
    return {
        "customers": {
            "columns": {"customer_id": "int64", "name": "string"},
            "primary_key": "customer_id",
            "unique_columns": [],
            "foreign_keys": [],
        },
        "orders": {
            "columns": {"order_id": "int64", "customer_id": "int64"},
            "primary_key": "order_id",
            "unique_columns": [],
            "foreign_keys": [
                {
                    "column": "customer_id",
                    "references": "customers",
                    "referenced_column": "customer_id",
                    "nullable": False,
                }
            ],
        },
    }


def _sample_datasets() -> dict[str, pl.DataFrame]:
    return {
        "customers": pl.DataFrame({"customer_id": [1, 2], "name": ["A", "B"]}),
        "orders": pl.DataFrame({"order_id": [10], "customer_id": [1]}),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_mysql_is_registered() -> None:
    import eds_loader  # noqa: F401
    assert "mysql" in CONNECTORS


def test_mysql_is_write_only() -> None:
    spec = CONNECTORS["mysql"]
    assert spec.can_write is True
    assert spec.can_read is False


def test_mysql_requires_pymysql() -> None:
    spec = CONNECTORS["mysql"]
    assert "pymysql" in spec.required_packages
    assert spec.install_extra == "mysql"


def test_mysql_connector_class_is_set_when_pymysql_available() -> None:
    spec = CONNECTORS["mysql"]
    assert spec.connector_class is MySQLConnector


def test_mysql_inherits_base_sql_connector() -> None:
    assert issubclass(MySQLConnector, BaseSQLConnector)


# ---------------------------------------------------------------------------
# Type mapping — MySQL-specific differences
# ---------------------------------------------------------------------------

def test_mysql_float64_maps_to_double_not_double_precision() -> None:
    conn = _make_conn()
    assert conn._polars_dtype_to_sql(pl.Float64()) == "DOUBLE"


def test_mysql_duration_maps_to_bigint() -> None:
    conn = _make_conn()
    assert conn._polars_dtype_to_sql(pl.Duration()) == "BIGINT"


def test_mysql_list_maps_to_json_not_jsonb() -> None:
    conn = _make_conn()
    assert conn._polars_dtype_to_sql(pl.List(pl.Int32())) == "JSON"


def test_mysql_struct_maps_to_json() -> None:
    conn = _make_conn()
    assert conn._polars_dtype_to_sql(pl.Struct({})) == "JSON"


def test_mysql_int64_maps_to_bigint() -> None:
    conn = _make_conn()
    assert conn._polars_dtype_to_sql(pl.Int64()) == "BIGINT"


def test_mysql_int32_maps_to_int() -> None:
    conn = _make_conn()
    assert conn._polars_dtype_to_sql(pl.Int32()) == "INT"


def test_mysql_int8_maps_to_tinyint() -> None:
    conn = _make_conn()
    assert conn._polars_dtype_to_sql(pl.Int8()) == "TINYINT"


def test_mysql_uint32_maps_to_int_unsigned() -> None:
    conn = _make_conn()
    assert conn._polars_dtype_to_sql(pl.UInt32()) == "INT UNSIGNED"


def test_mysql_unknown_dtype_falls_back_to_text() -> None:
    class _Fake(pl.DataType):
        pass
    conn = _make_conn()
    assert conn._polars_dtype_to_sql(_Fake()) == "TEXT"


# ---------------------------------------------------------------------------
# Quoting and table reference
# ---------------------------------------------------------------------------

def test_quote_uses_backticks() -> None:
    conn = _make_conn()
    assert conn._quote("my_table") == "`my_table`"


def test_table_ref_uses_database_and_backticks() -> None:
    conn = _make_conn(database="eds_db")
    assert conn._table_ref("customers") == "`eds_db`.`customers`"


def test_drop_table_sql_no_cascade() -> None:
    conn = _make_conn(database="eds_db")
    sql = conn._drop_table_sql("orders")
    assert "CASCADE" not in sql
    assert "`eds_db`.`orders`" in sql
    assert "DROP TABLE IF EXISTS" in sql


# ---------------------------------------------------------------------------
# FK check hooks
# ---------------------------------------------------------------------------

def test_pre_drop_hook_sets_fk_checks_zero() -> None:
    conn = _make_conn()
    mock_cursor = MagicMock()
    conn._pre_drop_hook(mock_cursor)
    mock_cursor.execute.assert_called_once_with("SET FOREIGN_KEY_CHECKS = 0")


def test_post_write_hook_restores_fk_checks() -> None:
    conn = _make_conn()
    mock_cursor = MagicMock()
    conn._post_write_hook(mock_cursor)
    mock_cursor.execute.assert_called_once_with("SET FOREIGN_KEY_CHECKS = 1")


def test_write_datasets_calls_fk_checks_off_before_drop() -> None:
    conn = _make_conn()
    _, mock_cursor = _inject_conn(conn)

    conn.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})

    all_calls = [str(c[0][0]) for c in mock_cursor.execute.call_args_list]
    fk_off_idx = next(i for i, s in enumerate(all_calls) if "FOREIGN_KEY_CHECKS = 0" in s)
    drop_idx = next(i for i, s in enumerate(all_calls) if "DROP TABLE" in s)
    assert fk_off_idx < drop_idx


def test_write_datasets_calls_fk_checks_on_after_writes() -> None:
    conn = _make_conn()
    _, mock_cursor = _inject_conn(conn)

    conn.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})

    all_calls = [str(c[0][0]) for c in mock_cursor.execute.call_args_list]
    drop_idx = next(i for i, s in enumerate(all_calls) if "DROP TABLE" in s)
    fk_on_idx = next(i for i, s in enumerate(all_calls) if "FOREIGN_KEY_CHECKS = 1" in s)
    assert drop_idx < fk_on_idx


def test_write_datasets_fk_checks_restored_even_on_error() -> None:
    conn = _make_conn()
    mock_conn, mock_cursor = _inject_conn(conn)

    # 1st execute = ensure_namespace, 2nd = FK off, 3rd = DROP (fail)
    mock_cursor.execute.side_effect = [None, None, Exception("DB down")]

    with pytest.raises(Exception):
        conn.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})

    all_calls = [str(c[0][0]) for c in mock_cursor.execute.call_args_list]
    assert any("FOREIGN_KEY_CHECKS = 1" in s for s in all_calls)


# ---------------------------------------------------------------------------
# DDL — backtick quoting in CREATE TABLE
# ---------------------------------------------------------------------------

def test_write_datasets_create_table_uses_backtick_quoting() -> None:
    conn = _make_conn(database="eds_db")
    _, mock_cursor = _inject_conn(conn)

    conn.write_datasets({"customers": pl.DataFrame({"id": [1]})}, schema_metadata={})

    sql_calls = [str(c[0][0]) for c in mock_cursor.execute.call_args_list]
    create_sql = next(s for s in sql_calls if "CREATE TABLE" in s)
    assert "`eds_db`.`customers`" in create_sql
    assert '"' not in create_sql  # no double-quote (Postgres style)


def test_write_datasets_with_constraints_uses_backtick_references() -> None:
    conn = _make_conn(database="eds_db")
    _, mock_cursor = _inject_conn(conn)
    datasets = _sample_datasets()

    conn.write_datasets(datasets, schema_metadata=_sample_schema())

    sql_calls = [str(c[0][0]) for c in mock_cursor.execute.call_args_list]
    orders_create = next(s for s in sql_calls if "CREATE TABLE" in s and "orders" in s)
    assert "REFERENCES `eds_db`.`customers`" in orders_create


# ---------------------------------------------------------------------------
# Namespace — CREATE DATABASE
# ---------------------------------------------------------------------------

def test_ensure_namespace_sql_creates_database() -> None:
    conn = _make_conn(database="eds_db")
    sql = conn._ensure_namespace_sql()
    assert "CREATE DATABASE IF NOT EXISTS" in sql
    assert "`eds_db`" in sql


def test_write_datasets_creates_database_first() -> None:
    conn = _make_conn()
    _, mock_cursor = _inject_conn(conn)
    conn.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})
    first_sql = str(mock_cursor.execute.call_args_list[0][0][0])
    assert "CREATE DATABASE" in first_sql


# ---------------------------------------------------------------------------
# Location URL
# ---------------------------------------------------------------------------

def test_build_location_is_mysql_url() -> None:
    conn = _make_conn(host="dbserver", port=3307, database="mydb")
    assert conn._build_location("tbl") == "mysql://dbserver:3307/mydb/tbl"


def test_write_datasets_result_location_is_mysql_url() -> None:
    conn = _make_conn(host="srv", port=3306, database="db")
    _inject_conn(conn)
    results = conn.write_datasets({"tbl": pl.DataFrame({"id": [1]})}, schema_metadata={})
    assert results[0].location.startswith("mysql://srv:3306/db/")
    assert "tbl" in results[0].location


# ---------------------------------------------------------------------------
# FK ordering (inherited from base)
# ---------------------------------------------------------------------------

def test_write_datasets_fk_table_created_before_referencing() -> None:
    conn = _make_conn()
    _, mock_cursor = _inject_conn(conn)
    conn.write_datasets(_sample_datasets(), schema_metadata=_sample_schema())

    sql_calls = [str(c[0][0]) for c in mock_cursor.execute.call_args_list]
    create_calls = [s for s in sql_calls if "CREATE TABLE" in s]
    cust_idx = next(i for i, s in enumerate(create_calls) if "customers" in s)
    ord_idx = next(i for i, s in enumerate(create_calls) if "orders" in s)
    assert cust_idx < ord_idx


# ---------------------------------------------------------------------------
# _connect / connection
# ---------------------------------------------------------------------------

def test_connect_calls_pymysql_connect_with_correct_params() -> None:
    conn = _make_conn(host="mydb", port=3307, database="prod", user="admin", password="s3cr3t")
    with patch("eds_loader.connectors.mysql._pymysql") as mock_pm:
        mock_pm.connect.return_value = MagicMock()
        mock_pm.connect.return_value.ping = MagicMock(side_effect=Exception)
        conn._conn = None
        conn._connect()
        mock_pm.connect.assert_called_once_with(
            host="mydb",
            port=3307,
            database="prod",
            user="admin",
            password="s3cr3t",
            charset="utf8mb4",
            connect_timeout=10,
            autocommit=False,
        )


def test_connect_password_env_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYSQL_PASS", "env_secret")
    conn = _make_conn(password=None, password_env="MYSQL_PASS")
    with patch("eds_loader.connectors.mysql._pymysql") as mock_pm:
        mock_pm.connect.return_value = MagicMock()
        conn._conn = None
        conn._connect()
        _, kwargs = mock_pm.connect.call_args
        assert kwargs["password"] == "env_secret"


def test_connect_missing_password_env_raises_load_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_MYSQL_PASS", raising=False)
    conn = _make_conn(password=None, password_env="MISSING_MYSQL_PASS")
    with pytest.raises(LoadError, match="MISSING_MYSQL_PASS"):
        conn._connect()


def test_connect_connection_error_raises_load_error() -> None:
    conn = _make_conn()
    with patch("eds_loader.connectors.mysql._pymysql") as mock_pm:
        mock_pm.connect.side_effect = Exception("connection refused")
        conn._conn = None
        with pytest.raises(LoadError, match="Cannot connect"):
            conn._connect()


def test_connect_caches_live_connection() -> None:
    conn = _make_conn()
    mock_conn, _ = _inject_conn(conn)
    mock_conn.ping.return_value = None  # ping succeeds → connection is live
    c1 = conn._connect()
    c2 = conn._connect()
    assert c1 is c2


# ---------------------------------------------------------------------------
# Integration — through load()
# ---------------------------------------------------------------------------

def test_integration_local_fs_to_mysql_via_load(tmp_path: pytest.TempPathFactory) -> None:
    """Full load() pipeline: local_fs source → mysql target (mocked)."""
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    datasets = _sample_datasets()
    schema = _sample_schema()

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name, df in datasets.items():
        df.write_parquet(source_dir / f"{name}.parquet")
    (source_dir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")

    mysql_conn = _make_conn()
    mock_conn, mock_cursor = _inject_conn(mysql_conn)

    original_get_connector = __import__(
        "eds_loader.connectors.registry", fromlist=["get_connector"]
    ).get_connector

    def _patched(kind: str, config: dict) -> Any:
        if kind == "mysql":
            return mysql_conn
        return original_get_connector(kind, config)

    with patch("eds_loader.loader.get_connector", side_effect=_patched):
        config = LoaderConfig(
            source={"kind": "local_fs", "path": str(source_dir)},
            target={"kind": "mysql", "host": "mock", "database": "db", "user": "u"},
        )
        result = load(config)

    expected_rows = sum(df.height for df in datasets.values())
    assert result.total_rows == expected_rows
    assert set(result.tables_written) == set(datasets)
    assert mock_cursor.executemany.call_count == len(datasets)
