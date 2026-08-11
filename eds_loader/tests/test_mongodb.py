"""Tests for MongoDBConnector.

All tests use mocked pymongo — no real MongoDB server required.

Mocking strategy
----------------
- ``_inject_client()`` injects a pre-built mock MongoClient directly into
  ``conn._mongo_client``, bypassing ``_client()``.
- The mock client uses ``__getitem__`` to return a mock database, which in
  turn uses ``__getitem__`` to return per-collection mock objects.
- Connection tests patch ``eds_loader.connectors.mongodb._pymongo``.

``pytest.importorskip("pymongo")`` skips the whole file if pymongo is not
installed.  pymongo is listed in ``[dev]`` deps so it is always present in
a normal dev environment.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, call, patch

import polars as pl
import pytest

pymongo = pytest.importorskip("pymongo")  # skip if not installed

from eds_loader.connectors.mongodb import MongoDBConnector
from eds_loader.connectors.registry import CONNECTORS
from eds_loader.exceptions import LoadError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(**kwargs: Any) -> MongoDBConnector:
    defaults: dict[str, Any] = dict(
        host="localhost",
        database="test_db",
        password="test_pass",
    )
    defaults.update(kwargs)
    return MongoDBConnector(**defaults)


def _inject_client(
    conn: MongoDBConnector,
    collection_names: list[str] | None = None,
) -> tuple[MagicMock, MagicMock, dict[str, MagicMock]]:
    """Inject a mock MongoClient, bypassing _client().

    Returns:
        ``(mock_client, mock_db, collections_map)``
        where ``collections_map[name]`` is the mock collection object.
    """
    collections: dict[str, MagicMock] = {}

    if collection_names:
        for name in collection_names:
            collections[name] = MagicMock()

    def _get_collection(name: str) -> MagicMock:
        if name not in collections:
            collections[name] = MagicMock()
        return collections[name]

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=_get_collection)

    mock_client = MagicMock()
    mock_client.__getitem__ = MagicMock(return_value=mock_db)

    conn._mongo_client = mock_client
    return mock_client, mock_db, collections


def _sample_schema() -> dict:
    return {
        "customers": {
            "primary_key": "customer_id",
            "unique_columns": ["email"],
            "foreign_keys": [],
        },
        "orders": {
            "primary_key": "order_id",
            "unique_columns": [],
            "foreign_keys": [
                {"column": "customer_id", "references": "customers",
                 "referenced_column": "customer_id", "nullable": False}
            ],
        },
    }


def _sample_datasets() -> dict[str, pl.DataFrame]:
    return {
        "customers": pl.DataFrame({
            "customer_id": [1, 2, 3],
            "email": ["a@x.com", "b@x.com", "c@x.com"],
        }),
        "orders": pl.DataFrame({
            "order_id": [10, 11],
            "customer_id": [1, 2],
            "amount": [99.9, 49.5],
        }),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_mongodb_is_registered() -> None:
    import eds_loader  # noqa: F401
    assert "mongodb" in CONNECTORS


def test_mongodb_is_write_only() -> None:
    spec = CONNECTORS["mongodb"]
    assert spec.can_write is True
    assert spec.can_read is False


def test_mongodb_requires_pymongo() -> None:
    spec = CONNECTORS["mongodb"]
    assert "pymongo" in spec.required_packages
    assert spec.install_extra == "mongodb"


def test_mongodb_connector_class_is_set_when_pymongo_available() -> None:
    spec = CONNECTORS["mongodb"]
    assert spec.connector_class is MongoDBConnector


def test_mongodb_not_readable_by_protocol() -> None:
    from eds_loader.connectors.base import Readable
    conn = _make_conn()
    assert not isinstance(conn, Readable)


# ---------------------------------------------------------------------------
# Constructor / attributes
# ---------------------------------------------------------------------------

def test_constructor_stores_defaults() -> None:
    conn = _make_conn()
    assert conn._host == "localhost"
    assert conn._database == "test_db"
    assert conn._port == 27017
    assert conn._auth_source == "admin"
    assert conn._connect_timeout == 10000


def test_constructor_custom_port() -> None:
    conn = _make_conn(port=27018)
    assert conn._port == 27018


# ---------------------------------------------------------------------------
# _resolve_password
# ---------------------------------------------------------------------------

def test_resolve_password_inline() -> None:
    conn = _make_conn(password="secret")
    assert conn._resolve_password() == "secret"


def test_resolve_password_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGO_PASS", "from_env")
    conn = _make_conn(password=None, password_env="MONGO_PASS")
    assert conn._resolve_password() == "from_env"


def test_resolve_password_missing_env_raises_load_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_MONGO_PASS", raising=False)
    conn = _make_conn(password=None, password_env="MISSING_MONGO_PASS")
    with pytest.raises(LoadError, match="MISSING_MONGO_PASS"):
        conn._resolve_password()


# ---------------------------------------------------------------------------
# _client / connection
# ---------------------------------------------------------------------------

def test_client_calls_mongo_client_with_correct_params() -> None:
    conn = _make_conn(host="mghost", port=27019, database="mydb",
                      username="admin", password="s3cr3t", auth_source="mydb")
    with patch("eds_loader.connectors.mongodb._pymongo") as mock_pm:
        mock_pm.MongoClient.return_value = MagicMock()
        conn._mongo_client = None
        conn._client()
        mock_pm.MongoClient.assert_called_once_with(
            host="mghost",
            port=27019,
            serverSelectionTimeoutMS=10000,
            username="admin",
            password="s3cr3t",
            authSource="mydb",
        )


def test_client_without_username_omits_auth_params() -> None:
    conn = _make_conn(host="mghost", username=None, password=None)
    with patch("eds_loader.connectors.mongodb._pymongo") as mock_pm:
        mock_pm.MongoClient.return_value = MagicMock()
        conn._mongo_client = None
        conn._client()
        _, kwargs = mock_pm.MongoClient.call_args
        assert "username" not in kwargs
        assert "password" not in kwargs
        assert "authSource" not in kwargs


def test_client_caches_connection() -> None:
    conn = _make_conn()
    mock_client, _, _ = _inject_client(conn)
    c1 = conn._client()
    c2 = conn._client()
    assert c1 is c2


def test_client_creation_error_raises_load_error() -> None:
    conn = _make_conn()
    with patch("eds_loader.connectors.mongodb._pymongo") as mock_pm:
        mock_pm.MongoClient.side_effect = Exception("invalid host")
        conn._mongo_client = None
        with pytest.raises(LoadError, match="Cannot create MongoDB client"):
            conn._client()


def test_client_password_env_resolved_on_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MONGO_PW", "env_pass")
    conn = _make_conn(username="u", password=None, password_env="MONGO_PW")
    with patch("eds_loader.connectors.mongodb._pymongo") as mock_pm:
        mock_pm.MongoClient.return_value = MagicMock()
        conn._mongo_client = None
        conn._client()
        _, kwargs = mock_pm.MongoClient.call_args
        assert kwargs["password"] == "env_pass"


# ---------------------------------------------------------------------------
# write_datasets — collection operations
# ---------------------------------------------------------------------------

def test_write_datasets_drops_each_collection() -> None:
    conn = _make_conn()
    _, _, colls = _inject_client(conn, ["customers", "orders"])
    conn.write_datasets(_sample_datasets(), schema_metadata={})
    colls["customers"].drop.assert_called_once()
    colls["orders"].drop.assert_called_once()


def test_write_datasets_inserts_documents() -> None:
    conn = _make_conn()
    df = pl.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})
    _, _, colls = _inject_client(conn, ["data"])
    conn.write_datasets({"data": df}, schema_metadata={})
    colls["data"].insert_many.assert_called_once()
    docs = colls["data"].insert_many.call_args[0][0]
    assert docs == df.to_dicts()


def test_write_datasets_drop_before_insert() -> None:
    """drop() must always be called before insert_many()."""
    conn = _make_conn()
    order_of_calls: list[str] = []

    mock_collection = MagicMock()
    mock_collection.drop.side_effect = lambda: order_of_calls.append("drop")
    mock_collection.insert_many.side_effect = lambda _: order_of_calls.append("insert")

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_client = MagicMock()
    mock_client.__getitem__ = MagicMock(return_value=mock_db)
    conn._mongo_client = mock_client

    conn.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})
    assert order_of_calls == ["drop", "insert"]


def test_write_datasets_empty_df_skips_insert() -> None:
    conn = _make_conn()
    df = pl.DataFrame({"id": pl.Series([], dtype=pl.Int64)})
    _, _, colls = _inject_client(conn, ["empty"])
    conn.write_datasets({"empty": df}, schema_metadata={})
    colls["empty"].drop.assert_called_once()
    colls["empty"].insert_many.assert_not_called()


def test_write_datasets_empty_df_still_called_drop() -> None:
    """Even an empty DF should clear the existing collection."""
    conn = _make_conn()
    df = pl.DataFrame({"id": pl.Series([], dtype=pl.Int64)})
    _, _, colls = _inject_client(conn, ["empty"])
    conn.write_datasets({"empty": df}, schema_metadata={})
    colls["empty"].drop.assert_called_once()


# ---------------------------------------------------------------------------
# write_datasets — results
# ---------------------------------------------------------------------------

def test_write_datasets_returns_one_result_per_dataset() -> None:
    conn = _make_conn()
    _inject_client(conn)
    datasets = _sample_datasets()
    results = conn.write_datasets(datasets, schema_metadata={})
    assert len(results) == len(datasets)
    assert {r.dataset for r in results} == set(datasets)


def test_write_datasets_result_rows_match_df_height() -> None:
    conn = _make_conn()
    _inject_client(conn)
    datasets = _sample_datasets()
    results = conn.write_datasets(datasets, schema_metadata={})
    rows_by_name = {r.dataset: r.rows for r in results}
    for name, df in datasets.items():
        assert rows_by_name[name] == df.height


def test_write_datasets_result_location_is_mongodb_url() -> None:
    conn = _make_conn(host="mgserver", port=27020, database="mydb")
    _inject_client(conn, ["tbl"])
    results = conn.write_datasets({"tbl": pl.DataFrame({"id": [1]})},
                                   schema_metadata={})
    assert results[0].location == "mongodb://mgserver:27020/mydb/tbl"


def test_write_datasets_results_in_original_order() -> None:
    conn = _make_conn()
    _inject_client(conn)
    datasets = {"z": pl.DataFrame({"id": [1]}), "a": pl.DataFrame({"id": [2]})}
    results = conn.write_datasets(datasets, schema_metadata={})
    assert [r.dataset for r in results] == list(datasets)


# ---------------------------------------------------------------------------
# write_datasets — no FK ordering (collections are independent)
# ---------------------------------------------------------------------------

def test_write_datasets_preserves_original_order_no_sort() -> None:
    """MongoDB does not need topological sort — datasets written as-is."""
    conn = _make_conn()
    write_order: list[str] = []

    mock_db = MagicMock()

    def _get_coll(name: str) -> MagicMock:
        coll = MagicMock()
        coll.drop.side_effect = lambda: write_order.append(name)
        return coll

    mock_db.__getitem__ = MagicMock(side_effect=_get_coll)
    mock_client = MagicMock()
    mock_client.__getitem__ = MagicMock(return_value=mock_db)
    conn._mongo_client = mock_client

    datasets = {"orders": pl.DataFrame({"id": [1]}),
                "customers": pl.DataFrame({"id": [2]})}
    conn.write_datasets(datasets, schema_metadata=_sample_schema())

    # Written in original dict order — NOT customers-first (no sort)
    assert write_order == list(datasets)


# ---------------------------------------------------------------------------
# Index creation
# ---------------------------------------------------------------------------

def test_create_indexes_pk_creates_unique_index() -> None:
    mock_collection = MagicMock()
    schema_entry = {
        "primary_key": "customer_id",
        "unique_columns": [],
        "foreign_keys": [],
    }
    MongoDBConnector._create_indexes(mock_collection, schema_entry)
    mock_collection.create_index.assert_any_call("customer_id", unique=True)


def test_create_indexes_unique_columns() -> None:
    mock_collection = MagicMock()
    schema_entry = {
        "primary_key": None,
        "unique_columns": ["email", "username"],
        "foreign_keys": [],
    }
    MongoDBConnector._create_indexes(mock_collection, schema_entry)
    calls = mock_collection.create_index.call_args_list
    assert call("email", unique=True) in calls
    assert call("username", unique=True) in calls


def test_create_indexes_fk_columns_create_regular_index() -> None:
    mock_collection = MagicMock()
    schema_entry = {
        "primary_key": None,
        "unique_columns": [],
        "foreign_keys": [
            {"column": "customer_id", "references": "customers",
             "referenced_column": "customer_id", "nullable": False}
        ],
    }
    MongoDBConnector._create_indexes(mock_collection, schema_entry)
    mock_collection.create_index.assert_any_call("customer_id", unique=False)


def test_create_indexes_empty_schema_no_index_calls() -> None:
    mock_collection = MagicMock()
    MongoDBConnector._create_indexes(mock_collection, {})
    mock_collection.create_index.assert_not_called()


def test_write_datasets_with_schema_creates_pk_index() -> None:
    conn = _make_conn()
    _, _, colls = _inject_client(conn, ["customers"])
    conn.write_datasets(
        {"customers": pl.DataFrame({"customer_id": [1], "email": ["a@x.com"]})},
        schema_metadata=_sample_schema(),
    )
    colls["customers"].create_index.assert_any_call("customer_id", unique=True)


def test_write_datasets_with_schema_creates_unique_index_for_unique_column() -> None:
    conn = _make_conn()
    _, _, colls = _inject_client(conn, ["customers"])
    conn.write_datasets(
        {"customers": pl.DataFrame({"customer_id": [1], "email": ["a@x.com"]})},
        schema_metadata=_sample_schema(),
    )
    colls["customers"].create_index.assert_any_call("email", unique=True)


def test_write_datasets_with_schema_creates_regular_index_for_fk() -> None:
    conn = _make_conn()
    _, _, colls = _inject_client(conn, ["orders"])
    conn.write_datasets(
        {"orders": pl.DataFrame({"order_id": [1], "customer_id": [1], "amount": [9.9]})},
        schema_metadata=_sample_schema(),
    )
    colls["orders"].create_index.assert_any_call("customer_id", unique=False)


def test_write_datasets_without_schema_no_index_calls() -> None:
    conn = _make_conn()
    _, _, colls = _inject_client(conn, ["customers"])
    conn.write_datasets(
        {"customers": pl.DataFrame({"customer_id": [1]})},
        schema_metadata={},  # empty = no constraints
    )
    colls["customers"].create_index.assert_not_called()


# ---------------------------------------------------------------------------
# Type conversion — df.to_dicts()
# ---------------------------------------------------------------------------

def test_to_dicts_integer_columns_are_python_ints() -> None:
    df = pl.DataFrame({"id": pl.Series([1, 2, 3], dtype=pl.Int64)})
    docs = df.to_dicts()
    assert all(isinstance(d["id"], int) for d in docs)


def test_to_dicts_float_columns_are_python_floats() -> None:
    df = pl.DataFrame({"val": pl.Series([1.1, 2.2], dtype=pl.Float64)})
    docs = df.to_dicts()
    assert all(isinstance(d["val"], float) for d in docs)


def test_to_dicts_null_values_become_none() -> None:
    df = pl.DataFrame({"id": [1, None, 3]})
    docs = df.to_dicts()
    assert docs[1]["id"] is None


def test_to_dicts_list_column_becomes_python_list() -> None:
    df = pl.DataFrame({"tags": [[1, 2], [3, 4]]})
    docs = df.to_dicts()
    assert docs[0]["tags"] == [1, 2]
    assert isinstance(docs[0]["tags"], list)


def test_to_dicts_struct_column_becomes_python_dict() -> None:
    df = pl.DataFrame({"meta": [{"key": "a", "val": 1}]})
    docs = df.to_dicts()
    assert docs[0]["meta"] == {"key": "a", "val": 1}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_write_datasets_drop_error_raises_load_error() -> None:
    conn = _make_conn()
    mock_collection = MagicMock()
    mock_collection.drop.side_effect = Exception("network error")
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_client = MagicMock()
    mock_client.__getitem__ = MagicMock(return_value=mock_db)
    conn._mongo_client = mock_client

    with pytest.raises(LoadError, match="Failed to write"):
        conn.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})


def test_write_datasets_insert_error_raises_load_error() -> None:
    conn = _make_conn()
    mock_collection = MagicMock()
    mock_collection.insert_many.side_effect = Exception("duplicate key")
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_client = MagicMock()
    mock_client.__getitem__ = MagicMock(return_value=mock_db)
    conn._mongo_client = mock_client

    with pytest.raises(LoadError, match="Failed to write"):
        conn.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

def test_context_manager_creates_client_on_enter() -> None:
    conn = _make_conn()
    with patch("eds_loader.connectors.mongodb._pymongo") as mock_pm:
        mock_pm.MongoClient.return_value = MagicMock()
        conn._mongo_client = None
        with conn:
            assert conn._mongo_client is not None


def test_context_manager_closes_client_on_exit() -> None:
    conn = _make_conn()
    mock_client, _, _ = _inject_client(conn)
    with conn:
        pass
    mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# Integration — through load()
# ---------------------------------------------------------------------------

def test_integration_local_fs_to_mongodb_via_load(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Full load() pipeline: local_fs source → mongodb target (mocked)."""
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    datasets = _sample_datasets()
    schema = _sample_schema()

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name, df in datasets.items():
        df.write_parquet(source_dir / f"{name}.parquet")
    (source_dir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")

    mongo_conn = _make_conn()
    _, _, colls = _inject_client(mongo_conn, list(datasets))

    original_get_connector = __import__(
        "eds_loader.connectors.registry", fromlist=["get_connector"]
    ).get_connector

    def _patched(kind: str, config: dict) -> Any:
        if kind == "mongodb":
            return mongo_conn
        return original_get_connector(kind, config)

    with patch("eds_loader.loader.get_connector", side_effect=_patched):
        config = LoaderConfig(
            source={"kind": "local_fs", "path": str(source_dir)},
            target={
                "kind": "mongodb",
                "host": "mock",
                "database": "db",
            },
        )
        result = load(config)

    expected_rows = sum(df.height for df in datasets.values())
    assert result.total_rows == expected_rows
    assert set(result.tables_written) == set(datasets)

    # Every collection was inserted
    for name in datasets:
        colls[name].insert_many.assert_called_once()


def test_integration_enforce_false_no_indexes_created(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """When enforce_constraints=False, no indexes are created."""
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    datasets = _sample_datasets()
    source_dir = tmp_path / "source2"
    source_dir.mkdir()
    for name, df in datasets.items():
        df.write_parquet(source_dir / f"{name}.parquet")
    (source_dir / "schema.json").write_text(
        json.dumps(_sample_schema()), encoding="utf-8"
    )

    mongo_conn = _make_conn()
    _, _, colls = _inject_client(mongo_conn, list(datasets))

    original_get_connector = __import__(
        "eds_loader.connectors.registry", fromlist=["get_connector"]
    ).get_connector

    def _patched(kind: str, config: dict) -> Any:
        if kind == "mongodb":
            return mongo_conn
        return original_get_connector(kind, config)

    with patch("eds_loader.loader.get_connector", side_effect=_patched):
        config = LoaderConfig(
            source={"kind": "local_fs", "path": str(source_dir)},
            target={"kind": "mongodb", "host": "mock", "database": "db"},
            enforce_constraints=False,
        )
        load(config)

    for coll in colls.values():
        coll.create_index.assert_not_called()
