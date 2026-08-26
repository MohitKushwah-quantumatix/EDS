"""Tests for GCSConnector.

All tests use mocked google-cloud-storage — no real GCS account required.

Mocking strategy:
- ``_inject_client()`` replaces ``conn._cloud_client`` with a mock
  google.cloud.storage.Client, bypassing ``_connect()``.
- Connection tests patch ``eds_loader.connectors.gcs._gcs``.

``pytest.importorskip("google.cloud.storage")`` skips the file if the
driver is not installed.
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

pytest.importorskip("google.cloud.storage")

from eds_loader.connectors.gcs import GCSConnector
from eds_loader.connectors.registry import CONNECTORS
from eds_loader.connectors._cloud_base import CloudBaseConnector
from eds_loader.exceptions import LoadError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(**kwargs: Any) -> GCSConnector:
    defaults: dict[str, Any] = dict(bucket="test-bucket")
    defaults.update(kwargs)
    return GCSConnector(**defaults)


def _inject_client(conn: GCSConnector) -> MagicMock:
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

def test_gcs_is_registered() -> None:
    import eds_loader  # noqa: F401
    assert "gcs" in CONNECTORS


def test_gcs_is_readable_and_writable() -> None:
    spec = CONNECTORS["gcs"]
    assert spec.can_read is True
    assert spec.can_write is True


def test_gcs_requires_driver() -> None:
    spec = CONNECTORS["gcs"]
    assert "google.cloud.storage" in spec.required_packages
    assert spec.install_extra == "gcs"


def test_gcs_connector_class_is_set() -> None:
    assert CONNECTORS["gcs"].connector_class is GCSConnector


def test_gcs_inherits_cloud_base() -> None:
    assert issubclass(GCSConnector, CloudBaseConnector)


# ---------------------------------------------------------------------------
# Constructor / attributes
# ---------------------------------------------------------------------------

def test_constructor_stores_bucket() -> None:
    conn = _make_conn(bucket="my-bucket")
    assert conn._bucket_name == "my-bucket"


def test_constructor_prefix_normalised() -> None:
    conn = _make_conn(prefix="data")
    assert conn._prefix == "data/"


def test_constructor_credentials_none_by_default() -> None:
    conn = _make_conn()
    assert conn._credentials_file is None
    assert conn._credentials_env is None


# ---------------------------------------------------------------------------
# _resolve_credentials_file
# ---------------------------------------------------------------------------

def test_resolve_credentials_file_explicit() -> None:
    conn = _make_conn(credentials_file="/path/to/sa.json")
    assert conn._resolve_credentials_file() == "/path/to/sa.json"


def test_resolve_credentials_file_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_SA_JSON", "/creds/sa.json")
    conn = _make_conn(credentials_env="GOOGLE_SA_JSON")
    assert conn._resolve_credentials_file() == "/creds/sa.json"


def test_resolve_credentials_file_missing_env_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_GOOGLE_CRED", raising=False)
    conn = _make_conn(credentials_env="MISSING_GOOGLE_CRED")
    with pytest.raises(LoadError, match="MISSING_GOOGLE_CRED"):
        conn._resolve_credentials_file()


def test_resolve_credentials_file_none_when_neither_set() -> None:
    conn = _make_conn(credentials_file=None, credentials_env=None)
    assert conn._resolve_credentials_file() is None


# ---------------------------------------------------------------------------
# _connect
# ---------------------------------------------------------------------------

def test_connect_uses_service_account_json_when_credentials_file_set() -> None:
    conn = _make_conn(credentials_file="/sa.json")
    with patch("eds_loader.connectors.gcs._gcs") as mock_gcs:
        mock_gcs.Client.from_service_account_json.return_value = MagicMock()
        conn._cloud_client = None
        conn._get_client()
        mock_gcs.Client.from_service_account_json.assert_called_once_with(
            "/sa.json", project=None
        )


def test_connect_uses_adc_when_no_credentials() -> None:
    conn = _make_conn()
    with patch("eds_loader.connectors.gcs._gcs") as mock_gcs:
        mock_gcs.Client.return_value = MagicMock()
        conn._cloud_client = None
        conn._get_client()
        mock_gcs.Client.assert_called_once_with(project=None)


def test_connect_with_project() -> None:
    conn = _make_conn(project="my-project")
    with patch("eds_loader.connectors.gcs._gcs") as mock_gcs:
        mock_gcs.Client.return_value = MagicMock()
        conn._cloud_client = None
        conn._get_client()
        _, kwargs = mock_gcs.Client.call_args
        assert kwargs["project"] == "my-project"


def test_connect_error_raises_load_error() -> None:
    conn = _make_conn()
    with patch("eds_loader.connectors.gcs._gcs") as mock_gcs:
        mock_gcs.Client.side_effect = Exception("auth failed")
        conn._cloud_client = None
        with pytest.raises(LoadError, match="Cannot create GCS client"):
            conn._get_client()


def test_connect_caches_client() -> None:
    conn = _make_conn()
    with patch("eds_loader.connectors.gcs._gcs") as mock_gcs:
        mock_gcs.Client.return_value = MagicMock()
        conn._cloud_client = None
        c1 = conn._get_client()
        c2 = conn._get_client()
        assert c1 is c2
        mock_gcs.Client.assert_called_once()


# ---------------------------------------------------------------------------
# _list_parquet_keys
# ---------------------------------------------------------------------------

def test_list_parquet_keys_returns_parquet_blobs_only() -> None:
    conn = _make_conn(bucket="bkt")
    mock_client = _inject_client(conn)
    bucket_obj = MagicMock()
    mock_client.bucket.return_value = bucket_obj
    mock_client.list_blobs.return_value = [
        _make_blob("data/customers.parquet"),
        _make_blob("data/schema.json"),   # excluded
        _make_blob("data/orders.parquet"),
    ]
    keys = conn._list_keys_by_extension(".parquet")
    assert keys == ["data/customers.parquet", "data/orders.parquet"]
    mock_client.list_blobs.assert_called_once_with(
        bucket_obj, prefix=conn._prefix
    )


def test_list_parquet_keys_uses_correct_bucket() -> None:
    conn = _make_conn(bucket="my-bucket")
    mock_client = _inject_client(conn)
    mock_client.list_blobs.return_value = []
    conn._list_keys_by_extension(".parquet")
    mock_client.bucket.assert_called_once_with("my-bucket")


def test_list_parquet_keys_error_raises_load_error() -> None:
    conn = _make_conn(bucket="bkt")
    mock_client = _inject_client(conn)
    mock_client.bucket.side_effect = Exception("permission denied")
    with pytest.raises(LoadError, match="Cannot list gs://bkt"):
        conn._list_keys_by_extension(".parquet")


# ---------------------------------------------------------------------------
# _read_bytes
# ---------------------------------------------------------------------------

def test_read_bytes_downloads_blob() -> None:
    conn = _make_conn(bucket="bkt")
    mock_client = _inject_client(conn)
    bucket_obj = MagicMock()
    blob_obj = MagicMock()
    blob_obj.download_as_bytes.return_value = b"parquet_data"
    bucket_obj.blob.return_value = blob_obj
    mock_client.bucket.return_value = bucket_obj

    data = conn._read_bytes("data/customers.parquet")
    assert data == b"parquet_data"
    mock_client.bucket.assert_called_once_with("bkt")
    bucket_obj.blob.assert_called_once_with("data/customers.parquet")


def test_read_bytes_error_raises_load_error() -> None:
    conn = _make_conn(bucket="bkt")
    mock_client = _inject_client(conn)
    mock_client.bucket.side_effect = Exception("not found")
    with pytest.raises(LoadError, match="Cannot download gs://bkt"):
        conn._read_bytes("missing.parquet")


# ---------------------------------------------------------------------------
# _write_bytes
# ---------------------------------------------------------------------------

def test_write_bytes_uploads_blob() -> None:
    conn = _make_conn(bucket="bkt")
    mock_client = _inject_client(conn)
    bucket_obj = MagicMock()
    blob_obj = MagicMock()
    bucket_obj.blob.return_value = blob_obj
    mock_client.bucket.return_value = bucket_obj

    conn._write_bytes("out/customers.parquet", b"data")
    blob_obj.upload_from_string.assert_called_once_with(b"data")
    bucket_obj.blob.assert_called_once_with("out/customers.parquet")


def test_write_bytes_error_raises_load_error() -> None:
    conn = _make_conn(bucket="bkt")
    mock_client = _inject_client(conn)
    mock_client.bucket.side_effect = Exception("quota exceeded")
    with pytest.raises(LoadError, match="Cannot upload to gs://bkt"):
        conn._write_bytes("key", b"data")


# ---------------------------------------------------------------------------
# _location
# ---------------------------------------------------------------------------

def test_location_no_prefix() -> None:
    conn = _make_conn(bucket="bkt")
    assert conn._location("customers") == "gs://bkt/customers.parquet"


def test_location_with_prefix() -> None:
    conn = _make_conn(bucket="bkt", prefix="data/")
    assert conn._location("orders") == "gs://bkt/data/orders.parquet"


# ---------------------------------------------------------------------------
# write_datasets result
# ---------------------------------------------------------------------------

def test_write_datasets_result_location_is_gs_url() -> None:
    conn = _make_conn(bucket="my-bkt", prefix="ds/")
    _inject_client(conn)
    results = conn.write_datasets(
        {"tbl": pl.DataFrame({"id": [1]})}, schema_metadata={}
    )
    assert results[0].location == "gs://my-bkt/ds/tbl.parquet"


def test_write_datasets_result_rows_match_df_height() -> None:
    conn = _make_conn()
    _inject_client(conn)
    df = pl.DataFrame({"id": [1, 2, 3]})
    results = conn.write_datasets({"t": df}, schema_metadata={})
    assert results[0].rows == 3


def test_write_datasets_uploads_schema_json() -> None:
    conn = _make_conn(bucket="bkt")
    mock_client = _inject_client(conn)
    bucket_obj = MagicMock()
    blob_calls: list[str] = []

    def _blob(key: str) -> MagicMock:
        blob_calls.append(key)
        return MagicMock()

    bucket_obj.blob.side_effect = _blob
    mock_client.bucket.return_value = bucket_obj

    schema = {"t": {"primary_key": "id"}}
    conn.write_datasets({"t": pl.DataFrame({"id": [1]})}, schema_metadata=schema)
    assert any("schema.json" in k for k in blob_calls)


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

def test_integration_gcs_source_via_load(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Full load() pipeline: gcs source → local_fs target (GCS mocked)."""
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    datasets = {
        "customers": pl.DataFrame({"id": [1, 2, 3]}),
        "orders": pl.DataFrame({"id": [10, 11]}),
    }
    schema = {n: {"primary_key": "id", "unique_columns": [], "foreign_keys": []}
              for n in datasets}

    gcs_conn = _make_conn(bucket="bkt")
    mock_client = _inject_client(gcs_conn)

    schema_bytes = json.dumps(schema).encode()
    parquet_map = {name: _parquet_bytes(df) for name, df in datasets.items()}

    bucket_obj = MagicMock()

    def _blob(key: str) -> MagicMock:
        b = MagicMock()
        if key.endswith("schema.json"):
            b.download_as_bytes.return_value = schema_bytes
        else:
            for name, data in parquet_map.items():
                if key.endswith(f"{name}.parquet"):
                    b.download_as_bytes.return_value = data
                    break
        return b

    bucket_obj.blob.side_effect = _blob
    mock_client.bucket.return_value = bucket_obj
    mock_client.list_blobs.return_value = [
        _make_blob(f"{n}.parquet") for n in datasets
    ]

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    original_gc = __import__(
        "eds_loader.connectors.registry", fromlist=["get_connector"]
    ).get_connector

    def _patched(kind: str, config: dict) -> Any:
        if kind == "gcs":
            return gcs_conn
        return original_gc(kind, config)

    with patch("eds_loader.loader.get_connector", side_effect=_patched):
        config = LoaderConfig(
            source={"kind": "gcs", "bucket": "bkt"},
            target={"kind": "local_fs", "path": str(target_dir)},
        )
        result = load(config)

    assert result.total_rows == sum(df.height for df in datasets.values())
    assert set(result.tables_written) == set(datasets)
