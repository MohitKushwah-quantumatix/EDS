"""SSH/SFTP connector — source and target over SSH.

Reads EDS-generated Parquet files and ``schema.json`` from a remote server
over SSH/SFTP (**source** role) and writes Parquet files back to a remote
path (**target** role).

Driver
------
:pypi:`paramiko` (``pip install eds-loader[remote_fs]``).

When paramiko is not installed, this module still imports cleanly and
registers the connector with ``connector_class=None``, so
``eds-loader connectors`` shows a helpful install hint rather than an
``ImportError`` traceback.

Auth modes
----------
Two modes are supported, controlled by config fields:

1. **Password** — ``password`` (inline) or ``password_env`` (env-var name).
2. **Private key** — ``private_key_path`` + optional
   ``private_key_passphrase_env``.

If neither is set, paramiko falls back to the running SSH agent.

Lazy connection
---------------
The SSH connection is not opened in ``__init__``.  It is opened on the
first call to ``read_*`` or ``write_*`` and cached for the lifetime of the
connector.  Use the connector as a context manager for explicit lifetime
control::

    with RemoteFSConnector(...) as conn:
        data = conn.read_datasets()
"""

from __future__ import annotations

import io
import json
import os
import socket
from pathlib import Path, PurePosixPath
from typing import Any

import polars as pl

from eds_loader.connectors.base import WriteResult
from eds_loader.connectors.registry import ConnectorSpec, register_connector
from eds_loader.exceptions import LoadError

__all__ = ["RemoteFSConnector"]

_SCHEMA_FILE = "schema.json"

# Optional dependency — wrapped so the module always imports cleanly.
try:
    import paramiko as _paramiko  # type: ignore[import]
    _PARAMIKO_AVAILABLE = True
except ImportError:
    _paramiko = None  # type: ignore[assignment]
    _PARAMIKO_AVAILABLE = False


class RemoteFSConnector:
    """Read and write EDS Parquet datasets on a remote server over SSH/SFTP.

    Acts as both a **source** (implements
    :class:`~eds_loader.connectors.base.Readable`) and a **target**
    (implements :class:`~eds_loader.connectors.base.Writable`).

    Config fields
    -------------
    ``host`` (required)
        SSH server hostname or IP address.
    ``username`` (required)
        SSH login username.
    ``remote_path`` (required)
        Absolute path on the remote server to the directory containing
        ``.parquet`` files and ``schema.json``.
    ``port``
        SSH port (default: ``22``).
    ``password`` / ``password_env``
        Inline password or name of env-var holding the password.
        ``password_env`` is preferred — keeps secrets out of YAML files.
    ``private_key_path``
        Local path to an SSH private-key file (``~`` is expanded).
    ``private_key_passphrase_env``
        Env-var name holding the key passphrase, if the key is encrypted.
    ``known_hosts_file``
        Path to a ``known_hosts`` file.  Pass ``"none"`` to skip host-key
        verification (useful in dev — **not recommended in production**).
        Omit to use the system ``known_hosts``.
    ``timeout``
        Connection timeout in seconds (default: ``30``).

    Example configs::

        # Key-based auth
        source:
          kind: remote_fs
          host: data.mycompany.com
          username: eds_service
          private_key_path: ~/.ssh/eds_rsa
          remote_path: /home/eds_service/output

        # Password auth via env-var
        source:
          kind: remote_fs
          host: 192.168.1.100
          username: admin
          password_env: SSH_PASSWORD
          remote_path: /var/data/eds_output
          known_hosts_file: none
    """

    def __init__(
        self,
        host: str,
        username: str,
        remote_path: str,
        port: int = 22,
        password: str | None = None,
        password_env: str | None = None,
        private_key_path: str | None = None,
        private_key_passphrase_env: str | None = None,
        known_hosts_file: str | None = None,
        timeout: int = 30,
        **_kwargs: Any,  # absorb unknown future config fields gracefully
    ) -> None:
        self._host = host
        self._username = username
        self._remote_path = PurePosixPath(remote_path)
        self._port = int(port)
        self._password = password
        self._password_env = password_env
        self._private_key_path = private_key_path
        self._private_key_passphrase_env = private_key_passphrase_env
        self._known_hosts_file = known_hosts_file
        self._timeout = int(timeout)

        # Populated lazily on first use.
        self._ssh: Any = None
        self._sftp: Any = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_credential(self, value: str | None, env_name: str | None) -> str | None:
        """Return a credential, preferring env-var form.

        Secrets are never included in raised exceptions — only the env-var
        *name* is mentioned.
        """
        if env_name:
            val = os.environ.get(env_name)
            if val is None:
                raise LoadError(
                    f"Environment variable {env_name!r} is not set."
                )
            return val
        return value

    def _connect(self) -> tuple[Any, Any]:
        """Open (or return the cached) SSH + SFTP connection.

        Returns:
            ``(SSHClient, SFTPClient)`` tuple.

        Raises:
            LoadError: On authentication failure or network error.
        """
        if self._ssh is not None and self._sftp is not None:
            return self._ssh, self._sftp

        client = _paramiko.SSHClient()

        # Host key policy.
        if self._known_hosts_file and self._known_hosts_file.lower() == "none":
            client.set_missing_host_key_policy(_paramiko.AutoAddPolicy())
        elif self._known_hosts_file:
            client.load_host_keys(self._known_hosts_file)
            client.set_missing_host_key_policy(_paramiko.RejectPolicy())
        else:
            client.load_system_host_keys()
            client.set_missing_host_key_policy(_paramiko.RejectPolicy())

        connect_kwargs: dict[str, Any] = {
            "hostname": self._host,
            "port": self._port,
            "username": self._username,
            "timeout": self._timeout,
        }

        try:
            if self._private_key_path:
                passphrase = self._resolve_credential(None, self._private_key_passphrase_env)
                key_file = str(Path(self._private_key_path).expanduser())
                try:
                    pkey = _paramiko.RSAKey.from_private_key_file(
                        key_file, password=passphrase
                    )
                except _paramiko.PasswordRequiredException:
                    raise LoadError(
                        f"Private key at {key_file} requires a passphrase. "
                        "Set private_key_passphrase_env in config."
                    )
                connect_kwargs["pkey"] = pkey
            else:
                password = self._resolve_credential(self._password, self._password_env)
                if password is not None:
                    connect_kwargs["password"] = password

            client.connect(**connect_kwargs)

        except _paramiko.AuthenticationException as exc:
            raise LoadError(
                f"SSH authentication failed for {self._username}@{self._host}: {exc}"
            ) from exc
        except (socket.timeout, socket.error, OSError) as exc:
            raise LoadError(
                f"SSH connection to {self._host}:{self._port} failed: {exc}"
            ) from exc
        except _paramiko.SSHException as exc:
            raise LoadError(
                f"SSH error connecting to {self._host}:{self._port}: {exc}"
            ) from exc

        sftp = client.open_sftp()
        self._ssh = client
        self._sftp = sftp
        return client, sftp

    def _disconnect(self) -> None:
        """Close SSH and SFTP connections gracefully."""
        if self._sftp is not None:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None
        if self._ssh is not None:
            try:
                self._ssh.close()
            except Exception:
                pass
            self._ssh = None

    def __enter__(self) -> "RemoteFSConnector":
        self._connect()
        return self

    def __exit__(self, *_args: object) -> None:
        self._disconnect()

    def __del__(self) -> None:
        self._disconnect()

    def _download_bytes(self, remote_file: str) -> bytes:
        """Download one file from the remote server into memory.

        Args:
            remote_file: Absolute path on the remote server.

        Returns:
            Raw file bytes.

        Raises:
            LoadError: If the file is missing or the download fails.
        """
        _, sftp = self._connect()
        buf = io.BytesIO()
        try:
            sftp.getfo(remote_file, buf)
        except FileNotFoundError:
            raise LoadError(
                f"Remote file not found: {remote_file} on {self._host}"
            ) from None
        except Exception as exc:
            raise LoadError(
                f"Cannot download {remote_file} from {self._host}: {exc}"
            ) from exc
        return buf.getvalue()

    def _upload_bytes(self, data: bytes, remote_file: str) -> None:
        """Upload raw bytes to one file on the remote server.

        Args:
            data: File contents to upload.
            remote_file: Absolute path on the remote server.

        Raises:
            LoadError: If the upload fails.
        """
        _, sftp = self._connect()
        buf = io.BytesIO(data)
        try:
            sftp.putfo(buf, remote_file)
        except Exception as exc:
            raise LoadError(
                f"Cannot upload to {remote_file} on {self._host}: {exc}"
            ) from exc

    def _list_parquet_names(self) -> list[str]:
        """List all ``.parquet`` dataset names in ``remote_path``.

        Returns:
            Sorted list of dataset name stems (no extension).

        Raises:
            LoadError: If the remote directory cannot be listed.
        """
        _, sftp = self._connect()
        remote_dir = str(self._remote_path)
        try:
            attrs = sftp.listdir_attr(remote_dir)
        except FileNotFoundError:
            raise LoadError(
                f"Remote directory not found: {remote_dir} on {self._host}"
            ) from None
        except Exception as exc:
            raise LoadError(
                f"Cannot list remote directory {remote_dir} on {self._host}: {exc}"
            ) from exc
        return sorted(
            PurePosixPath(attr.filename).stem
            for attr in attrs
            if attr.filename.endswith(".parquet")
        )

    def _ensure_remote_dir(self) -> None:
        """Create ``remote_path`` on the server if it does not exist."""
        _, sftp = self._connect()
        remote_dir = str(self._remote_path)
        try:
            sftp.stat(remote_dir)
        except FileNotFoundError:
            try:
                sftp.mkdir(remote_dir)
            except Exception as exc:
                raise LoadError(
                    f"Cannot create remote directory {remote_dir} on {self._host}: {exc}"
                ) from exc

    # ------------------------------------------------------------------
    # Readable interface
    # ------------------------------------------------------------------

    def read_schema_metadata(self) -> dict[str, Any]:
        """Download and parse ``schema.json`` from the remote source directory.

        Returns:
            Schema metadata dict.

        Raises:
            ~eds_loader.exceptions.LoadError: If ``schema.json`` is absent,
                unreadable, or contains invalid JSON.
        """
        remote_schema = str(self._remote_path / _SCHEMA_FILE)
        try:
            data = self._download_bytes(remote_schema)
        except LoadError:
            raise LoadError(
                f"schema.json not found at {remote_schema} on {self._host}.\n"
                "Run `eds generate <stage>` and sync the output to the remote server."
            ) from None

        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LoadError(
                f"schema.json at {remote_schema} on {self._host} is not valid JSON: {exc}"
            ) from exc

    def read_datasets(
        self,
        names: list[str] | None = None,
    ) -> dict[str, pl.DataFrame]:
        """Download Parquet datasets from the remote source directory.

        Args:
            names: Dataset names to download.  ``None`` lists every
                ``.parquet`` file in ``remote_path`` and reads them all.

        Returns:
            Dict mapping dataset name to its Polars DataFrame.

        Raises:
            ~eds_loader.exceptions.LoadError: If the directory cannot be
                listed or any dataset file is missing or unreadable.
        """
        if names is None:
            names = self._list_parquet_names()

        result: dict[str, pl.DataFrame] = {}
        for name in names:
            remote_file = str(self._remote_path / f"{name}.parquet")
            try:
                data = self._download_bytes(remote_file)
            except LoadError:
                raise LoadError(
                    f"Dataset {name!r} not found at {remote_file} on {self._host}."
                ) from None
            try:
                result[name] = pl.read_parquet(io.BytesIO(data))
            except Exception as exc:
                raise LoadError(
                    f"Cannot parse dataset {name!r} downloaded from {self._host}: {exc}"
                ) from exc
        return result

    # ------------------------------------------------------------------
    # Writable interface
    # ------------------------------------------------------------------

    def write_datasets(
        self,
        datasets: dict[str, pl.DataFrame],
        schema_metadata: dict[str, Any],
    ) -> list[WriteResult]:
        """Upload Parquet datasets to the remote target directory.

        Creates ``remote_path`` if it does not exist.  Existing files are
        overwritten (full replace — NFR-3).  If ``schema_metadata`` is
        non-empty, ``schema.json`` is merged and uploaded alongside the
        Parquet files.

        Args:
            datasets: Dataset name to Polars DataFrame.
            schema_metadata: Schema metadata to merge into ``schema.json``
                at the target.  Pass an empty dict to skip.

        Returns:
            One :class:`~eds_loader.connectors.base.WriteResult` per
            dataset written.  ``location`` is formatted as
            ``sftp://<host>:<port><remote_file>``.

        Raises:
            ~eds_loader.exceptions.LoadError: If the directory cannot be
                created or any file cannot be uploaded.
        """
        self._ensure_remote_dir()

        results: list[WriteResult] = []
        for name, df in datasets.items():
            remote_file = str(self._remote_path / f"{name}.parquet")
            buf = io.BytesIO()
            df.write_parquet(buf)
            self._upload_bytes(buf.getvalue(), remote_file)
            location = f"sftp://{self._host}:{self._port}{remote_file}"
            results.append(WriteResult(dataset=name, location=location, rows=df.height))

        if schema_metadata:
            remote_schema = str(self._remote_path / _SCHEMA_FILE)
            # Merge with any existing schema.json on the remote.
            existing: dict[str, Any] = {}
            try:
                raw = self._download_bytes(remote_schema)
                existing = json.loads(raw.decode("utf-8"))
            except (LoadError, json.JSONDecodeError, UnicodeDecodeError):
                existing = {}
            existing.update(schema_metadata)
            merged = (json.dumps(existing, indent=2, sort_keys=True) + "\n").encode("utf-8")
            self._upload_bytes(merged, remote_schema)

        return results


# ---------------------------------------------------------------------------
# Self-registration — runs once when this module is first imported.
# ---------------------------------------------------------------------------
register_connector(
    "remote_fs",
    ConnectorSpec(
        connector_class=RemoteFSConnector if _PARAMIKO_AVAILABLE else None,
        required_packages=["paramiko"],
        install_extra="remote_fs",
        can_read=True,
        can_write=True,
        description=(
            "SSH/SFTP — reads/writes Parquet files on a remote server over SSH. "
            "Requires: pip install eds-loader[remote_fs]"
        ),
    ),
)
