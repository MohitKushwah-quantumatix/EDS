"""Google Cloud Storage connector — source and target.

Reads and writes EDS Parquet datasets from/to a GCS bucket.

Inherits shared file I/O logic from
:class:`~eds_loader.connectors._cloud_base.CloudBaseConnector`.

Driver
------
:pypi:`google-cloud-storage` (``pip install eds-loader[gcs]``).

When the driver is not installed, this module still imports cleanly and
registers the connector with ``connector_class=None``.

Auth
----
Three options (checked in order):

1. ``credentials_file`` — explicit path to a service account JSON file.
2. ``credentials_env`` — env-var whose *value* is the path to a service
   account JSON file.
3. Neither set — falls back to Google Application Default Credentials
   (``GOOGLE_APPLICATION_CREDENTIALS`` env-var or gcloud auth).
"""

from __future__ import annotations

import os
from typing import Any

from eds_loader.connectors._cloud_base import CloudBaseConnector
from eds_loader.connectors.registry import ConnectorSpec, register_connector
from eds_loader.exceptions import LoadError

__all__ = ["GCSConnector"]

try:
    from google.cloud import storage as _gcs  # type: ignore[import]
    _GCS_AVAILABLE = True
except ImportError:
    _gcs = None  # type: ignore[assignment]
    _GCS_AVAILABLE = False


class GCSConnector(CloudBaseConnector):
    """Read / write EDS datasets in a Google Cloud Storage bucket.

    Implements both :class:`~eds_loader.connectors.base.Readable` and
    :class:`~eds_loader.connectors.base.Writable` via
    :class:`~eds_loader.connectors._cloud_base.CloudBaseConnector`.

    Config fields
    -------------
    ``bucket`` (required)
        GCS bucket name.
    ``prefix``
        Object prefix (acts as a directory).  Default: ``""`` (bucket root).
    ``credentials_file``
        Absolute path to a service account JSON key file.
    ``credentials_env``
        Env-var whose *value* is the path to a service account JSON file.
        Takes precedence over ``credentials_file`` when both are set.
    ``project``
        GCP project ID.  Usually inferred from credentials; set explicitly
        when using Application Default Credentials without a project.

    Example config::

        source:
          kind: gcs
          bucket: my-eds-bucket
          prefix: datasets/2024/
          credentials_env: GOOGLE_APPLICATION_CREDENTIALS
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        credentials_file: str | None = None,
        credentials_env: str | None = None,
        project: str | None = None,
        **_kwargs: Any,
    ) -> None:
        super().__init__(prefix=prefix)
        self._bucket_name = bucket
        self._credentials_file = credentials_file
        self._credentials_env = credentials_env
        self._project = project

    # ------------------------------------------------------------------
    # Credential resolution
    # ------------------------------------------------------------------

    def _resolve_credentials_file(self) -> str | None:
        """Return the path to the service account JSON file."""
        if self._credentials_env:
            val = os.environ.get(self._credentials_env)
            if val is None:
                raise LoadError(
                    f"Environment variable {self._credentials_env!r} is not set."
                )
            return val
        return self._credentials_file

    # ------------------------------------------------------------------
    # Abstract method overrides
    # ------------------------------------------------------------------

    def _connect(self) -> Any:
        """Create and return a :class:`google.cloud.storage.Client`."""
        try:
            cred_file = self._resolve_credentials_file()
            if cred_file:
                return _gcs.Client.from_service_account_json(
                    cred_file, project=self._project
                )
            # Application Default Credentials
            return _gcs.Client(project=self._project)
        except LoadError:
            raise
        except Exception as exc:
            raise LoadError(f"Cannot create GCS client: {exc}") from exc

    def _list_keys_by_extension(self, ext: str) -> list[str]:
        """List all object names ending with *ext* in the bucket under the prefix."""
        client = self._get_client()
        try:
            bucket = client.bucket(self._bucket_name)
            return [
                blob.name
                for blob in client.list_blobs(bucket, prefix=self._prefix)
                if blob.name.endswith(ext)
            ]
        except Exception as exc:
            raise LoadError(
                f"Cannot list gs://{self._bucket_name}/{self._prefix}: {exc}"
            ) from exc

    def _read_bytes(self, key: str) -> bytes:
        """Download one GCS object and return its raw bytes."""
        client = self._get_client()
        try:
            return client.bucket(self._bucket_name).blob(key).download_as_bytes()
        except Exception as exc:
            raise LoadError(
                f"Cannot download gs://{self._bucket_name}/{key}: {exc}"
            ) from exc

    def _write_bytes(self, key: str, data: bytes) -> None:
        """Upload *data* to a GCS object at *key*."""
        client = self._get_client()
        try:
            client.bucket(self._bucket_name).blob(key).upload_from_string(data)
        except Exception as exc:
            raise LoadError(
                f"Cannot upload to gs://{self._bucket_name}/{key}: {exc}"
            ) from exc

    def _location(self, dataset_name: str) -> str:
        return f"gs://{self._bucket_name}/{self._key(f'{dataset_name}.parquet')}"


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------
register_connector(
    "gcs",
    ConnectorSpec(
        connector_class=GCSConnector if _GCS_AVAILABLE else None,
        required_packages=["google.cloud.storage"],
        install_extra="gcs",
        can_read=True,
        can_write=True,
        description=(
            "Google Cloud Storage — reads/writes Parquet datasets in a GCS "
            "bucket. Requires: pip install eds-loader[gcs]"
        ),
    ),
)
