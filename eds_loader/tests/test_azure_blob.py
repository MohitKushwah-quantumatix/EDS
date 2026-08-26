"""Tests for AzureBlobConnector.

All tests use mocked azure-storage-blob — no real Azure account required.

Mocking strategy:
- ``_inject_client()`` replaces ``conn._cloud_client`` with a mock
  BlobServiceClient, bypassing ``_connect()``.
- Connection tests patch ``eds_loader.connectors.azure_blob._BlobServiceClient``.

``pytest.importorskip("azure.storage.blob")`` skips the file if the driver
is not installed.
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

pytest.importorskip("azure.storage.blob")

from eds_loader.connectors.azure_blob import AzureBlobConnector
from eds_loader.connectors.registry import CONNECTORS
from eds_loader.connectors._cloud_base import CloudBaseConnector
from eds_loader.exceptions import LoadError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(**kwargs: Any) -> AzureBlobConnector:
    defaults: dict[str, Any] = dict(
        account_name="testaccount",
        container="test-container",
        account_key="dGVzdGtleQ==",   # fake base64 key
    )
    defaults.update(kwargs)
    return AzureBlobConnector(**defaults)


def _inject_client(conn: AzureBlobConnector) -> MagicMock:
    mock_client = MagicMock()
    conn._cloud_client = mock_client
    return mock_client


def _parquet_bytes(df: pl.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.write_parquet(buf)
    return buf.getvalue()


def _make_blob(name: str) -> MagicMock:
    b = MagicMock()
    b.name = name
    return b


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_azure_blob_is_registered() -> None:
    import eds_loader  # noqa: F401
    assert "azure_blob" in CONNECTORS


def test_azure_blob_is_readable_and_writable() -> None:
    spec = CONNECTORS["azure_blob"]
    assert spec.can_read is True
    assert spec.can_write is True


def test_azure_blob_requires_driver() -> None:
    spec = CONNECTORS["azure_blob"]
    assert "azure.storage.blob" in spec.required_packages
    assert spec.install_extra == "azure"


def test_azure_blob_connector_class_is_set() -> None:
    assert CONNECTORS["azure_blob"].connector_class is AzureBlobConnector


def test_azure_blob_inherits_cloud_base() -> None:
    assert issubclass(AzureBlobConnector, CloudBaseConnector)


# ---------------------------------------------------------------------------
# Constructor / attributes
# ---------------------------------------------------------------------------

def test_constructor_stores_account_and_container() -> None:
    conn = _make_conn(account_name="acc", container="ctr")
    assert conn._account_name == "acc"
    assert conn._container == "ctr"


def test_constructor_prefix_normalised() -> None:
    conn = _make_conn(prefix="blobs/v1")
    assert conn._prefix == "blobs/v1/"


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------

def test_resolve_account_key_inline() -> None:
    conn = _make_conn(account_key="mykey")
    assert conn._resolve_account_key() == "mykey"


def test_resolve_account_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_KEY", "env_key")
    conn = _make_conn(account_key=None, account_key_env="AZURE_KEY")
    assert conn._resolve_account_key() == "env_key"


def test_resolve_account_key_missing_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_AZURE_KEY", raising=False)
    conn = _make_conn(account_key=None, account_key_env="MISSING_AZURE_KEY")
    with pytest.raises(LoadError, match="MISSING_AZURE_KEY"):
        conn._resolve_account_key()


def test_resolve_connection_string_inline() -> None:
    conn = _make_conn(connection_string="DefaultEndpointsProtocol=https;...")
    assert conn._resolve_connection_string() == "DefaultEndpointsProtocol=https;..."


def test_resolve_connection_string_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_CONN", "conn_str")
    conn = _make_conn(connection_string_env="AZURE_CONN")
    assert conn._resolve_connection_string() == "conn_str"


def test_resolve_connection_string_missing_env_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_AZURE_CONN", raising=False)
    conn = _make_conn(connection_string_env="MISSING_AZURE_CONN")
    with pytest.raises(LoadError, match="MISSING_AZURE_CONN"):
        conn._resolve_connection_string()


# ---------------------------------------------------------------------------
# _connect
# ---------------------------------------------------------------------------

def test_connect_uses_connection_string_when_set() -> None:
    conn = _make_conn(connection_string="conn_str_value")
    with patch(
        "eds_loader.connectors.azure_blob._BlobServiceClient"
    ) as mock_cls:
        mock_cls.from_connection_string.return_value = MagicMock()
        conn._cloud_client = None
        conn._get_client()
        mock_cls.from_connection_string.assert_called_once_with("conn_str_value")


def test_connect_uses_account_key_when_no_connection_string() -> None:
    conn = _make_conn(account_name="myacc", account_key="mykey",
                      connection_string=None)
    with patch(
        "eds_loader.connectors.azure_blob._BlobServiceClient"
    ) as mock_cls:
        mock_cls.return_value = MagicMock()
        conn._cloud_client = None
        conn._get_client()
        mock_cls.assert_called_once_with(
            account_url="https://myacc.blob.core.windows.net",
            credential="mykey",
        )


def test_connect_error_raises_load_error() -> None:
    conn = _make_conn(connection_string=None, account_key=None,
                      account_key_env=None)
    with patch(
        "eds_loader.connectors.azure_blob._BlobServiceClient"
    ) as mock_cls:
        mock_cls.side_effect = Exception("auth failed")
        conn._cloud_client = None
        with pytest.raises(LoadError, match="Cannot create Azure Blob client"):
            conn._get_client()


# ---------------------------------------------------------------------------
# _list_parquet_keys
# ---------------------------------------------------------------------------

def test_list_parquet_keys_returns_only_parquet_blobs() -> None:
    conn = _make_conn(container="ctr")
    mock_client = _inject_client(conn)
    cc = MagicMock()
    cc.list_blobs.return_value = [
        _make_blob("data/customers.parquet"),
        _make_blob("data/schema.json"),   # excluded
        _make_blob("data/orders.parquet"),
    ]
    mock_client.get_container_client.return_value = cc

    keys = conn._list_keys_by_extension(".parquet")
    assert keys == ["data/customers.parquet", "data/orders.parquet"]
    cc.list_blobs.assert_called_once_with(name_starts_with=conn._prefix)


def test_list_parquet_keys_uses_correct_container() -> None:
    conn = _make_conn(container="eds-data")
    mock_client = _inject_client(conn)
    cc = MagicMock()
    cc.list_blobs.return_value = []
    mock_client.get_container_client.return_value = cc
    conn._list_keys_by_extension(".parquet")
    mock_client.get_container_client.assert_called_once_with("eds-data")


def test_list_parquet_keys_error_raises_load_error() -> None:
    conn = _make_conn(account_name="acc", container="ctr")
    mock_client = _inject_client(conn)
    mock_client.get_container_client.side_effect = Exception("network error")
    with pytest.raises(LoadError, match="Cannot list blobs in azure://acc/ctr"):
        conn._list_keys_by_extension(".parquet")


# ---------------------------------------------------------------------------
# _read_bytes
# ---------------------------------------------------------------------------

def test_read_bytes_downloads_blob() -> None:
    conn = _make_conn(account_name="acc", container="ctr")
    mock_client = _inject_client(conn)
    mock_blob_client = MagicMock()
    mock_blob_client.download_blob.return_value.readall.return_value = b"parquet_data"
    mock_client.get_blob_client.return_value = mock_blob_client

    data = conn._read_bytes("prefix/customers.parquet")
    assert data == b"parquet_data"
    mock_client.get_blob_client.assert_called_once_with("ctr", "prefix/customers.parquet")


def test_read_bytes_error_raises_load_error() -> None:
    conn = _make_conn(account_name="acc", container="ctr")
    mock_client = _inject_client(conn)
    mock_client.get_blob_client.side_effect = Exception("ResourceNotFound")
    with pytest.raises(LoadError, match="Cannot download azure://acc/ctr"):
        conn._read_bytes("missing.parquet")


# ---------------------------------------------------------------------------
# _write_bytes
# ---------------------------------------------------------------------------

def test_write_bytes_uploads_blob_with_overwrite() -> None:
    conn = _make_conn(container="ctr")
    mock_client = _inject_client(conn)
    mock_blob_client = MagicMock()
    mock_client.get_blob_client.return_value = mock_blob_client

    conn._write_bytes("prefix/customers.parquet", b"data")
    mock_blob_client.upload_blob.assert_called_once_with(b"data", overwrite=True)


def test_write_bytes_uses_correct_blob_key() -> None:
    conn = _make_conn(container="ctr")
    mock_client = _inject_client(conn)
    blob_cl = MagicMock()
    mock_client.get_blob_client.return_value = blob_cl

    conn._write_bytes("my/key.parquet", b"x")
    mock_client.get_blob_client.assert_called_once_with("ctr", "my/key.parquet")


def test_write_bytes_error_raises_load_error() -> None:
    conn = _make_conn(account_name="acc", container="ctr")
    mock_client = _inject_client(conn)
    mock_client.get_blob_client.side_effect = Exception("quota exceeded")
    with pytest.raises(LoadError, match="Cannot upload to azure://acc/ctr"):
        conn._write_bytes("key", b"data")


# ---------------------------------------------------------------------------
# _location
# ---------------------------------------------------------------------------

def test_location_no_prefix() -> None:
    conn = _make_conn(account_name="acc", container="ctr")
    assert conn._location("customers") == "azure://acc/ctr/customers.parquet"


def test_location_with_prefix() -> None:
    conn = _make_conn(account_name="acc", container="ctr", prefix="data/")
    assert conn._location("orders") == "azure://acc/ctr/data/orders.parquet"


# ---------------------------------------------------------------------------
# write_datasets result
# ---------------------------------------------------------------------------

def test_write_datasets_result_location_is_azure_url() -> None:
    conn = _make_conn(account_name="myacc", container="myc", prefix="ds/")
    _inject_client(conn)
    results = conn.write_datasets(
        {"tbl": pl.DataFrame({"id": [1]})}, schema_metadata={}
    )
    assert results[0].location == "azure://myacc/myc/ds/tbl.parquet"


def test_write_datasets_result_rows_match_df_height() -> None:
    conn = _make_conn()
    _inject_client(conn)
    df = pl.DataFrame({"id": [10, 20, 30]})
    results = conn.write_datasets({"t": df}, schema_metadata={})
    assert results[0].rows == 3


def test_write_datasets_uploads_schema_json() -> None:
    conn = _make_conn(container="ctr")
    mock_client = _inject_client(conn)
    blob_cl = MagicMock()
    mock_client.get_blob_client.return_value = blob_cl

    schema = {"t": {"primary_key": "id"}}
    conn.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata=schema)

    upload_keys = [
        mock_client.get_blob_client.call_args_list[i].args[1]
        for i in range(mock_client.get_blob_client.call_count)
    ]
    assert any("schema.json" in k for k in upload_keys)


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

def test_integration_azure_blob_to_local_fs(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Full load() pipeline: azure_blob source → local_fs target (mocked)."""
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    datasets = {
        "customers": pl.DataFrame({"id": [1, 2]}),
        "orders": pl.DataFrame({"id": [10]}),
    }
    schema = {n: {"primary_key": "id", "unique_columns": [], "foreign_keys": []}
              for n in datasets}

    az_conn = _make_conn()
    mock_client = _inject_client(az_conn)

    schema_bytes = json.dumps(schema).encode()
    parquet_map = {name: _parquet_bytes(df) for name, df in datasets.items()}

    def _get_blob_cl(container: str, key: str) -> MagicMock:
        bc = MagicMock()
        if key.endswith("schema.json"):
            bc.download_blob.return_value.readall.return_value = schema_bytes
        else:
            for name, data in parquet_map.items():
                if key.endswith(f"{name}.parquet"):
                    bc.download_blob.return_value.readall.return_value = data
                    break
        return bc

    mock_client.get_blob_client.side_effect = _get_blob_cl

    cc = MagicMock()
    cc.list_blobs.return_value = [
        _make_blob(f"{n}.parquet") for n in datasets
    ]
    mock_client.get_container_client.return_value = cc

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    original_gc = __import__(
        "eds_loader.connectors.registry", fromlist=["get_connector"]
    ).get_connector

    def _patched(kind: str, config: dict) -> Any:
        if kind == "azure_blob":
            return az_conn
        return original_gc(kind, config)

    with patch("eds_loader.loader.get_connector", side_effect=_patched):
        config = LoaderConfig(
            source={"kind": "azure_blob", "account_name": "acc", "container": "ctr"},
            target={"kind": "local_fs", "path": str(target_dir)},
        )
        result = load(config)

    assert result.total_rows == sum(df.height for df in datasets.values())
    assert set(result.tables_written) == set(datasets)
