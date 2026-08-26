"""Tests for S3Connector.

All tests use mocked boto3 — no real AWS account required.

Mocking strategy:
- ``_inject_client()`` replaces ``conn._cloud_client`` with a mock boto3 S3
  client, bypassing ``_connect()``.
- Connection tests patch ``eds_loader.connectors.s3._boto3``.

``pytest.importorskip("boto3")`` skips the file if boto3 is not installed.
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock, call, patch

import polars as pl
import pytest

boto3 = pytest.importorskip("boto3")

from eds_loader.connectors.s3 import S3Connector
from eds_loader.connectors.registry import CONNECTORS
from eds_loader.connectors._cloud_base import CloudBaseConnector
from eds_loader.exceptions import LoadError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(**kwargs: Any) -> S3Connector:
    defaults: dict[str, Any] = dict(
        bucket="test-bucket",
        aws_access_key_id="AKIATEST",
        aws_secret_access_key="secretkey",
    )
    defaults.update(kwargs)
    return S3Connector(**defaults)


def _inject_client(conn: S3Connector) -> MagicMock:
    mock_s3 = MagicMock()
    conn._cloud_client = mock_s3
    return mock_s3


def _parquet_bytes(df: pl.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.write_parquet(buf)
    return buf.getvalue()


def _mock_paginator(keys: list[str]) -> MagicMock:
    """Build a mock paginator that returns *keys* in one page."""
    page = {"Contents": [{"Key": k} for k in keys]}
    pag = MagicMock()
    pag.paginate.return_value = [page]
    return pag


def _mock_get_object(data: bytes) -> dict:
    body = MagicMock()
    body.read.return_value = data
    return {"Body": body}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_s3_is_registered() -> None:
    import eds_loader  # noqa: F401
    assert "s3" in CONNECTORS


def test_s3_is_readable_and_writable() -> None:
    spec = CONNECTORS["s3"]
    assert spec.can_read is True
    assert spec.can_write is True


def test_s3_requires_boto3() -> None:
    spec = CONNECTORS["s3"]
    assert "boto3" in spec.required_packages
    assert spec.install_extra == "s3"


def test_s3_connector_class_is_set() -> None:
    assert CONNECTORS["s3"].connector_class is S3Connector


def test_s3_inherits_cloud_base() -> None:
    assert issubclass(S3Connector, CloudBaseConnector)


# ---------------------------------------------------------------------------
# Constructor / attributes
# ---------------------------------------------------------------------------

def test_constructor_stores_bucket() -> None:
    conn = _make_conn(bucket="my-bucket")
    assert conn._bucket == "my-bucket"


def test_constructor_default_region() -> None:
    conn = _make_conn()
    assert conn._region == "us-east-1"


def test_constructor_custom_region() -> None:
    conn = _make_conn(region="eu-west-1")
    assert conn._region == "eu-west-1"


def test_constructor_endpoint_url_none_by_default() -> None:
    conn = _make_conn()
    assert conn._endpoint_url is None


def test_constructor_prefix_normalised() -> None:
    conn = _make_conn(prefix="data")
    assert conn._prefix == "data/"


# ---------------------------------------------------------------------------
# _resolve_secret_key
# ---------------------------------------------------------------------------

def test_resolve_secret_key_inline() -> None:
    conn = _make_conn(aws_secret_access_key="inlinesecret")
    assert conn._resolve_secret_key() == "inlinesecret"


def test_resolve_secret_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_SECRET", "from_env")
    conn = _make_conn(aws_secret_access_key=None,
                      aws_secret_access_key_env="AWS_SECRET")
    assert conn._resolve_secret_key() == "from_env"


def test_resolve_secret_key_missing_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_AWS_SECRET", raising=False)
    conn = _make_conn(aws_secret_access_key=None,
                      aws_secret_access_key_env="MISSING_AWS_SECRET")
    with pytest.raises(LoadError, match="MISSING_AWS_SECRET"):
        conn._resolve_secret_key()


# ---------------------------------------------------------------------------
# _connect / _get_client
# ---------------------------------------------------------------------------

def test_connect_calls_boto3_client_with_correct_params() -> None:
    conn = _make_conn(bucket="b", aws_access_key_id="KEY",
                      aws_secret_access_key="SECRET", region="ap-south-1")
    with patch("eds_loader.connectors.s3._boto3") as mock_b3:
        mock_b3.client.return_value = MagicMock()
        conn._cloud_client = None
        conn._get_client()
        mock_b3.client.assert_called_once_with(
            "s3",
            region_name="ap-south-1",
            aws_access_key_id="KEY",
            aws_secret_access_key="SECRET",
        )


def test_connect_no_credentials_omits_key_params() -> None:
    conn = S3Connector(bucket="b", aws_access_key_id=None)
    with patch("eds_loader.connectors.s3._boto3") as mock_b3:
        mock_b3.client.return_value = MagicMock()
        conn._cloud_client = None
        conn._get_client()
        _, kwargs = mock_b3.client.call_args
        assert "aws_access_key_id" not in kwargs


def test_connect_with_endpoint_url() -> None:
    conn = _make_conn(endpoint_url="http://localhost:9000")
    with patch("eds_loader.connectors.s3._boto3") as mock_b3:
        mock_b3.client.return_value = MagicMock()
        conn._cloud_client = None
        conn._get_client()
        _, kwargs = mock_b3.client.call_args
        assert kwargs["endpoint_url"] == "http://localhost:9000"


def test_connect_error_raises_load_error() -> None:
    conn = _make_conn()
    with patch("eds_loader.connectors.s3._boto3") as mock_b3:
        mock_b3.client.side_effect = Exception("credentials invalid")
        conn._cloud_client = None
        with pytest.raises(LoadError, match="Cannot create S3 client"):
            conn._get_client()


def test_get_client_caches_connection() -> None:
    conn = _make_conn()
    with patch("eds_loader.connectors.s3._boto3") as mock_b3:
        mock_b3.client.return_value = MagicMock()
        conn._cloud_client = None
        c1 = conn._get_client()
        c2 = conn._get_client()
        assert c1 is c2
        mock_b3.client.assert_called_once()


# ---------------------------------------------------------------------------
# _list_parquet_keys
# ---------------------------------------------------------------------------

def test_list_parquet_keys_returns_parquet_files() -> None:
    conn = _make_conn(bucket="bkt")
    mock_s3 = _inject_client(conn)
    mock_s3.get_paginator.return_value = _mock_paginator([
        "prefix/customers.parquet",
        "prefix/orders.parquet",
        "prefix/schema.json",   # ← excluded
    ])
    keys = conn._list_keys_by_extension(".parquet")
    assert keys == ["prefix/customers.parquet", "prefix/orders.parquet"]


def test_list_parquet_keys_paginates_all_pages() -> None:
    conn = _make_conn()
    mock_s3 = _inject_client(conn)
    pag = MagicMock()
    pag.paginate.return_value = [
        {"Contents": [{"Key": "a.parquet"}]},
        {"Contents": [{"Key": "b.parquet"}]},
    ]
    mock_s3.get_paginator.return_value = pag
    assert conn._list_keys_by_extension(".parquet") == ["a.parquet", "b.parquet"]


def test_list_parquet_keys_empty_page_returns_empty() -> None:
    conn = _make_conn()
    mock_s3 = _inject_client(conn)
    pag = MagicMock()
    pag.paginate.return_value = [{}]   # no "Contents" key
    mock_s3.get_paginator.return_value = pag
    assert conn._list_keys_by_extension(".parquet") == []


def test_list_parquet_keys_error_raises_load_error() -> None:
    conn = _make_conn(bucket="bkt")
    mock_s3 = _inject_client(conn)
    mock_s3.get_paginator.side_effect = Exception("access denied")
    with pytest.raises(LoadError, match="Cannot list s3://bkt"):
        conn._list_keys_by_extension(".parquet")


# ---------------------------------------------------------------------------
# _read_bytes
# ---------------------------------------------------------------------------

def test_read_bytes_downloads_object() -> None:
    conn = _make_conn(bucket="bkt")
    mock_s3 = _inject_client(conn)
    mock_s3.get_object.return_value = _mock_get_object(b"hello")
    data = conn._read_bytes("prefix/file.parquet")
    assert data == b"hello"
    mock_s3.get_object.assert_called_once_with(
        Bucket="bkt", Key="prefix/file.parquet"
    )


def test_read_bytes_error_raises_load_error() -> None:
    conn = _make_conn(bucket="bkt")
    mock_s3 = _inject_client(conn)
    mock_s3.get_object.side_effect = Exception("NoSuchKey")
    with pytest.raises(LoadError, match="Cannot download s3://bkt"):
        conn._read_bytes("missing.parquet")


# ---------------------------------------------------------------------------
# _write_bytes
# ---------------------------------------------------------------------------

def test_write_bytes_uploads_object() -> None:
    conn = _make_conn(bucket="bkt")
    mock_s3 = _inject_client(conn)
    conn._write_bytes("out/customers.parquet", b"data")
    mock_s3.put_object.assert_called_once_with(
        Bucket="bkt", Key="out/customers.parquet", Body=b"data"
    )


def test_write_bytes_error_raises_load_error() -> None:
    conn = _make_conn(bucket="bkt")
    mock_s3 = _inject_client(conn)
    mock_s3.put_object.side_effect = Exception("access denied")
    with pytest.raises(LoadError, match="Cannot upload to s3://bkt"):
        conn._write_bytes("key", b"data")


# ---------------------------------------------------------------------------
# _location
# ---------------------------------------------------------------------------

def test_location_no_prefix() -> None:
    conn = _make_conn(bucket="mybucket")
    assert conn._location("customers") == "s3://mybucket/customers.parquet"


def test_location_with_prefix() -> None:
    conn = _make_conn(bucket="mybucket", prefix="data/")
    assert conn._location("orders") == "s3://mybucket/data/orders.parquet"


# ---------------------------------------------------------------------------
# read_schema_metadata (end-to-end through base)
# ---------------------------------------------------------------------------

def test_read_schema_metadata_downloads_and_parses() -> None:
    conn = _make_conn(bucket="bkt")
    mock_s3 = _inject_client(conn)
    schema = {"t": {"primary_key": "id"}}
    mock_s3.get_object.return_value = _mock_get_object(
        json.dumps(schema).encode()
    )
    result = conn.read_schema_metadata()
    assert result == schema
    mock_s3.get_object.assert_called_once_with(
        Bucket="bkt", Key="schema.json"
    )


def test_read_schema_metadata_with_prefix() -> None:
    conn = _make_conn(bucket="bkt", prefix="out/")
    mock_s3 = _inject_client(conn)
    mock_s3.get_object.return_value = _mock_get_object(b'{"k": {}}')
    conn.read_schema_metadata()
    mock_s3.get_object.assert_called_once_with(
        Bucket="bkt", Key="out/schema.json"
    )


# ---------------------------------------------------------------------------
# write_datasets (end-to-end through base)
# ---------------------------------------------------------------------------

def test_write_datasets_uploads_parquet_and_schema() -> None:
    conn = _make_conn(bucket="bkt")
    mock_s3 = _inject_client(conn)
    df = pl.DataFrame({"id": [1, 2]})
    schema = {"customers": {"primary_key": "id"}}
    results = conn.write_datasets({"customers": df}, schema_metadata=schema)

    # Two put_object calls: parquet + schema.json
    assert mock_s3.put_object.call_count == 2
    uploaded_keys = [c.kwargs.get("Key") or c.args[1]
                     for c in mock_s3.put_object.call_args_list]
    assert any("customers.parquet" in k for k in uploaded_keys)
    assert any("schema.json" in k for k in uploaded_keys)


def test_write_datasets_result_location_is_s3_url() -> None:
    conn = _make_conn(bucket="bkt", prefix="ds/")
    _inject_client(conn)
    results = conn.write_datasets(
        {"tbl": pl.DataFrame({"id": [1]})}, schema_metadata={}
    )
    assert results[0].location == "s3://bkt/ds/tbl.parquet"


def test_write_datasets_result_rows_match_df_height() -> None:
    conn = _make_conn()
    _inject_client(conn)
    df = pl.DataFrame({"id": [1, 2, 3]})
    results = conn.write_datasets({"t": df}, schema_metadata={})
    assert results[0].rows == 3


# ---------------------------------------------------------------------------
# Integration — through load()
# ---------------------------------------------------------------------------

def test_integration_s3_source_via_load(tmp_path: pytest.TempPathFactory) -> None:
    """Full load() pipeline: s3 source → local_fs target (S3 mocked)."""
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    datasets = {
        "customers": pl.DataFrame({"id": [1, 2], "name": ["A", "B"]}),
        "orders": pl.DataFrame({"id": [10], "cust_id": [1]}),
    }
    schema = {"customers": {"primary_key": "id", "unique_columns": [], "foreign_keys": []},
              "orders": {"primary_key": "id", "unique_columns": [], "foreign_keys": []}}

    s3_conn = _make_conn(bucket="bkt")
    mock_s3 = _inject_client(s3_conn)

    schema_bytes = json.dumps(schema).encode()
    parquet_map = {name: _parquet_bytes(df) for name, df in datasets.items()}

    def _get_object(Bucket: str, Key: str) -> dict:
        if Key.endswith("schema.json"):
            return _mock_get_object(schema_bytes)
        for name, data in parquet_map.items():
            if Key.endswith(f"{name}.parquet"):
                return _mock_get_object(data)
        raise KeyError(Key)

    mock_s3.get_object.side_effect = _get_object
    pag = MagicMock()
    pag.paginate.return_value = [
        {"Contents": [{"Key": f"{n}.parquet"} for n in datasets]}
    ]
    mock_s3.get_paginator.return_value = pag

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    original_gc = __import__(
        "eds_loader.connectors.registry", fromlist=["get_connector"]
    ).get_connector

    def _patched(kind: str, config: dict) -> Any:
        if kind == "s3":
            return s3_conn
        return original_gc(kind, config)

    with patch("eds_loader.loader.get_connector", side_effect=_patched):
        config = LoaderConfig(
            source={"kind": "s3", "bucket": "bkt"},
            target={"kind": "local_fs", "path": str(target_dir)},
        )
        result = load(config)

    assert result.total_rows == sum(df.height for df in datasets.values())
    assert set(result.tables_written) == set(datasets)
