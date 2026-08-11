"""Azure Blob Storage connector — source and target.

Reads and writes EDS Parquet datasets from/to an Azure Blob container.

Inherits shared file I/O logic from
:class:`~eds_loader.connectors._cloud_base.CloudBaseConnector`.

Driver
------
:pypi:`azure-storage-blob` (``pip install eds-loader[azure]``).

When the driver is not installed, this module still imports cleanly and
registers the connector with ``connector_class=None``.

Auth
----
Two mutually exclusive options:

1. **Connection string** — ``connection_string`` or ``connection_string_env``
2. **Account key** — ``account_name`` + ``account_key`` / ``account_key_env``
"""

from __future__ import annotations

import os
from typing import Any

from eds_loader.connectors._cloud_base import CloudBaseConnector
from eds_loader.connectors.registry import ConnectorSpec, register_connector
from eds_loader.exceptions import LoadError

__all__ = ["AzureBlobConnector"]

try:
    from azure.storage.blob import BlobServiceClient as _BlobServiceClient  # type: ignore[import]
    _AZURE_AVAILABLE = True
except ImportError:
    _BlobServiceClient = None  # type: ignore[assignment]
    _AZURE_AVAILABLE = False


class AzureBlobConnector(CloudBaseConnector):
    """Read / write EDS datasets in Azure Blob Storage.

    Implements both :class:`~eds_loader.connectors.base.Readable` and
    :class:`~eds_loader.connectors.base.Writable` via
    :class:`~eds_loader.connectors._cloud_base.CloudBaseConnector`.

    Config fields
    -------------
    ``account_name`` (required)
        Azure storage account name.
    ``container`` (required)
        Blob container name.
    ``prefix``
        Blob name prefix (acts as a directory).  Default: ``""`` (container root).
    ``account_key`` / ``account_key_env``
        Storage account key inline or via env-var.
    ``connection_string`` / ``connection_string_env``
        Full connection string inline or via env-var (takes precedence over
        account key when set).

    Example config::

        source:
          kind: azure_blob
          account_name: myaccount
          container: eds-data
          prefix: datasets/2024/
          account_key_env: AZURE_STORAGE_KEY
    """

    def __init__(
        self,
        account_name: str,
        container: str,
        prefix: str = "",
        account_key: str | None = None,
        account_key_env: str | None = None,
        connection_string: str | None = None,
        connection_string_env: str | None = None,
        **_kwargs: Any,
    ) -> None:
        super().__init__(prefix=prefix)
        self._account_name = account_name
        self._container = container
        self._account_key = account_key
        self._account_key_env = account_key_env
        self._connection_string = connection_string
        self._connection_string_env = connection_string_env

    # ------------------------------------------------------------------
    # Credential resolution
    # ------------------------------------------------------------------

    def _resolve_account_key(self) -> str | None:
        if self._account_key_env:
            val = os.environ.get(self._account_key_env)
            if val is None:
                raise LoadError(
                    f"Environment variable {self._account_key_env!r} is not set."
                )
            return val
        return self._account_key

    def _resolve_connection_string(self) -> str | None:
        if self._connection_string_env:
            val = os.environ.get(self._connection_string_env)
            if val is None:
                raise LoadError(
                    f"Environment variable {self._connection_string_env!r} is not set."
                )
            return val
        return self._connection_string

    # ------------------------------------------------------------------
    # Abstract method overrides
    # ------------------------------------------------------------------

    def _connect(self) -> Any:
        """Create and return a :class:`azure.storage.blob.BlobServiceClient`."""
        try:
            conn_str = self._resolve_connection_string()
            if conn_str:
                return _BlobServiceClient.from_connection_string(conn_str)
            account_key = self._resolve_account_key()
            return _BlobServiceClient(
                account_url=(
                    f"https://{self._account_name}.blob.core.windows.net"
                ),
                credential=account_key,
            )
        except LoadError:
            raise
        except Exception as exc:
            raise LoadError(f"Cannot create Azure Blob client: {exc}") from exc

    def _list_parquet_keys(self) -> list[str]:
        """List all ``*.parquet`` blob names in the container under the prefix."""
        client = self._get_client()
        try:
            cc = client.get_container_client(self._container)
            return [
                b.name
                for b in cc.list_blobs(name_starts_with=self._prefix)
                if b.name.endswith(".parquet")
            ]
        except Exception as exc:
            raise LoadError(
                f"Cannot list blobs in "
                f"azure://{self._account_name}/{self._container}/{self._prefix}: {exc}"
            ) from exc

    def _read_bytes(self, key: str) -> bytes:
        """Download one blob and return its raw bytes."""
        client = self._get_client()
        try:
            return (
                client.get_blob_client(self._container, key)
                .download_blob()
                .readall()
            )
        except Exception as exc:
            raise LoadError(
                f"Cannot download "
                f"azure://{self._account_name}/{self._container}/{key}: {exc}"
            ) from exc

    def _write_bytes(self, key: str, data: bytes) -> None:
        """Upload *data* to a blob at *key* (overwrites existing)."""
        client = self._get_client()
        try:
            client.get_blob_client(self._container, key).upload_blob(
                data, overwrite=True
            )
        except Exception as exc:
            raise LoadError(
                f"Cannot upload to "
                f"azure://{self._account_name}/{self._container}/{key}: {exc}"
            ) from exc

    def _location(self, dataset_name: str) -> str:
        return (
            f"azure://{self._account_name}/{self._container}"
            f"/{self._key(f'{dataset_name}.parquet')}"
        )


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------
register_connector(
    "azure_blob",
    ConnectorSpec(
        connector_class=AzureBlobConnector if _AZURE_AVAILABLE else None,
        required_packages=["azure.storage.blob"],
        install_extra="azure",
        can_read=True,
        can_write=True,
        description=(
            "Azure Blob Storage — reads/writes Parquet datasets in a blob "
            "container. Requires: pip install eds-loader[azure]"
        ),
    ),
)
