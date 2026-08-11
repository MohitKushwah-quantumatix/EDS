"""Tests for RemoteFSConnector.

All tests use mocked paramiko — no real SSH server required.

Strategy
--------
- **Registration tests**: check the registry entry after import.
- **Connection tests**: patch ``paramiko.SSHClient`` at the module level via
  ``patch("eds_loader.connectors.remote_fs._paramiko")``.
- **Read / write unit tests**: inject pre-built mock SSH + SFTP objects
  directly into ``conn._ssh`` and ``conn._sftp``, bypassing ``_connect()``.
  This avoids re-testing connection logic in every unit test.

paramiko availability
---------------------
``pytest.importorskip("paramiko")`` at the top of the file skips the entire
module if paramiko is not installed.  Because paramiko is listed in
``[dev]`` dependencies, it is always present in a normal dev environment.
"""

from __future__ import annotations

import io
import json
from pathlib import PurePosixPath
from typing import Any
from unittest.mock import MagicMock, call, patch

import polars as pl
import pytest

paramiko = pytest.importorskip("paramiko")  # skip whole file if not installed

from eds_loader.connectors.registry import CONNECTORS
from eds_loader.connectors.remote_fs import RemoteFSConnector
from eds_loader.exceptions import LoadError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(
    host: str = "test.example.com",
    username: str = "testuser",
    remote_path: str = "/data/eds",
    **kwargs: Any,
) -> RemoteFSConnector:
    """Build a connector without opening any real SSH connection."""
    return RemoteFSConnector(
        host=host,
        username=username,
        remote_path=remote_path,
        known_hosts_file="none",
        **kwargs,
    )


def _inject_sftp(conn: RemoteFSConnector) -> MagicMock:
    """Inject a mock SFTP (and SSH) into *conn*, bypassing _connect().

    Returns the mock SFTP client for further setup.
    """
    mock_sftp = MagicMock()
    mock_ssh = MagicMock()
    conn._ssh = mock_ssh
    conn._sftp = mock_sftp
    return mock_sftp


def _make_getfo(data: bytes):
    """Return a ``getfo`` side_effect that writes *data* into the BytesIO arg."""
    def _getfo(remote_path: str, buf: io.BytesIO) -> None:
        buf.write(data)
    return _getfo


def _parquet_bytes(df: pl.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.write_parquet(buf)
    return buf.getvalue()


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
            "foreign_keys": [],
        },
    }


def _sample_datasets() -> dict[str, pl.DataFrame]:
    return {
        "customers": pl.DataFrame({"customer_id": [1, 2], "name": ["Alice", "Bob"]}),
        "orders": pl.DataFrame({"order_id": [10], "customer_id": [1]}),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_remote_fs_is_registered() -> None:
    import eds_loader  # noqa: F401 — triggers __init__.py
    assert "remote_fs" in CONNECTORS


def test_remote_fs_can_read_and_write() -> None:
    spec = CONNECTORS["remote_fs"]
    assert spec.can_read is True
    assert spec.can_write is True


def test_remote_fs_requires_paramiko() -> None:
    spec = CONNECTORS["remote_fs"]
    assert "paramiko" in spec.required_packages
    assert spec.install_extra == "remote_fs"


def test_remote_fs_connector_class_is_set_when_paramiko_available() -> None:
    """Since paramiko is in dev deps, connector_class must not be None."""
    spec = CONNECTORS["remote_fs"]
    assert spec.connector_class is RemoteFSConnector


# ---------------------------------------------------------------------------
# _connect() — password auth
# ---------------------------------------------------------------------------

def test_connect_password_calls_ssh_connect() -> None:
    conn = _make_conn(password="s3cret")
    with patch("eds_loader.connectors.remote_fs._paramiko") as mock_pm:
        mock_ssh = MagicMock()
        mock_pm.SSHClient.return_value = mock_ssh
        mock_pm.AutoAddPolicy = MagicMock
        mock_pm.RejectPolicy = MagicMock
        mock_pm.AuthenticationException = paramiko.AuthenticationException
        mock_pm.SSHException = paramiko.SSHException
        mock_pm.PasswordRequiredException = paramiko.PasswordRequiredException

        conn._ssh = None
        conn._sftp = None
        conn._connect()

        mock_ssh.connect.assert_called_once_with(
            hostname="test.example.com",
            port=22,
            username="testuser",
            timeout=30,
            password="s3cret",
        )


def test_connect_password_env_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_SSH_PASS", "env_secret")
    conn = _make_conn(password_env="MY_SSH_PASS")
    with patch("eds_loader.connectors.remote_fs._paramiko") as mock_pm:
        mock_ssh = MagicMock()
        mock_pm.SSHClient.return_value = mock_ssh
        mock_pm.AutoAddPolicy = MagicMock
        mock_pm.RejectPolicy = MagicMock
        mock_pm.AuthenticationException = paramiko.AuthenticationException
        mock_pm.SSHException = paramiko.SSHException
        mock_pm.PasswordRequiredException = paramiko.PasswordRequiredException

        conn._ssh = None
        conn._sftp = None
        conn._connect()

        _, kwargs = mock_ssh.connect.call_args
        assert kwargs["password"] == "env_secret"


def test_connect_missing_password_env_raises_load_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_SSH_PASS", raising=False)
    conn = _make_conn(password_env="MISSING_SSH_PASS")
    with pytest.raises(LoadError, match="MISSING_SSH_PASS"):
        conn._connect()


def test_connect_caches_connection() -> None:
    """Calling _connect() twice returns the same objects."""
    conn = _make_conn()
    mock_sftp = _inject_sftp(conn)
    ssh1, sftp1 = conn._connect()
    ssh2, sftp2 = conn._connect()
    assert sftp1 is sftp2


# ---------------------------------------------------------------------------
# _connect() — private key auth
# ---------------------------------------------------------------------------

def test_connect_private_key_loads_rsa_key(tmp_path: pytest.TempPathFactory) -> None:
    # Generate a real RSA key to put on disk
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    try:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        )
        key_file = tmp_path / "id_rsa"
        key_file.write_bytes(pem)
    except Exception:
        pytest.skip("cryptography package not available for key generation")

    conn = _make_conn(private_key_path=str(key_file))
    with patch("eds_loader.connectors.remote_fs._paramiko") as mock_pm:
        mock_ssh = MagicMock()
        mock_pm.SSHClient.return_value = mock_ssh
        mock_pm.AutoAddPolicy = MagicMock
        mock_pm.RejectPolicy = MagicMock
        mock_pm.AuthenticationException = paramiko.AuthenticationException
        mock_pm.SSHException = paramiko.SSHException
        mock_pm.PasswordRequiredException = paramiko.PasswordRequiredException
        mock_pm.RSAKey.from_private_key_file.return_value = MagicMock()

        conn._ssh = None
        conn._sftp = None
        conn._connect()

        mock_pm.RSAKey.from_private_key_file.assert_called_once()
        # connect should have been called with pkey, not password
        _, kwargs = mock_ssh.connect.call_args
        assert "pkey" in kwargs
        assert "password" not in kwargs


# ---------------------------------------------------------------------------
# _connect() — error handling
# ---------------------------------------------------------------------------

def test_connect_auth_failure_raises_load_error() -> None:
    conn = _make_conn(password="wrong")
    with patch("eds_loader.connectors.remote_fs._paramiko") as mock_pm:
        mock_ssh = MagicMock()
        mock_pm.SSHClient.return_value = mock_ssh
        mock_pm.AutoAddPolicy = MagicMock
        mock_pm.AuthenticationException = paramiko.AuthenticationException
        mock_pm.SSHException = paramiko.SSHException
        mock_pm.PasswordRequiredException = paramiko.PasswordRequiredException
        mock_ssh.connect.side_effect = paramiko.AuthenticationException("bad creds")

        conn._ssh = None
        conn._sftp = None
        with pytest.raises(LoadError, match="authentication failed"):
            conn._connect()


def test_connect_network_error_raises_load_error() -> None:
    import socket
    conn = _make_conn()
    with patch("eds_loader.connectors.remote_fs._paramiko") as mock_pm:
        mock_ssh = MagicMock()
        mock_pm.SSHClient.return_value = mock_ssh
        mock_pm.AutoAddPolicy = MagicMock
        mock_pm.AuthenticationException = paramiko.AuthenticationException
        mock_pm.SSHException = paramiko.SSHException
        mock_pm.PasswordRequiredException = paramiko.PasswordRequiredException
        mock_ssh.connect.side_effect = socket.timeout("timed out")

        conn._ssh = None
        conn._sftp = None
        with pytest.raises(LoadError, match="failed"):
            conn._connect()


# ---------------------------------------------------------------------------
# _disconnect() and context manager
# ---------------------------------------------------------------------------

def test_disconnect_closes_sftp_and_ssh() -> None:
    conn = _make_conn()
    mock_sftp = _inject_sftp(conn)
    conn._disconnect()
    mock_sftp.close.assert_called_once()
    conn._sftp  # None after disconnect
    assert conn._sftp is None
    assert conn._ssh is None


def test_context_manager_disconnects_on_exit() -> None:
    conn = _make_conn()
    mock_sftp = _inject_sftp(conn)
    with conn:
        pass
    mock_sftp.close.assert_called_once()


# ---------------------------------------------------------------------------
# read_schema_metadata
# ---------------------------------------------------------------------------

def test_read_schema_metadata_downloads_and_parses_json() -> None:
    schema = _sample_schema()
    schema_bytes = json.dumps(schema).encode("utf-8")
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.getfo.side_effect = _make_getfo(schema_bytes)

    result = conn.read_schema_metadata()

    assert result == schema
    sftp.getfo.assert_called_once()
    called_path = sftp.getfo.call_args[0][0]
    assert called_path.endswith("schema.json")


def test_read_schema_metadata_missing_raises_load_error() -> None:
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.getfo.side_effect = FileNotFoundError("no such file")

    with pytest.raises(LoadError, match="schema.json not found"):
        conn.read_schema_metadata()


def test_read_schema_metadata_corrupt_json_raises_load_error() -> None:
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.getfo.side_effect = _make_getfo(b"{not valid json!!!}")

    with pytest.raises(LoadError, match="not valid JSON"):
        conn.read_schema_metadata()


def test_read_schema_metadata_empty_bytes_raises_load_error() -> None:
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.getfo.side_effect = _make_getfo(b"")

    with pytest.raises(LoadError):
        conn.read_schema_metadata()


# ---------------------------------------------------------------------------
# read_datasets — names=None (scan remote dir)
# ---------------------------------------------------------------------------

def test_read_datasets_none_lists_remote_parquet_files() -> None:
    datasets = _sample_datasets()
    schema = _sample_schema()
    conn = _make_conn()
    sftp = _inject_sftp(conn)

    # listdir_attr returns attr objects with .filename
    def _make_attr(name: str) -> MagicMock:
        a = MagicMock()
        a.filename = name
        return a

    sftp.listdir_attr.return_value = [
        _make_attr("customers.parquet"),
        _make_attr("orders.parquet"),
        _make_attr("schema.json"),       # should be ignored
        _make_attr("readme.txt"),        # should be ignored
    ]

    # getfo dispatches by filename
    def _dispatch_getfo(path: str, buf: io.BytesIO) -> None:
        name = PurePosixPath(path).stem
        if name in datasets:
            datasets[name].write_parquet(buf)
        else:
            raise FileNotFoundError(path)

    sftp.getfo.side_effect = _dispatch_getfo

    result = conn.read_datasets(names=None)
    assert set(result) == {"customers", "orders"}


def test_read_datasets_none_ignores_non_parquet_entries() -> None:
    conn = _make_conn()
    sftp = _inject_sftp(conn)

    def _make_attr(name: str) -> MagicMock:
        a = MagicMock()
        a.filename = name
        return a

    sftp.listdir_attr.return_value = [
        _make_attr("data.parquet"),
        _make_attr("schema.json"),
        _make_attr("notes.txt"),
    ]

    customers_df = pl.DataFrame({"id": [1]})
    sftp.getfo.side_effect = _make_getfo(_parquet_bytes(customers_df))

    result = conn.read_datasets(names=None)
    assert set(result) == {"data"}


def test_read_datasets_none_remote_dir_missing_raises_load_error() -> None:
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.listdir_attr.side_effect = FileNotFoundError("no dir")

    with pytest.raises(LoadError, match="Remote directory not found"):
        conn.read_datasets(names=None)


# ---------------------------------------------------------------------------
# read_datasets — explicit names
# ---------------------------------------------------------------------------

def test_read_datasets_explicit_names_downloads_only_those() -> None:
    customers_df = pl.DataFrame({"customer_id": [1, 2], "name": ["A", "B"]})
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.getfo.side_effect = _make_getfo(_parquet_bytes(customers_df))

    result = conn.read_datasets(names=["customers"])

    assert set(result) == {"customers"}
    assert sftp.getfo.call_count == 1
    called_path = sftp.getfo.call_args[0][0]
    assert "customers.parquet" in called_path


def test_read_datasets_explicit_preserves_data() -> None:
    df = pl.DataFrame({"id": [10, 20, 30], "val": ["a", "b", "c"]})
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.getfo.side_effect = _make_getfo(_parquet_bytes(df))

    result = conn.read_datasets(names=["my_table"])
    assert result["my_table"].to_dict(as_series=False) == df.to_dict(as_series=False)


def test_read_datasets_missing_file_raises_load_error() -> None:
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.getfo.side_effect = FileNotFoundError("not found")

    with pytest.raises(LoadError, match="'no_such_table'"):
        conn.read_datasets(names=["no_such_table"])


# ---------------------------------------------------------------------------
# write_datasets
# ---------------------------------------------------------------------------

def test_write_datasets_uploads_one_file_per_dataset() -> None:
    datasets = _sample_datasets()
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.stat.return_value = MagicMock()  # remote dir "exists"

    conn.write_datasets(datasets, schema_metadata={})

    # putfo called once per dataset (no schema.json because metadata is empty)
    assert sftp.putfo.call_count == len(datasets)
    uploaded_paths = [call_args[0][1] for call_args in sftp.putfo.call_args_list]
    assert any("customers.parquet" in p for p in uploaded_paths)
    assert any("orders.parquet" in p for p in uploaded_paths)


def test_write_datasets_uploads_schema_json_when_metadata_nonempty() -> None:
    datasets = _sample_datasets()
    schema = _sample_schema()
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.stat.return_value = MagicMock()  # remote dir "exists"
    # First getfo for existing schema.json → not found (no existing)
    sftp.getfo.side_effect = FileNotFoundError("no schema yet")

    conn.write_datasets(datasets, schema_metadata=schema)

    uploaded_paths = [call_args[0][1] for call_args in sftp.putfo.call_args_list]
    assert any("schema.json" in p for p in uploaded_paths)


def test_write_datasets_skips_schema_json_when_metadata_empty() -> None:
    datasets = _sample_datasets()
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.stat.return_value = MagicMock()  # remote dir "exists"

    conn.write_datasets(datasets, schema_metadata={})

    uploaded_paths = [call_args[0][1] for call_args in sftp.putfo.call_args_list]
    assert not any("schema.json" in p for p in uploaded_paths)


def test_write_datasets_creates_remote_dir_when_missing() -> None:
    datasets = _sample_datasets()
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.stat.side_effect = FileNotFoundError("no dir")  # dir doesn't exist

    conn.write_datasets(datasets, schema_metadata={})

    sftp.mkdir.assert_called_once_with("/data/eds")


def test_write_datasets_returns_one_result_per_dataset() -> None:
    datasets = _sample_datasets()
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.stat.return_value = MagicMock()

    results = conn.write_datasets(datasets, schema_metadata={})

    assert len(results) == len(datasets)
    assert {r.dataset for r in results} == set(datasets)


def test_write_datasets_result_rows_match_dataframe_height() -> None:
    datasets = _sample_datasets()
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.stat.return_value = MagicMock()

    results = conn.write_datasets(datasets, schema_metadata={})
    rows_by_name = {r.dataset: r.rows for r in results}

    for name, df in datasets.items():
        assert rows_by_name[name] == df.height


def test_write_datasets_result_location_is_sftp_url() -> None:
    df = pl.DataFrame({"id": [1]})
    conn = _make_conn(host="myserver.com", port=2222)
    sftp = _inject_sftp(conn)
    sftp.stat.return_value = MagicMock()

    results = conn.write_datasets({"table1": df}, schema_metadata={})

    assert results[0].location.startswith("sftp://myserver.com:2222")
    assert "table1.parquet" in results[0].location


def test_write_datasets_upload_failure_raises_load_error() -> None:
    df = pl.DataFrame({"id": [1]})
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.stat.return_value = MagicMock()
    sftp.putfo.side_effect = OSError("disk full")

    with pytest.raises(LoadError, match="Cannot upload"):
        conn.write_datasets({"data": df}, schema_metadata={})


# ---------------------------------------------------------------------------
# schema.json merge on write
# ---------------------------------------------------------------------------

def test_write_datasets_merges_schema_with_existing_on_remote() -> None:
    """If schema.json already exists on the remote, it is merged not replaced."""
    pre_existing = {"old_table": {"columns": {}, "primary_key": None, "unique_columns": [], "foreign_keys": []}}
    pre_existing_bytes = json.dumps(pre_existing).encode("utf-8")
    new_schema = {"customers": {"columns": {"id": "int64"}, "primary_key": "id", "unique_columns": [], "foreign_keys": []}}

    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.stat.return_value = MagicMock()
    sftp.getfo.side_effect = _make_getfo(pre_existing_bytes)  # existing schema

    datasets = {"customers": pl.DataFrame({"id": [1]})}
    conn.write_datasets(datasets, schema_metadata=new_schema)

    # Capture what was uploaded for schema.json
    schema_upload_calls = [
        c for c in sftp.putfo.call_args_list
        if "schema.json" in c[0][1]
    ]
    assert len(schema_upload_calls) == 1
    uploaded_buf: io.BytesIO = schema_upload_calls[0][0][0]
    uploaded_buf.seek(0)
    merged = json.loads(uploaded_buf.read().decode("utf-8"))
    assert "old_table" in merged  # pre-existing key preserved
    assert "customers" in merged  # new key added


# ---------------------------------------------------------------------------
# _download_bytes error wrapping
# ---------------------------------------------------------------------------

def test_download_bytes_file_not_found_raises_load_error() -> None:
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.getfo.side_effect = FileNotFoundError("no file")

    with pytest.raises(LoadError, match="Remote file not found"):
        conn._download_bytes("/data/eds/missing.parquet")


def test_download_bytes_os_error_raises_load_error() -> None:
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.getfo.side_effect = OSError("connection reset")

    with pytest.raises(LoadError, match="Cannot download"):
        conn._download_bytes("/data/eds/broken.parquet")


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------

def test_connect_ssh_exception_raises_load_error() -> None:
    """A generic SSHException during connect wraps into LoadError."""
    conn = _make_conn()
    with patch("eds_loader.connectors.remote_fs._paramiko") as mock_pm:
        mock_ssh = MagicMock()
        mock_pm.SSHClient.return_value = mock_ssh
        mock_pm.AutoAddPolicy = MagicMock
        mock_pm.AuthenticationException = paramiko.AuthenticationException
        mock_pm.SSHException = paramiko.SSHException
        mock_pm.PasswordRequiredException = paramiko.PasswordRequiredException
        mock_ssh.connect.side_effect = paramiko.SSHException("banner timeout")

        conn._ssh = None
        conn._sftp = None
        with pytest.raises(LoadError, match="SSH error"):
            conn._connect()


def test_write_datasets_mkdir_failure_raises_load_error() -> None:
    """If remote dir is missing and mkdir fails, LoadError is raised."""
    df = pl.DataFrame({"id": [1]})
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.stat.side_effect = FileNotFoundError("no dir")
    sftp.mkdir.side_effect = OSError("permission denied")

    with pytest.raises(LoadError, match="Cannot create remote directory"):
        conn.write_datasets({"data": df}, schema_metadata={})


def test_custom_port_appears_in_result_location() -> None:
    """Non-default port is reflected in the sftp:// location URL."""
    df = pl.DataFrame({"id": [1]})
    conn = _make_conn(host="srv.example.com", port=2222)
    sftp = _inject_sftp(conn)
    sftp.stat.return_value = MagicMock()

    results = conn.write_datasets({"tbl": df}, schema_metadata={})

    assert "2222" in results[0].location
    assert "srv.example.com" in results[0].location


def test_read_datasets_empty_remote_dir_returns_empty_dict() -> None:
    """names=None on an empty directory returns {} without error."""
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.listdir_attr.return_value = []  # empty dir

    result = conn.read_datasets(names=None)
    assert result == {}


def test_write_datasets_corrupt_existing_schema_json_is_replaced() -> None:
    """A corrupt schema.json on the remote is silently discarded, not raised."""
    df = pl.DataFrame({"id": [1]})
    schema = {"tbl": {"columns": {"id": "int64"}, "primary_key": "id", "unique_columns": [], "foreign_keys": []}}
    conn = _make_conn()
    sftp = _inject_sftp(conn)
    sftp.stat.return_value = MagicMock()
    # getfo for existing schema.json returns corrupt bytes
    sftp.getfo.side_effect = _make_getfo(b"{not json}")

    conn.write_datasets({"tbl": df}, schema_metadata=schema)  # must not raise

    uploaded_paths = [c[0][1] for c in sftp.putfo.call_args_list]
    assert any("schema.json" in p for p in uploaded_paths)


# ---------------------------------------------------------------------------
# Integration — through load()
# ---------------------------------------------------------------------------

def test_integration_remote_fs_source_to_local_fs_target(tmp_path: pytest.TempPathFactory) -> None:
    """Full load() run: remote_fs source (mocked) → local_fs target (real disk)."""
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    datasets = _sample_datasets()
    schema = _sample_schema()

    # Build a RemoteFSConnector with a pre-injected SFTP mock.
    source_conn = _make_conn()
    mock_sftp = _inject_sftp(source_conn)

    # Make listdir_attr return the two dataset names.
    def _make_attr(name: str) -> MagicMock:
        a = MagicMock()
        a.filename = name
        return a

    mock_sftp.listdir_attr.return_value = [
        _make_attr("customers.parquet"),
        _make_attr("orders.parquet"),
    ]

    # Make getfo dispatch by file type.
    schema_bytes = json.dumps(schema).encode("utf-8")

    def _dispatch(path: str, buf: io.BytesIO) -> None:
        name = PurePosixPath(path).stem
        if path.endswith("schema.json"):
            buf.write(schema_bytes)
        elif name in datasets:
            datasets[name].write_parquet(buf)
        else:
            raise FileNotFoundError(path)

    mock_sftp.getfo.side_effect = _dispatch

    # Patch get_connector so that when kind=="remote_fs" it returns our mock.
    target_dir = tmp_path / "remote_to_local_target"

    original_get_connector = __import__(
        "eds_loader.connectors.registry", fromlist=["get_connector"]
    ).get_connector

    def _patched_get_connector(kind: str, config: dict):
        if kind == "remote_fs":
            return source_conn
        return original_get_connector(kind, config)

    with patch("eds_loader.loader.get_connector", side_effect=_patched_get_connector):
        config = LoaderConfig(
            source={"kind": "remote_fs", "host": "mock", "username": "u", "remote_path": "/d"},
            target={"kind": "local_fs", "path": str(target_dir)},
        )
        result = load(config)

    expected_rows = sum(df.height for df in datasets.values())
    assert result.total_rows == expected_rows
    assert set(result.tables_written) == set(datasets)
    for name in datasets:
        assert (target_dir / f"{name}.parquet").is_file()


def test_integration_table_subset_remote_to_local(tmp_path: pytest.TempPathFactory) -> None:
    """load() with tables=['customers'] only loads that one dataset from remote."""
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    datasets = _sample_datasets()
    schema = _sample_schema()

    source_conn = _make_conn()
    mock_sftp = _inject_sftp(source_conn)

    schema_bytes = json.dumps(schema).encode("utf-8")

    def _dispatch(path: str, buf: io.BytesIO) -> None:
        name = PurePosixPath(path).stem
        if path.endswith("schema.json"):
            buf.write(schema_bytes)
        elif name in datasets:
            datasets[name].write_parquet(buf)
        else:
            raise FileNotFoundError(path)

    mock_sftp.getfo.side_effect = _dispatch

    target_dir = tmp_path / "subset_target"

    original_get_connector = __import__(
        "eds_loader.connectors.registry", fromlist=["get_connector"]
    ).get_connector

    def _patched_get_connector(kind: str, config: dict):
        if kind == "remote_fs":
            return source_conn
        return original_get_connector(kind, config)

    with patch("eds_loader.loader.get_connector", side_effect=_patched_get_connector):
        config = LoaderConfig(
            source={"kind": "remote_fs", "host": "mock", "username": "u", "remote_path": "/d"},
            target={"kind": "local_fs", "path": str(target_dir)},
            tables=["customers"],
        )
        result = load(config)

    assert result.tables_written == ["customers"]
    assert (target_dir / "customers.parquet").is_file()
    assert not (target_dir / "orders.parquet").exists()
