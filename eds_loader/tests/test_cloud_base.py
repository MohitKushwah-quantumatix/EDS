"""Tests for CloudBaseConnector.

Uses a minimal concrete test double (_TestCloudConnector) so the abstract
base can be exercised without depending on any real cloud driver.

Coverage:
- _key() with and without prefix
- _name_from_key() — static helper
- _prefix normalisation (always ends with "/" when non-empty)
- _get_client() — lazy creation + caching
- read_schema_metadata() — success and error paths
- read_datasets() — list + read + parse, empty result, error paths
- write_datasets() — upload Parquet per dataset + schema.json
- write_datasets() — schema_metadata empty → no schema upload
- write_datasets() — WriteResult fields (dataset, rows, location)
- write_datasets() — upload error → LoadError
- read_datasets() — read error → LoadError
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock

import polars as pl
import pytest

from eds_loader.connectors._cloud_base import CloudBaseConnector
from eds_loader.exceptions import LoadError


# ---------------------------------------------------------------------------
# Concrete test double
# ---------------------------------------------------------------------------

class _TestCloud(CloudBaseConnector):
    """Minimal subclass — all abstract methods delegated to MagicMocks."""

    def __init__(self, prefix: str = "") -> None:
        super().__init__(prefix=prefix)
        self._mock_files: dict[str, bytes] = {}   # in-memory "bucket"
        self._parquet_keys: list[str] = []
        self._connect_mock = MagicMock(return_value=MagicMock())
        self._list_calls: list[None] = []
        self._read_calls: list[str] = []
        self._write_calls: list[tuple[str, bytes]] = []

    def _connect(self) -> Any:
        return self._connect_mock()

    def _list_keys_by_extension(self, ext: str) -> list[str]:
        self._list_calls.append(None)
        return [k for k in self._parquet_keys if k.endswith(ext)]

    def _read_bytes(self, key: str) -> bytes:
        self._read_calls.append(key)
        if key not in self._mock_files:
            raise FileNotFoundError(f"Not found: {key}")
        return self._mock_files[key]

    def _write_bytes(self, key: str, data: bytes) -> None:
        self._write_calls.append((key, data))
        self._mock_files[key] = data

    def _location(self, dataset_name: str) -> str:
        return f"test://{self._key(f'{dataset_name}.parquet')}"


def _parquet_bytes(df: pl.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.write_parquet(buf)
    return buf.getvalue()


def _make_cloud(prefix: str = "") -> _TestCloud:
    return _TestCloud(prefix=prefix)


# ---------------------------------------------------------------------------
# _prefix normalisation
# ---------------------------------------------------------------------------

def test_empty_prefix_stays_empty() -> None:
    tc = _make_cloud(prefix="")
    assert tc._prefix == ""


def test_prefix_without_slash_gets_slash_appended() -> None:
    tc = _make_cloud(prefix="data")
    assert tc._prefix == "data/"


def test_prefix_with_trailing_slash_preserved() -> None:
    tc = _make_cloud(prefix="data/")
    assert tc._prefix == "data/"


def test_prefix_with_nested_path() -> None:
    tc = _make_cloud(prefix="datasets/2024/")
    assert tc._prefix == "datasets/2024/"


# ---------------------------------------------------------------------------
# _key()
# ---------------------------------------------------------------------------

def test_key_no_prefix() -> None:
    tc = _make_cloud()
    assert tc._key("schema.json") == "schema.json"


def test_key_with_prefix() -> None:
    tc = _make_cloud(prefix="data/")
    assert tc._key("customers.parquet") == "data/customers.parquet"


def test_key_with_nested_prefix() -> None:
    tc = _make_cloud(prefix="eds/v1")
    assert tc._key("orders.parquet") == "eds/v1/orders.parquet"


# ---------------------------------------------------------------------------
# _name_from_key()
# ---------------------------------------------------------------------------

def test_name_from_key_with_prefix() -> None:
    assert CloudBaseConnector._name_from_key("prefix/customers.parquet", ".parquet") == "customers"


def test_name_from_key_no_prefix() -> None:
    assert CloudBaseConnector._name_from_key("orders.parquet", ".parquet") == "orders"


def test_name_from_key_deep_prefix() -> None:
    assert CloudBaseConnector._name_from_key("a/b/c/products.parquet", ".parquet") == "products"


# ---------------------------------------------------------------------------
# _get_client()
# ---------------------------------------------------------------------------

def test_get_client_calls_connect_on_first_use() -> None:
    tc = _make_cloud()
    tc._get_client()
    tc._connect_mock.assert_called_once()


def test_get_client_caches_result() -> None:
    tc = _make_cloud()
    c1 = tc._get_client()
    c2 = tc._get_client()
    assert c1 is c2
    tc._connect_mock.assert_called_once()


# ---------------------------------------------------------------------------
# read_schema_metadata()
# ---------------------------------------------------------------------------

def test_read_schema_metadata_parses_json() -> None:
    tc = _make_cloud()
    schema = {"customers": {"primary_key": "id"}}
    tc._mock_files["schema.json"] = json.dumps(schema).encode()
    result = tc.read_schema_metadata()
    assert result == schema


def test_read_schema_metadata_with_prefix() -> None:
    tc = _make_cloud(prefix="data/")
    schema = {"tbl": {}}
    tc._mock_files["data/schema.json"] = json.dumps(schema).encode()
    result = tc.read_schema_metadata()
    assert result == schema


def test_read_schema_metadata_missing_raises_load_error() -> None:
    tc = _make_cloud()  # empty _mock_files → FileNotFoundError
    with pytest.raises(LoadError, match="schema.json"):
        tc.read_schema_metadata()


def test_read_schema_metadata_invalid_json_raises_load_error() -> None:
    tc = _make_cloud()
    tc._mock_files["schema.json"] = b"NOT JSON{"
    with pytest.raises(LoadError):
        tc.read_schema_metadata()


# ---------------------------------------------------------------------------
# read_datasets()
# ---------------------------------------------------------------------------

def test_read_datasets_returns_dataframes() -> None:
    tc = _make_cloud()
    df = pl.DataFrame({"id": [1, 2], "name": ["a", "b"]})
    tc._mock_files["customers.parquet"] = _parquet_bytes(df)
    tc._parquet_keys = ["customers.parquet"]
    result = tc.read_datasets()
    assert "customers" in result
    assert result["customers"].shape == df.shape


def test_read_datasets_with_prefix_in_key() -> None:
    tc = _make_cloud(prefix="data/")
    df = pl.DataFrame({"id": [1]})
    tc._mock_files["data/orders.parquet"] = _parquet_bytes(df)
    tc._parquet_keys = ["data/orders.parquet"]
    result = tc.read_datasets()
    assert "orders" in result


def test_read_datasets_multiple_files() -> None:
    tc = _make_cloud()
    dfs = {
        "a": pl.DataFrame({"x": [1]}),
        "b": pl.DataFrame({"y": [2]}),
    }
    for name, df in dfs.items():
        tc._mock_files[f"{name}.parquet"] = _parquet_bytes(df)
    tc._parquet_keys = ["a.parquet", "b.parquet"]
    result = tc.read_datasets()
    assert set(result) == {"a", "b"}


def test_read_datasets_empty_prefix_returns_empty_dict() -> None:
    tc = _make_cloud()
    tc._parquet_keys = []
    assert tc.read_datasets() == {}


def test_read_datasets_list_error_raises_load_error() -> None:
    class _BrokenList(_TestCloud):
        def _list_keys_by_extension(self, ext: str) -> list[str]:
            raise RuntimeError("network error")

    tc = _BrokenList()
    with pytest.raises(LoadError, match="Cannot list"):
        tc.read_datasets()


def test_read_datasets_read_error_raises_load_error() -> None:
    tc = _make_cloud()
    tc._parquet_keys = ["missing.parquet"]  # not in _mock_files
    with pytest.raises(LoadError, match="Cannot read dataset"):
        tc.read_datasets()


# ---------------------------------------------------------------------------
# write_datasets()
# ---------------------------------------------------------------------------

def test_write_datasets_uploads_parquet_per_dataset() -> None:
    tc = _make_cloud()
    df = pl.DataFrame({"id": [1, 2]})
    tc.write_datasets({"customers": df}, schema_metadata={})
    assert "customers.parquet" in tc._mock_files
    recovered = pl.read_parquet(io.BytesIO(tc._mock_files["customers.parquet"]))
    assert recovered.shape == df.shape


def test_write_datasets_with_prefix_uses_correct_key() -> None:
    tc = _make_cloud(prefix="out/")
    df = pl.DataFrame({"id": [1]})
    tc.write_datasets({"tbl": df}, schema_metadata={})
    assert "out/tbl.parquet" in tc._mock_files


def test_write_datasets_uploads_schema_json_when_non_empty() -> None:
    tc = _make_cloud()
    schema = {"customers": {"primary_key": "id"}}
    tc.write_datasets({"customers": pl.DataFrame({"id": [1]})},
                      schema_metadata=schema)
    assert "schema.json" in tc._mock_files
    stored = json.loads(tc._mock_files["schema.json"])
    assert stored == schema


def test_write_datasets_no_schema_json_when_empty_meta() -> None:
    tc = _make_cloud()
    tc.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})
    assert "schema.json" not in tc._mock_files


def test_write_datasets_returns_one_result_per_dataset() -> None:
    tc = _make_cloud()
    datasets = {
        "a": pl.DataFrame({"id": [1]}),
        "b": pl.DataFrame({"id": [2, 3]}),
    }
    results = tc.write_datasets(datasets, schema_metadata={})
    assert len(results) == 2
    assert {r.dataset for r in results} == {"a", "b"}


def test_write_datasets_rows_match_df_height() -> None:
    tc = _make_cloud()
    df = pl.DataFrame({"id": [1, 2, 3]})
    results = tc.write_datasets({"t": df}, schema_metadata={})
    assert results[0].rows == 3


def test_write_datasets_location_uses_location_method() -> None:
    tc = _make_cloud()
    results = tc.write_datasets({"tbl": pl.DataFrame({"id": [1]})}, schema_metadata={})
    assert results[0].location == "test://tbl.parquet"


def test_write_datasets_upload_error_raises_load_error() -> None:
    class _FailWrite(_TestCloud):
        def _write_bytes(self, key: str, data: bytes) -> None:
            raise RuntimeError("quota exceeded")

    tc = _FailWrite()
    with pytest.raises(LoadError, match="Cannot write dataset"):
        tc.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata={})


def test_write_schema_upload_error_raises_load_error() -> None:
    written: list[str] = []

    class _FailSchema(_TestCloud):
        def _write_bytes(self, key: str, data: bytes) -> None:
            if key.endswith("schema.json"):
                raise RuntimeError("write failed")
            written.append(key)
            super()._write_bytes(key, data)

    tc = _FailSchema()
    with pytest.raises(LoadError, match="schema.json"):
        tc.write_datasets(
            {"t": pl.DataFrame({"id": [1]})},
            schema_metadata={"t": {}},
        )
    # Parquet was uploaded before the schema error
    assert any("parquet" in k for k in written)
