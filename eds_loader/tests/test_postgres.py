"""Tests for PostgresConnector.

All tests use mocked psycopg — no real PostgreSQL server required.

Mocking strategy
----------------
- **Unit tests** inject a pre-built mock connection directly into
  ``conn._conn``, bypassing ``_connect()``.
- **Connection tests** patch ``eds_loader.connectors.postgres._psycopg``.
- **Static helpers** (``_polars_dtype_to_pg``, ``_topological_sort``,
  ``_build_column_defs``) are tested without any mocking.

``pytest.importorskip("psycopg")`` skips the whole file if psycopg is not
installed.  psycopg is listed in ``[dev]`` deps so it is always present in
a normal dev environment.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import polars as pl
import pytest

psycopg = pytest.importorskip("psycopg")  # skip if not installed

from eds_loader.connectors.postgres import (
    PostgresConnector,
    _polars_dtype_to_pg,
)
from eds_loader.connectors.registry import CONNECTORS
from eds_loader.exceptions import ConfigError, LoadError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(**kwargs: Any) -> PostgresConnector:
    """Build a PostgresConnector without opening a real DB connection."""
    defaults: dict[str, Any] = dict(
        host="localhost",
        database="test_db",
        user="test_user",
        password="test_pass",
    )
    defaults.update(kwargs)
    return PostgresConnector(**defaults)


def _inject_conn(connector: PostgresConnector) -> tuple[MagicMock, MagicMock]:
    """Inject a mock psycopg connection + cursor, bypassing _connect().

    Returns:
        ``(mock_conn, mock_cursor)`` — the cursor is what ``__enter__``
        returns from the context manager.
    """
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.closed = False
    # Make  `with conn.cursor() as cur:` return mock_cursor
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = False
    connector._conn = mock_conn
    return mock_conn, mock_cursor


def _sample_schema() -> dict:
    return {
        "customers": {
            "columns": {"customer_id": "int64", "name": "string"},
            "primary_key": "customer_id",
            "unique_columns": ["name"],
            "foreign_keys": [],
        },
        "orders": {
            "columns": {"order_id": "int64", "customer_id": "int64", "amount": "float64"},
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
        "customers": pl.DataFrame(
            {"customer_id": [1, 2, 3], "name": ["Alice", "Bob", "Carol"]}
        ),
        "orders": pl.DataFrame(
            {"order_id": [10, 11], "customer_id": [1, 2], "amount": [99.9, 49.5]}
        ),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_postgres_is_registered() -> None:
    import eds_loader  # noqa: F401
    assert "postgres" in CONNECTORS


def test_postgres_is_write_only() -> None:
    spec = CONNECTORS["postgres"]
    assert spec.can_write is True
    assert spec.can_read is False


def test_postgres_requires_psycopg() -> None:
    spec = CONNECTORS["postgres"]
    assert "psycopg" in spec.required_packages
    assert spec.install_extra == "postgres"


def test_postgres_connector_class_is_set_when_psycopg_available() -> None:
    spec = CONNECTORS["postgres"]
    assert spec.connector_class is PostgresConnector


def test_postgres_not_readable_by_protocol() -> None:
    """PostgresConnector does not satisfy the Readable protocol."""
    from eds_loader.connectors.base import Readable
    conn = _make_conn()
    assert not isinstance(conn, Readable)


# ---------------------------------------------------------------------------
# _polars_dtype_to_pg — type mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dtype,expected", [
    (pl.Int8(),           "SMALLINT"),
    (pl.Int16(),          "SMALLINT"),
    (pl.Int32(),          "INTEGER"),
    (pl.Int64(),          "BIGINT"),
    (pl.UInt8(),          "INTEGER"),
    (pl.UInt16(),         "INTEGER"),
    (pl.UInt32(),         "BIGINT"),
    (pl.UInt64(),         "BIGINT"),
    (pl.Float32(),        "REAL"),
    (pl.Float64(),        "DOUBLE PRECISION"),
    (pl.String(),         "TEXT"),
    (pl.Boolean(),        "BOOLEAN"),
    (pl.Date(),           "DATE"),
    (pl.Datetime(),       "TIMESTAMP"),
    (pl.Duration(),       "INTERVAL"),
    (pl.List(pl.Int32()), "JSONB"),
])
def test_polars_dtype_to_pg(dtype: pl.DataType, expected: str) -> None:
    assert _polars_dtype_to_pg(dtype) == expected


def test_polars_dtype_to_pg_unknown_falls_back_to_text() -> None:
    """An unknown dtype should safely fall back to TEXT."""
    class _FakeDtype(pl.DataType):
        pass
    assert _polars_dtype_to_pg(_FakeDtype()) == "TEXT"


# ---------------------------------------------------------------------------
# _topological_sort
# ---------------------------------------------------------------------------

def test_topological_sort_independent_tables_returns_sorted() -> None:
    schema = {
        "a": {"foreign_keys": []},
        "b": {"foreign_keys": []},
    }
    result = PostgresConnector._topological_sort(schema, ["b", "a"])
    # Both orderings are valid; what matters is all names are present
    assert set(result) == {"a", "b"}


def test_topological_sort_fk_dependency_puts_referenced_first() -> None:
    """orders depends on customers → customers must come first."""
    schema = _sample_schema()
    result = PostgresConnector._topological_sort(schema, ["orders", "customers"])
    assert result.index("customers") < result.index("orders")


def test_topological_sort_three_level_chain() -> None:
    """A → B → C: result order should be C, B, A."""
    schema = {
        "a": {"foreign_keys": [{"column": "x", "references": "b", "referenced_column": "id", "nullable": True}]},
        "b": {"foreign_keys": [{"column": "y", "references": "c", "referenced_column": "id", "nullable": True}]},
        "c": {"foreign_keys": []},
    }
    result = PostgresConnector._topological_sort(schema, ["a", "b", "c"])
    assert result.index("c") < result.index("b") < result.index("a")


def test_topological_sort_circular_dependency_raises_config_error() -> None:
    schema = {
        "a": {"foreign_keys": [{"column": "x", "references": "b", "referenced_column": "id", "nullable": True}]},
        "b": {"foreign_keys": [{"column": "y", "references": "a", "referenced_column": "id", "nullable": True}]},
    }
    with pytest.raises(ConfigError, match="Circular"):
        PostgresConnector._topological_sort(schema, ["a", "b"])


def test_topological_sort_external_reference_ignored() -> None:
    """FK pointing at a table not in the write set should not affect sort."""
    schema = {
        "orders": {"foreign_keys": [
            {"column": "c_id", "references": "customers", "referenced_column": "id", "nullable": False}
        ]},
    }
    # customers is not in the write set — sort should succeed quietly
    result = PostgresConnector._topological_sort(schema, ["orders"])
    assert result == ["orders"]


# ---------------------------------------------------------------------------
# _build_column_defs
# ---------------------------------------------------------------------------

def test_build_column_defs_without_enforce() -> None:
    """With enforce=False, no PK/UNIQUE/FK clauses in DDL."""
    conn = _make_conn()
    df = pl.DataFrame({"order_id": [1], "customer_id": [2]})
    schema_entry = _sample_schema()["orders"]

    ddl = conn._build_column_defs(df, schema_entry, enforce=False)

    assert "PRIMARY KEY" not in ddl
    assert "UNIQUE" not in ddl
    assert "REFERENCES" not in ddl


def test_build_column_defs_with_enforce_adds_primary_key() -> None:
    conn = _make_conn()
    df = pl.DataFrame({"customer_id": [1], "name": ["Alice"]})
    schema_entry = _sample_schema()["customers"]

    ddl = conn._build_column_defs(df, schema_entry, enforce=True)

    assert '"customer_id" BIGINT PRIMARY KEY' in ddl


def test_build_column_defs_with_enforce_adds_unique() -> None:
    conn = _make_conn()
    df = pl.DataFrame({"customer_id": [1], "name": ["Alice"]})
    schema_entry = _sample_schema()["customers"]

    ddl = conn._build_column_defs(df, schema_entry, enforce=True)

    # 'name' is in unique_columns and is not the PK → should get UNIQUE
    assert "UNIQUE" in ddl
    assert '"name"' in ddl


def test_build_column_defs_with_enforce_adds_not_null_and_references() -> None:
    conn = _make_conn()
    df = pl.DataFrame({"order_id": [1], "customer_id": [2], "amount": [9.9]})
    schema_entry = _sample_schema()["orders"]

    ddl = conn._build_column_defs(df, schema_entry, enforce=True)

    assert "NOT NULL" in ddl
    assert "REFERENCES" in ddl
    assert "customers" in ddl


def test_build_column_defs_pk_does_not_get_unique() -> None:
    """PK columns must NOT get a redundant UNIQUE clause."""
    conn = _make_conn()
    df = pl.DataFrame({"id": [1], "val": ["x"]})
    schema_entry = {
        "primary_key": "id",
        "unique_columns": ["id"],  # same column is both PK and unique
        "foreign_keys": [],
    }

    ddl = conn._build_column_defs(df, schema_entry, enforce=True)
    # "PRIMARY KEY" should appear once for id
    assert ddl.count("PRIMARY KEY") == 1
    # "UNIQUE" should NOT appear alongside id
    id_line = next(line for line in ddl.split(",") if '"id"' in line)
    assert "UNIQUE" not in id_line


def test_build_column_defs_nullable_fk_has_no_not_null() -> None:
    """A nullable FK column must not have NOT NULL in the DDL."""
    conn = _make_conn()
    df = pl.DataFrame({"order_id": [1], "cust_id": [2]})
    schema_entry = {
        "primary_key": "order_id",
        "unique_columns": [],
        "foreign_keys": [
            {
                "column": "cust_id",
                "references": "customers",
                "referenced_column": "id",
                "nullable": True,   # <— nullable
            }
        ],
    }

    ddl = conn._build_column_defs(df, schema_entry, enforce=True)

    cust_line = next(line for line in ddl.split(",") if '"cust_id"' in line)
    assert "NOT NULL" not in cust_line
    assert "REFERENCES" in cust_line


# ---------------------------------------------------------------------------
# write_datasets
# ---------------------------------------------------------------------------

def test_write_datasets_creates_schema_first() -> None:
    conn = _make_conn()
    mock_conn, mock_cursor = _inject_conn(conn)

    conn.write_datasets(_sample_datasets(), schema_metadata={})

    # First execute call must be CREATE SCHEMA
    first_call_sql = mock_cursor.execute.call_args_list[0][0][0]
    assert "CREATE SCHEMA IF NOT EXISTS" in first_call_sql


def test_write_datasets_drops_table_before_creating() -> None:
    conn = _make_conn()
    _, mock_cursor = _inject_conn(conn)

    conn.write_datasets({"customers": pl.DataFrame({"id": [1]})}, schema_metadata={})

    sql_calls = [str(c[0][0]) for c in mock_cursor.execute.call_args_list]
    drop_calls = [s for s in sql_calls if "DROP TABLE" in s]
    create_calls = [s for s in sql_calls if "CREATE TABLE" in s]
    assert len(drop_calls) >= 1
    assert len(create_calls) >= 1


def test_write_datasets_drop_uses_cascade() -> None:
    conn = _make_conn()
    _, mock_cursor = _inject_conn(conn)

    conn.write_datasets({"tbl": pl.DataFrame({"a": [1]})}, schema_metadata={})

    sql_calls = [str(c[0][0]) for c in mock_cursor.execute.call_args_list]
    drop_call = next(s for s in sql_calls if "DROP TABLE" in s)
    assert "CASCADE" in drop_call


def test_write_datasets_calls_executemany_with_rows() -> None:
    conn = _make_conn()
    _, mock_cursor = _inject_conn(conn)
    df = pl.DataFrame({"id": [1, 2, 3], "val": ["a", "b", "c"]})

    conn.write_datasets({"data": df}, schema_metadata={})

    mock_cursor.executemany.assert_called_once()
    _, rows = mock_cursor.executemany.call_args[0]
    assert list(rows) == df.rows()


def test_write_datasets_commits_per_table() -> None:
    conn = _make_conn()
    mock_conn, mock_cursor = _inject_conn(conn)
    datasets = _sample_datasets()

    conn.write_datasets(datasets, schema_metadata={})

    # Base class commits: 1 (ensure_namespace) + 1 (pre_hook) + N (per table) + 1 (post_hook)
    # For postgres: ensure_namespace = CREATE SCHEMA → 1 commit
    # pre_hook = no-op but still commits → 1 commit
    # 2 tables → 2 commits
    # post_hook = no-op but still commits → 1 commit
    # Total = 5
    assert mock_conn.commit.call_count == 1 + 1 + len(datasets) + 1


def test_write_datasets_returns_one_result_per_dataset() -> None:
    conn = _make_conn()
    _inject_conn(conn)
    datasets = _sample_datasets()

    results = conn.write_datasets(datasets, schema_metadata={})

    assert len(results) == len(datasets)
    assert {r.dataset for r in results} == set(datasets)


def test_write_datasets_result_rows_match_dataframe_height() -> None:
    conn = _make_conn()
    _inject_conn(conn)
    datasets = _sample_datasets()

    results = conn.write_datasets(datasets, schema_metadata={})
    rows_by_name = {r.dataset: r.rows for r in results}

    for name, df in datasets.items():
        assert rows_by_name[name] == df.height


def test_write_datasets_result_location_is_postgres_url() -> None:
    conn = _make_conn(host="dbserver", port=5433, database="mydb")
    _inject_conn(conn)

    results = conn.write_datasets({"tbl": pl.DataFrame({"id": [1]})}, schema_metadata={})

    assert results[0].location.startswith("postgres://dbserver:5433/mydb/")
    assert "tbl" in results[0].location


def test_write_datasets_with_constraints_creates_fk_ddl() -> None:
    conn = _make_conn()
    _, mock_cursor = _inject_conn(conn)
    datasets = _sample_datasets()

    conn.write_datasets(datasets, schema_metadata=_sample_schema())

    sql_calls = [str(c[0][0]) for c in mock_cursor.execute.call_args_list]
    create_orders = next(s for s in sql_calls if "CREATE TABLE" in s and "orders" in s)
    assert "REFERENCES" in create_orders
    assert "customers" in create_orders


def test_write_datasets_fk_table_created_before_referencing_table() -> None:
    """customers must be created before orders when constraints are enforced."""
    conn = _make_conn()
    _, mock_cursor = _inject_conn(conn)

    conn.write_datasets(_sample_datasets(), schema_metadata=_sample_schema())

    sql_calls = [str(c[0][0]) for c in mock_cursor.execute.call_args_list]
    create_calls = [s for s in sql_calls if "CREATE TABLE" in s]
    customers_idx = next(i for i, s in enumerate(create_calls) if "customers" in s)
    orders_idx = next(i for i, s in enumerate(create_calls) if "orders" in s)
    assert customers_idx < orders_idx


def test_write_datasets_empty_dataframe_no_executemany_call() -> None:
    """An empty DataFrame should not trigger an INSERT."""
    conn = _make_conn()
    _, mock_cursor = _inject_conn(conn)
    df = pl.DataFrame({"id": pl.Series([], dtype=pl.Int64)})

    conn.write_datasets({"empty": df}, schema_metadata={})

    mock_cursor.executemany.assert_not_called()


def test_write_datasets_db_error_raises_load_error() -> None:
    conn = _make_conn()
    mock_conn, mock_cursor = _inject_conn(conn)
    mock_cursor.execute.side_effect = [None, None, Exception("DB error")]

    with pytest.raises(LoadError, match="Failed to write"):
        conn.write_datasets({"tbl": pl.DataFrame({"id": [1]})}, schema_metadata={})


def test_write_datasets_db_error_calls_rollback() -> None:
    conn = _make_conn()
    mock_conn, mock_cursor = _inject_conn(conn)
    mock_cursor.execute.side_effect = [None, None, Exception("oops")]

    with pytest.raises(LoadError):
        conn.write_datasets({"tbl": pl.DataFrame({"id": [1]})}, schema_metadata={})

    mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# _connect / connection handling
# ---------------------------------------------------------------------------

def test_connect_calls_psycopg_connect_with_correct_params() -> None:
    conn = _make_conn(host="mydb", port=5433, database="prod", user="admin", password="secret")
    with patch("eds_loader.connectors.postgres._psycopg") as mock_pm:
        mock_pm.connect.return_value = MagicMock(closed=False)
        mock_pm.OperationalError = psycopg.OperationalError

        conn._conn = None
        conn._connect()

        mock_pm.connect.assert_called_once_with(
            host="mydb",
            port=5433,
            dbname="prod",
            user="admin",
            password="secret",
            connect_timeout=10,
        )


def test_connect_password_env_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_PASS", "env_secret")
    conn = _make_conn(password=None, password_env="PG_PASS")
    with patch("eds_loader.connectors.postgres._psycopg") as mock_pm:
        mock_pm.connect.return_value = MagicMock(closed=False)
        conn._conn = None
        conn._connect()
        _, kwargs = mock_pm.connect.call_args
        assert kwargs["password"] == "env_secret"


def test_connect_missing_password_env_raises_load_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_PG_PASS", raising=False)
    conn = _make_conn(password=None, password_env="MISSING_PG_PASS")
    with pytest.raises(LoadError, match="MISSING_PG_PASS"):
        conn._connect()


def test_connect_connection_error_raises_load_error() -> None:
    conn = _make_conn()
    with patch("eds_loader.connectors.postgres._psycopg") as mock_pm:
        mock_pm.connect.side_effect = Exception("connection refused")
        conn._conn = None
        with pytest.raises(LoadError, match="Cannot connect"):
            conn._connect()


def test_connect_caches_connection() -> None:
    conn = _make_conn()
    mock_conn, _ = _inject_conn(conn)
    c1 = conn._connect()
    c2 = conn._connect()
    assert c1 is c2


def test_context_manager_disconnects_on_exit() -> None:
    conn = _make_conn()
    mock_conn, _ = _inject_conn(conn)
    with conn:
        pass
    mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# Integration — through load()
# ---------------------------------------------------------------------------

def test_integration_local_fs_to_postgres_via_load(tmp_path: pytest.TempPathFactory) -> None:
    """Full load() pipeline: local_fs source → postgres target (mocked)."""
    import json
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    datasets = _sample_datasets()
    schema = _sample_schema()

    # Write parquet + schema.json to local dir (real local_fs source).
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name, df in datasets.items():
        df.write_parquet(source_dir / f"{name}.parquet")
    (source_dir / "schema.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )

    # Patch get_connector for postgres kind to return a mock connector.
    pg_conn = _make_conn()
    mock_conn, mock_cursor = _inject_conn(pg_conn)

    original_get_connector = __import__(
        "eds_loader.connectors.registry", fromlist=["get_connector"]
    ).get_connector

    def _patched(kind: str, config: dict):
        if kind == "postgres":
            return pg_conn
        return original_get_connector(kind, config)

    with patch("eds_loader.loader.get_connector", side_effect=_patched):
        config = LoaderConfig(
            source={"kind": "local_fs", "path": str(source_dir)},
            target={"kind": "postgres", "host": "mock", "database": "db", "user": "u"},
        )
        result = load(config)

    expected_rows = sum(df.height for df in datasets.values())
    assert result.total_rows == expected_rows
    assert set(result.tables_written) == set(datasets)
    # Verify executemany was called (data was actually inserted)
    assert mock_cursor.executemany.call_count == len(datasets)


def test_integration_enforce_false_no_constraints_in_ddl(tmp_path: pytest.TempPathFactory) -> None:
    """When enforce_constraints=False, CREATE TABLE has no REFERENCES."""
    import json
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    datasets = _sample_datasets()
    schema = _sample_schema()

    source_dir = tmp_path / "source2"
    source_dir.mkdir()
    for name, df in datasets.items():
        df.write_parquet(source_dir / f"{name}.parquet")
    (source_dir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")

    pg_conn = _make_conn()
    _, mock_cursor = _inject_conn(pg_conn)

    original_get_connector = __import__(
        "eds_loader.connectors.registry", fromlist=["get_connector"]
    ).get_connector

    def _patched(kind: str, config: dict):
        if kind == "postgres":
            return pg_conn
        return original_get_connector(kind, config)

    with patch("eds_loader.loader.get_connector", side_effect=_patched):
        config = LoaderConfig(
            source={"kind": "local_fs", "path": str(source_dir)},
            target={"kind": "postgres", "host": "mock", "database": "db", "user": "u"},
            enforce_constraints=False,
        )
        load(config)

    sql_calls = [str(c[0][0]) for c in mock_cursor.execute.call_args_list]
    create_calls = [s for s in sql_calls if "CREATE TABLE" in s]
    for ddl in create_calls:
        assert "REFERENCES" not in ddl
        assert "PRIMARY KEY" not in ddl
