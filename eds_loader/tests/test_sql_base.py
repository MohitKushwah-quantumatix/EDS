"""Tests for BaseSQLConnector.

Uses a minimal concrete subclass (_TestConnector) as a test double so the
abstract class can be exercised without depending on any real DB driver.

Coverage:
- Constructor stores common attributes
- _resolve_password — inline and env-var modes
- _polars_dtype_to_sql — delegates through subclass _sql_type_map
- _topological_sort — all cases (independent, chain, circular)
- _build_column_defs — quotes, PK, UNIQUE, FK, enforce=False
- _bulk_insert — SQL shape, rows, empty DF guard
- write_datasets orchestration — namespace, hooks, order, results, errors
- Context manager (__enter__/__exit__)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import polars as pl
import pytest

from eds_loader.connectors._sql_base import BaseSQLConnector
from eds_loader.exceptions import ConfigError, LoadError


# ---------------------------------------------------------------------------
# Concrete test double
# ---------------------------------------------------------------------------

class _TestConnector(BaseSQLConnector):
    """Minimal concrete subclass for testing BaseSQLConnector in isolation."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            host="testhost",
            database="testdb",
            user="testuser",
            port=9999,
            **kwargs,
        )

    def _connect(self) -> Any:
        if self._conn is None:
            self._conn = _make_mock_conn()
        return self._conn

    def _disconnect(self) -> None:
        self._conn = None

    def _quote(self, name: str) -> str:
        return f"[{name}]"

    def _table_ref(self, name: str) -> str:
        return f"[testdb].[{name}]"

    def _sql_type_map(self) -> dict[str, str]:
        return {
            "Int64": "INT",
            "Float64": "DECIMAL",
            "String": "VARCHAR(256)",
        }

    def _drop_table_sql(self, name: str) -> str:
        return f"DROP TABLE IF EXISTS [testdb].[{name}]"

    def _build_location(self, name: str) -> str:
        return f"test://testhost:9999/testdb/{name}"


def _make_mock_conn() -> MagicMock:
    """Return a mock connection where each cursor() call gets its own cursor."""
    mock_conn = MagicMock()
    mock_conn.closed = False

    def _cursor_factory():
        ctx = MagicMock()
        cur = MagicMock()
        ctx.__enter__ = MagicMock(return_value=cur)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    mock_conn.cursor.side_effect = _cursor_factory
    return mock_conn


def _make_tc(**kwargs: Any) -> _TestConnector:
    return _TestConnector(**kwargs)


def _inject_mock_conn(tc: _TestConnector) -> tuple[MagicMock, list[MagicMock]]:
    """Inject a fresh mock connection that returns a new cursor per call.

    Returns:
        ``(mock_conn, cursors_list)`` — cursors_list grows as cursor() is called.
    """
    cursors: list[MagicMock] = []
    mock_conn = MagicMock()
    mock_conn.closed = False

    def _cursor_factory():
        ctx = MagicMock()
        cur = MagicMock()
        ctx.__enter__ = MagicMock(return_value=cur)
        ctx.__exit__ = MagicMock(return_value=False)
        cursors.append(cur)
        return ctx

    mock_conn.cursor.side_effect = _cursor_factory
    tc._conn = mock_conn
    return mock_conn, cursors


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

def test_base_stores_common_attributes() -> None:
    tc = _make_tc()
    assert tc._host == "testhost"
    assert tc._database == "testdb"
    assert tc._user == "testuser"
    assert tc._port == 9999


# ---------------------------------------------------------------------------
# _resolve_password
# ---------------------------------------------------------------------------

def test_resolve_password_inline() -> None:
    tc = _make_tc(password="inline_pass")
    assert tc._resolve_password() == "inline_pass"


def test_resolve_password_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_DB_PASS", "from_env")
    tc = _make_tc(password_env="TEST_DB_PASS")
    assert tc._resolve_password() == "from_env"


def test_resolve_password_missing_env_raises_load_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_PASS", raising=False)
    tc = _make_tc(password_env="MISSING_PASS")
    with pytest.raises(LoadError, match="MISSING_PASS"):
        tc._resolve_password()


def test_resolve_password_returns_none_when_neither_set() -> None:
    tc = _make_tc()
    assert tc._resolve_password() is None


# ---------------------------------------------------------------------------
# _polars_dtype_to_sql
# ---------------------------------------------------------------------------

def test_polars_dtype_to_sql_uses_subclass_type_map() -> None:
    tc = _make_tc()
    assert tc._polars_dtype_to_sql(pl.Int64()) == "INT"
    assert tc._polars_dtype_to_sql(pl.Float64()) == "DECIMAL"
    assert tc._polars_dtype_to_sql(pl.String()) == "VARCHAR(256)"


def test_polars_dtype_to_sql_unknown_falls_back_to_text() -> None:
    class _UnknownDtype(pl.DataType):
        pass
    tc = _make_tc()
    assert tc._polars_dtype_to_sql(_UnknownDtype()) == "TEXT"


# ---------------------------------------------------------------------------
# _topological_sort (static — inheritable, testable via class or instance)
# ---------------------------------------------------------------------------

def test_topological_sort_no_deps_returns_sorted_list() -> None:
    meta = {"a": {"foreign_keys": []}, "b": {"foreign_keys": []}}
    result = BaseSQLConnector._topological_sort(meta, ["b", "a"])
    assert set(result) == {"a", "b"}


def test_topological_sort_fk_referenced_comes_first() -> None:
    meta = {
        "orders": {"foreign_keys": [
            {"column": "c_id", "references": "customers", "referenced_column": "id", "nullable": False}
        ]},
        "customers": {"foreign_keys": []},
    }
    result = BaseSQLConnector._topological_sort(meta, ["orders", "customers"])
    assert result.index("customers") < result.index("orders")


def test_topological_sort_three_level_chain() -> None:
    meta = {
        "a": {"foreign_keys": [{"column": "x", "references": "b", "referenced_column": "id", "nullable": True}]},
        "b": {"foreign_keys": [{"column": "y", "references": "c", "referenced_column": "id", "nullable": True}]},
        "c": {"foreign_keys": []},
    }
    result = BaseSQLConnector._topological_sort(meta, ["a", "b", "c"])
    assert result.index("c") < result.index("b") < result.index("a")


def test_topological_sort_circular_raises_config_error() -> None:
    meta = {
        "a": {"foreign_keys": [{"column": "x", "references": "b", "referenced_column": "id", "nullable": True}]},
        "b": {"foreign_keys": [{"column": "y", "references": "a", "referenced_column": "id", "nullable": True}]},
    }
    with pytest.raises(ConfigError, match="Circular"):
        BaseSQLConnector._topological_sort(meta, ["a", "b"])


def test_topological_sort_external_fk_ref_ignored() -> None:
    meta = {
        "orders": {"foreign_keys": [
            {"column": "c_id", "references": "customers", "referenced_column": "id", "nullable": True}
        ]},
    }
    # "customers" not in names set → ignored
    result = BaseSQLConnector._topological_sort(meta, ["orders"])
    assert result == ["orders"]


# ---------------------------------------------------------------------------
# _build_column_defs
# ---------------------------------------------------------------------------

def test_build_column_defs_uses_subclass_quote() -> None:
    tc = _make_tc()
    df = pl.DataFrame({"id": [1], "name": ["x"]})
    ddl = tc._build_column_defs(df, {}, enforce=False)
    assert "[id]" in ddl
    assert "[name]" in ddl


def test_build_column_defs_enforce_false_no_constraints() -> None:
    tc = _make_tc()
    df = pl.DataFrame({"id": [1], "ref": [2]})
    schema_entry = {
        "primary_key": "id",
        "unique_columns": ["ref"],
        "foreign_keys": [{"column": "ref", "references": "other", "referenced_column": "id", "nullable": False}],
    }
    ddl = tc._build_column_defs(df, schema_entry, enforce=False)
    assert "PRIMARY KEY" not in ddl
    assert "UNIQUE" not in ddl
    assert "REFERENCES" not in ddl


def test_build_column_defs_enforce_true_adds_pk() -> None:
    tc = _make_tc()
    df = pl.DataFrame({"id": [1], "val": ["x"]})
    schema_entry = {"primary_key": "id", "unique_columns": [], "foreign_keys": []}
    ddl = tc._build_column_defs(df, schema_entry, enforce=True)
    assert "PRIMARY KEY" in ddl


def test_build_column_defs_enforce_true_fk_uses_table_ref() -> None:
    tc = _make_tc()
    df = pl.DataFrame({"id": [1], "ref_id": [2]})
    schema_entry = {
        "primary_key": "id",
        "unique_columns": [],
        "foreign_keys": [{"column": "ref_id", "references": "other_tbl", "referenced_column": "pk", "nullable": True}],
    }
    ddl = tc._build_column_defs(df, schema_entry, enforce=True)
    # Must use _table_ref("other_tbl") → [testdb].[other_tbl]
    assert "[testdb].[other_tbl]" in ddl


# ---------------------------------------------------------------------------
# _bulk_insert
# ---------------------------------------------------------------------------

def test_bulk_insert_uses_table_ref_and_placeholder() -> None:
    tc = _make_tc()
    mock_cursor = MagicMock()
    df = pl.DataFrame({"id": [1, 2], "val": ["a", "b"]})
    tc._bulk_insert(mock_cursor, "my_table", df)
    sql = mock_cursor.executemany.call_args[0][0]
    assert "[testdb].[my_table]" in sql
    assert "%s" in sql  # default placeholder


def test_bulk_insert_passes_all_rows() -> None:
    tc = _make_tc()
    mock_cursor = MagicMock()
    df = pl.DataFrame({"id": [10, 20, 30]})
    tc._bulk_insert(mock_cursor, "t", df)
    rows = mock_cursor.executemany.call_args[0][1]
    assert list(rows) == df.rows()


def test_bulk_insert_empty_df_skips_executemany() -> None:
    tc = _make_tc()
    mock_cursor = MagicMock()
    df = pl.DataFrame({"id": pl.Series([], dtype=pl.Int64)})
    tc._bulk_insert(mock_cursor, "t", df)
    mock_cursor.executemany.assert_not_called()


# ---------------------------------------------------------------------------
# write_datasets orchestration
# ---------------------------------------------------------------------------

def test_write_datasets_calls_namespace_sql() -> None:
    class _WithNamespace(_TestConnector):
        def _ensure_namespace_sql(self) -> str:
            return "CREATE DATABASE IF NOT EXISTS [testdb]"

    tc = _WithNamespace()
    mock_conn, cursors = _inject_mock_conn(tc)
    tc.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})
    # First cursor is used for namespace SQL
    first_execute_sql = cursors[0].execute.call_args_list[0][0][0]
    assert "CREATE DATABASE" in first_execute_sql


def test_write_datasets_calls_pre_hook_before_drop() -> None:
    hook_calls: list[str] = []

    class _HookConnector(_TestConnector):
        def _pre_drop_hook(self, cursor: Any) -> None:
            hook_calls.append("pre")
        def _post_write_hook(self, cursor: Any) -> None:
            hook_calls.append("post")

    tc = _HookConnector()
    _inject_mock_conn(tc)
    tc.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})
    assert hook_calls[0] == "pre"
    assert "post" in hook_calls


def test_write_datasets_post_hook_called_even_on_error() -> None:
    """_post_write_hook must be called even when the write loop raises."""
    post_called: list[bool] = []

    class _PostHookConnector(_TestConnector):
        def _post_write_hook(self, cursor: Any) -> None:
            post_called.append(True)

    tc = _PostHookConnector()
    # cursor #1 = pre_hook (no-op), cursor #2 = table write → DROP fails
    mock_conn = _make_mock_conn()
    call_n = [0]

    def _factory():
        ctx = MagicMock()
        cur = MagicMock()
        call_n[0] += 1
        if call_n[0] == 2:  # 2nd cursor = table write (pre_hook is cursor 1)
            cur.execute.side_effect = Exception("DB down")
        ctx.__enter__ = MagicMock(return_value=cur)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    mock_conn.cursor.side_effect = _factory
    tc._conn = mock_conn

    with pytest.raises((LoadError, Exception)):
        tc.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})

    assert post_called  # post-hook still ran


def test_write_datasets_commits_per_table() -> None:
    tc = _make_tc()
    mock_conn, cursors = _inject_mock_conn(tc)
    tc.write_datasets(
        {"a": pl.DataFrame({"id": [1]}), "b": pl.DataFrame({"id": [2]})},
        schema_metadata={},
    )
    # Commits: 1 (pre-drop hook) + 2 (one per table) + 1 (post-write hook) = 4
    assert mock_conn.commit.call_count == 4


def test_write_datasets_returns_results_in_original_order() -> None:
    tc = _make_tc()
    _inject_mock_conn(tc)
    datasets = {"z": pl.DataFrame({"id": [1]}), "a": pl.DataFrame({"id": [2]})}
    results = tc.write_datasets(datasets, schema_metadata={})
    assert [r.dataset for r in results] == list(datasets)


def test_write_datasets_location_uses_build_location() -> None:
    tc = _make_tc()
    _inject_mock_conn(tc)
    results = tc.write_datasets({"tbl": pl.DataFrame({"id": [1]})}, schema_metadata={})
    assert results[0].location == "test://testhost:9999/testdb/tbl"


def test_write_datasets_rows_match_df_height() -> None:
    tc = _make_tc()
    _inject_mock_conn(tc)
    df = pl.DataFrame({"id": [1, 2, 3]})
    results = tc.write_datasets({"t": df}, schema_metadata={})
    assert results[0].rows == 3


def test_write_datasets_db_error_raises_load_error() -> None:
    tc = _make_tc()
    # _TestConnector has no namespace SQL (returns None), so cursor calls:
    # cursor 1 = pre_hook, cursor 2 = table write
    mock_conn = _make_mock_conn()
    call_n = [0]

    def _factory():
        ctx = MagicMock()
        cur = MagicMock()
        call_n[0] += 1
        if call_n[0] == 2:  # 2nd cursor = table write (DROP+CREATE+INSERT)
            cur.execute.side_effect = [None, Exception("syntax error")]
        ctx.__enter__ = MagicMock(return_value=cur)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    mock_conn.cursor.side_effect = _factory
    tc._conn = mock_conn

    with pytest.raises(LoadError, match="Failed to write"):
        tc.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})


def test_write_datasets_db_error_calls_rollback() -> None:
    tc = _make_tc()
    mock_conn = _make_mock_conn()
    call_n = [0]

    def _factory():
        ctx = MagicMock()
        cur = MagicMock()
        call_n[0] += 1
        if call_n[0] == 2:
            cur.execute.side_effect = [None, Exception("oops")]
        ctx.__enter__ = MagicMock(return_value=cur)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    mock_conn.cursor.side_effect = _factory
    tc._conn = mock_conn

    with pytest.raises(Exception):
        tc.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})
    mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

def test_context_manager_enter_calls_connect() -> None:
    tc = _make_tc()
    with tc:
        assert tc._conn is not None


def test_context_manager_exit_disconnects() -> None:
    tc = _make_tc()
    with tc:
        pass
    assert tc._conn is None
