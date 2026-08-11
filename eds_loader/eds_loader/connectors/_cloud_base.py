"""Abstract base class for cloud object-storage connectors.

All shared read/write Parquet + ``schema.json`` logic lives here.
Concrete connectors (``s3.py``, ``azure_blob.py``, ``gcs.py``) override
four primitive I/O methods to supply cloud-specific file operations.

File layout in the bucket / container
--------------------------------------
::

    <prefix>/
    ├── schema.json
    ├── customers.parquet
    ├── orders.parquet
    └── products.parquet

The ``prefix`` config field (optional, default ``""``) scopes all files
under a path inside the bucket.  When non-empty it is normalised to end
with ``/`` so keys are always ``<prefix>/<filename>``.

Readable / Writable
-------------------
All cloud connectors implement **both** roles — they can act as a source
(reading Parquet files produced by EDS) and as a target (uploading processed
datasets back to the cloud).
"""

from __future__ import annotations

import abc
import io
import json
from typing import Any

import polars as pl

from eds_loader.connectors.base import WriteResult
from eds_loader.exceptions import LoadError

__all__ = ["CloudBaseConnector"]

_SCHEMA_FILE = "schema.json"


class CloudBaseConnector(abc.ABC):
    """Abstract base for cloud object-storage connectors.

    Subclasses must implement the four abstract primitive I/O methods.
    Everything else — listing, reading, writing Parquet and schema.json —
    is provided here.

    Args:
        prefix: Optional path prefix inside the bucket / container.
            Normalised to end with ``"/"`` when non-empty.
    """

    def __init__(self, prefix: str = "", **_kwargs: Any) -> None:
        # Normalise prefix: always ends with "/" when non-empty
        self._prefix: str = (prefix.rstrip("/") + "/") if prefix else ""
        self._cloud_client: Any = None  # lazily created by _get_client()

    # ------------------------------------------------------------------
    # Abstract — every cloud dialect must override
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def _connect(self) -> Any:
        """Create and return the cloud provider client object.

        Called once on first use; result is cached in ``_cloud_client``.
        """

    @abc.abstractmethod
    def _list_parquet_keys(self) -> list[str]:
        """Return all ``*.parquet`` object keys under the prefix.

        Keys are full paths relative to the bucket root (e.g.
        ``"prefix/customers.parquet"``).

        Raises:
            ~eds_loader.exceptions.LoadError: On list operation failure.
        """

    @abc.abstractmethod
    def _read_bytes(self, key: str) -> bytes:
        """Download the object at *key* and return its raw bytes.

        Raises:
            ~eds_loader.exceptions.LoadError: If the object does not exist
                or cannot be read.
        """

    @abc.abstractmethod
    def _write_bytes(self, key: str, data: bytes) -> None:
        """Upload *data* to the object at *key*.

        Raises:
            ~eds_loader.exceptions.LoadError: On upload failure.
        """

    @abc.abstractmethod
    def _location(self, dataset_name: str) -> str:
        """Return the full URL / URI for a dataset Parquet file.

        Examples:
            ``"s3://bucket/prefix/customers.parquet"``
            ``"gs://bucket/prefix/customers.parquet"``
        """

    # ------------------------------------------------------------------
    # Concrete helpers
    # ------------------------------------------------------------------

    def _key(self, filename: str) -> str:
        """Build a full object key: ``<prefix><filename>``."""
        return f"{self._prefix}{filename}"

    def _get_client(self) -> Any:
        """Return (or lazily create) the cached cloud client."""
        if self._cloud_client is None:
            self._cloud_client = self._connect()
        return self._cloud_client

    @staticmethod
    def _name_from_key(key: str) -> str:
        """Extract the dataset name from a full object key.

        ``"prefix/customers.parquet"`` → ``"customers"``
        ``"customers.parquet"``        → ``"customers"``
        """
        filename = key.rsplit("/", 1)[-1]
        return filename.removesuffix(".parquet")

    # ------------------------------------------------------------------
    # Readable interface
    # ------------------------------------------------------------------

    def read_schema_metadata(self) -> dict[str, Any]:
        """Download and parse ``schema.json`` from the prefix.

        Returns:
            Parsed schema metadata dict.

        Raises:
            ~eds_loader.exceptions.LoadError: If the file is absent,
                unreadable, or not valid JSON.
        """
        key = self._key(_SCHEMA_FILE)
        try:
            data = self._read_bytes(key)
            return json.loads(data.decode("utf-8"))
        except LoadError:
            raise
        except Exception as exc:
            raise LoadError(
                f"Cannot read {_SCHEMA_FILE} from {key!r}: {exc}"
            ) from exc

    def read_datasets(
        self,
        names: list[str] | None = None,
    ) -> dict[str, pl.DataFrame]:
        """Download and deserialise all ``*.parquet`` objects in the prefix.

        Args:
            names: Optional allow-list of dataset names to return.  When
                ``None`` or empty, all found datasets are returned.

        Returns:
            Dataset name → Polars DataFrame.

        Raises:
            ~eds_loader.exceptions.LoadError: On list or download failure.
        """
        try:
            keys = self._list_parquet_keys()
        except LoadError:
            raise
        except Exception as exc:
            raise LoadError(f"Cannot list Parquet files: {exc}") from exc

        name_filter: set[str] | None = set(names) if names else None

        datasets: dict[str, pl.DataFrame] = {}
        for key in keys:
            name = self._name_from_key(key)
            if name_filter is not None and name not in name_filter:
                continue
            try:
                data = self._read_bytes(key)
                datasets[name] = pl.read_parquet(io.BytesIO(data))
            except LoadError:
                raise
            except Exception as exc:
                raise LoadError(
                    f"Cannot read dataset {name!r} from {key!r}: {exc}"
                ) from exc

        return datasets

    # ------------------------------------------------------------------
    # Writable interface
    # ------------------------------------------------------------------

    def write_datasets(
        self,
        datasets: dict[str, pl.DataFrame],
        schema_metadata: dict[str, Any],
    ) -> list[WriteResult]:
        """Serialise datasets to Parquet and upload them to the bucket.

        Also uploads ``schema.json`` when *schema_metadata* is non-empty.

        Args:
            datasets: Dataset name → Polars DataFrame.
            schema_metadata: Parsed ``schema.json``.  Uploaded when
                non-empty.

        Returns:
            One :class:`~eds_loader.connectors.base.WriteResult` per
            dataset in *datasets* iteration order.

        Raises:
            ~eds_loader.exceptions.LoadError: On serialisation or upload
                failure.
        """
        results: list[WriteResult] = []

        for name, df in datasets.items():
            key = self._key(f"{name}.parquet")
            try:
                buf = io.BytesIO()
                df.write_parquet(buf)
                self._write_bytes(key, buf.getvalue())
            except LoadError:
                raise
            except Exception as exc:
                raise LoadError(
                    f"Cannot write dataset {name!r} to {key!r}: {exc}"
                ) from exc

            results.append(WriteResult(
                dataset=name,
                location=self._location(name),
                rows=df.height,
            ))

        if schema_metadata:
            schema_key = self._key(_SCHEMA_FILE)
            try:
                self._write_bytes(
                    schema_key,
                    json.dumps(schema_metadata, indent=2,
                               ensure_ascii=False).encode("utf-8"),
                )
            except LoadError:
                raise
            except Exception as exc:
                raise LoadError(
                    f"Cannot write {_SCHEMA_FILE} to {schema_key!r}: {exc}"
                ) from exc

        return results
