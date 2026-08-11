"""AWS S3 connector — source and target.

Reads and writes EDS Parquet datasets from/to an Amazon S3 bucket.

Inherits shared file I/O logic from
:class:`~eds_loader.connectors._cloud_base.CloudBaseConnector`.

Driver
------
:pypi:`boto3` (``pip install eds-loader[s3]``).

When boto3 is not installed, this module still imports cleanly and
registers the connector with ``connector_class=None``.

Auth
----
Pass credentials explicitly via ``aws_access_key_id`` +
``aws_secret_access_key`` / ``aws_secret_access_key_env``.
If no credentials are supplied, boto3 falls back to its normal
credential chain (environment variables, ``~/.aws/credentials``,
IAM instance role, etc.).

MinIO / LocalStack
------------------
Set ``endpoint_url`` to point the connector at a local S3-compatible
server for development and CI.
"""

from __future__ import annotations

import os
from typing import Any

from eds_loader.connectors._cloud_base import CloudBaseConnector
from eds_loader.connectors.registry import ConnectorSpec, register_connector
from eds_loader.exceptions import LoadError

__all__ = ["S3Connector"]

try:
    import boto3 as _boto3  # type: ignore[import]
    _BOTO3_AVAILABLE = True
except ImportError:
    _boto3 = None  # type: ignore[assignment]
    _BOTO3_AVAILABLE = False


class S3Connector(CloudBaseConnector):
    """Read / write EDS datasets in an Amazon S3 bucket.

    Implements both :class:`~eds_loader.connectors.base.Readable` and
    :class:`~eds_loader.connectors.base.Writable` via
    :class:`~eds_loader.connectors._cloud_base.CloudBaseConnector`.

    Config fields
    -------------
    ``bucket`` (required)
        S3 bucket name.
    ``prefix``
        Key prefix (acts as a directory).  Default: ``""`` (bucket root).
    ``aws_access_key_id``
        AWS access key ID.  Omit to use the boto3 credential chain.
    ``aws_secret_access_key`` / ``aws_secret_access_key_env``
        Secret access key inline or via env-var.
    ``region``
        AWS region (default: ``"us-east-1"``).
    ``endpoint_url``
        Custom endpoint URL for MinIO / LocalStack.

    Example config::

        source:
          kind: s3
          bucket: my-eds-bucket
          prefix: datasets/2024/
          aws_access_key_id: AKIAIOSFODNN7EXAMPLE
          aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY
          region: us-east-1
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_secret_access_key_env: str | None = None,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        **_kwargs: Any,
    ) -> None:
        super().__init__(prefix=prefix)
        self._bucket = bucket
        self._access_key_id = aws_access_key_id
        self._secret_access_key = aws_secret_access_key
        self._secret_access_key_env = aws_secret_access_key_env
        self._region = region
        self._endpoint_url = endpoint_url

    # ------------------------------------------------------------------
    # Credential resolution
    # ------------------------------------------------------------------

    def _resolve_secret_key(self) -> str | None:
        """Return the AWS secret access key, resolving env-var form."""
        if self._secret_access_key_env:
            val = os.environ.get(self._secret_access_key_env)
            if val is None:
                raise LoadError(
                    f"Environment variable {self._secret_access_key_env!r} "
                    "is not set."
                )
            return val
        return self._secret_access_key

    # ------------------------------------------------------------------
    # Abstract method overrides
    # ------------------------------------------------------------------

    def _connect(self) -> Any:
        """Create and return a :func:`boto3.client` for S3."""
        try:
            kwargs: dict[str, Any] = {"region_name": self._region}
            if self._access_key_id:
                kwargs["aws_access_key_id"] = self._access_key_id
                kwargs["aws_secret_access_key"] = self._resolve_secret_key() or ""
            if self._endpoint_url:
                kwargs["endpoint_url"] = self._endpoint_url
            return _boto3.client("s3", **kwargs)
        except LoadError:
            raise
        except Exception as exc:
            raise LoadError(f"Cannot create S3 client: {exc}") from exc

    def _list_parquet_keys(self) -> list[str]:
        """List all ``*.parquet`` keys in the bucket under the prefix."""
        client = self._get_client()
        try:
            paginator = client.get_paginator("list_objects_v2")
            keys: list[str] = []
            for page in paginator.paginate(
                Bucket=self._bucket, Prefix=self._prefix
            ):
                for obj in page.get("Contents", []):
                    if obj["Key"].endswith(".parquet"):
                        keys.append(obj["Key"])
            return keys
        except Exception as exc:
            raise LoadError(
                f"Cannot list s3://{self._bucket}/{self._prefix}: {exc}"
            ) from exc

    def _read_bytes(self, key: str) -> bytes:
        """Download one S3 object and return its raw bytes."""
        client = self._get_client()
        try:
            resp = client.get_object(Bucket=self._bucket, Key=key)
            return resp["Body"].read()
        except Exception as exc:
            raise LoadError(
                f"Cannot download s3://{self._bucket}/{key}: {exc}"
            ) from exc

    def _write_bytes(self, key: str, data: bytes) -> None:
        """Upload *data* to an S3 object at *key*."""
        client = self._get_client()
        try:
            client.put_object(Bucket=self._bucket, Key=key, Body=data)
        except Exception as exc:
            raise LoadError(
                f"Cannot upload to s3://{self._bucket}/{key}: {exc}"
            ) from exc

    def _location(self, dataset_name: str) -> str:
        return f"s3://{self._bucket}/{self._key(f'{dataset_name}.parquet')}"


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------
register_connector(
    "s3",
    ConnectorSpec(
        connector_class=S3Connector if _BOTO3_AVAILABLE else None,
        required_packages=["boto3"],
        install_extra="s3",
        can_read=True,
        can_write=True,
        description=(
            "AWS S3 — reads/writes Parquet datasets in an S3 bucket. "
            "Requires: pip install eds-loader[s3]"
        ),
    ),
)
