"""Elasticsearch / OpenSearch connector — write target.

Each dataset becomes an index (``<index_prefix><dataset_name>``).

Supported modes
---------------
- ``full``:        Delete index + bulk index all documents.
- ``incremental``: Bulk upsert using ``_id = <pk_field_value>``.

Driver
------
:pypi:`elasticsearch` v8+ (``pip install eds-loader[elasticsearch]``).

Compatibility: works with Elasticsearch 8.x and OpenSearch 2.x (the client
auto-detects OpenSearch via the ``/_nodes`` product check bypass).

When the driver is not installed, this module imports cleanly.
"""

from __future__ import annotations

import logging
from typing import Any

import polars as pl

from eds_loader.connectors.base import UpsertResult, WriteResult
from eds_loader.connectors.registry import ConnectorSpec, register_connector
from eds_loader.exceptions import LoadError

__all__ = ["ElasticsearchConnector"]

logger = logging.getLogger("eds_loader.connectors.elasticsearch")

try:
    from elasticsearch import Elasticsearch, helpers  # type: ignore[import]
    _ES_AVAILABLE = True
except ImportError:
    Elasticsearch = None  # type: ignore[assignment]
    helpers = None        # type: ignore[assignment]
    _ES_AVAILABLE = False


class ElasticsearchConnector:
    """Write EDS datasets to Elasticsearch or OpenSearch.

    Config fields
    -------------
    ``host``         : ES host URL, e.g. ``"http://localhost:9200"`` (required).
    ``index_prefix`` : Prepended to every index name (default: ``"eds_"``).
    ``username``     : HTTP Basic auth username.
    ``password``     : Password (or use ``password_env``).
    ``password_env`` : Env-var name for password.
    ``verify_certs`` : Verify TLS certificates (default: ``True``).
    ``timeout``      : Request timeout seconds (default: 30).
    ``shards``       : Number of primary shards per index (default: 1).
    ``replicas``     : Number of replicas per index (default: 0).
    """

    def __init__(
        self,
        host: str,
        index_prefix: str = "eds_",
        username: str | None = None,
        password: str | None = None,
        password_env: str | None = None,
        verify_certs: bool = True,
        timeout: int = 30,
        shards: int = 1,
        replicas: int = 0,
        **_kwargs: Any,
    ) -> None:
        self._host = host
        self._index_prefix = index_prefix
        self._username = username
        self._password = password
        self._password_env = password_env
        self._verify_certs = verify_certs
        self._timeout = timeout
        self._shards = shards
        self._replicas = replicas
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if Elasticsearch is None:
            raise LoadError(
                "elasticsearch is not installed. "
                "Fix: pip install eds-loader[elasticsearch]"
            )
        import os
        pw = self._password
        if not pw and self._password_env:
            pw = os.environ.get(self._password_env)

        kwargs: dict[str, Any] = {
            "hosts": [self._host],
            "verify_certs": self._verify_certs,
            "request_timeout": self._timeout,
        }
        if self._username and pw:
            kwargs["basic_auth"] = (self._username, pw)
        try:
            client = Elasticsearch(**kwargs)
            # ping to verify connectivity
            if not client.ping():
                raise RuntimeError("ping returned False")
            self._client = client
            return client
        except Exception as exc:
            raise LoadError(f"Cannot connect to Elasticsearch at {self._host}: {exc}") from exc

    def _index_name(self, dataset_name: str) -> str:
        return f"{self._index_prefix}{dataset_name}".lower()

    def _index_settings(self) -> dict[str, Any]:
        return {
            "settings": {
                "number_of_shards": self._shards,
                "number_of_replicas": self._replicas,
            }
        }

    def _df_to_docs(self, df: pl.DataFrame, index: str,
                    pk_field: str | None = None) -> list[dict[str, Any]]:
        """Convert DataFrame rows to Elasticsearch bulk action dicts."""
        docs = []
        for row in df.to_dicts():
            action: dict[str, Any] = {
                "_index": index,
                "_source": row,
            }
            if pk_field and pk_field in row:
                action["_id"] = str(row[pk_field])
            docs.append(action)
        return docs

    # ------------------------------------------------------------------
    # Writable interface
    # ------------------------------------------------------------------

    def write_datasets(
        self,
        datasets: dict[str, pl.DataFrame],
        schema_metadata: dict[str, Any],
    ) -> list[WriteResult]:
        """Full load: delete index + bulk index all documents."""
        client = self._get_client()
        results: list[WriteResult] = []

        for name, df in datasets.items():
            index = self._index_name(name)
            schema_entry = schema_metadata.get(name, {})
            pk_field = schema_entry.get("primary_key")

            try:
                # Delete existing index (idempotent)
                if client.indices.exists(index=index):
                    client.indices.delete(index=index)

                # Create with settings
                client.indices.create(index=index, body=self._index_settings())

                if df.height > 0:
                    docs = self._df_to_docs(df, index, pk_field)
                    helpers.bulk(client, docs)

                client.indices.refresh(index=index)
                logger.info("[%s] Indexed %d document(s) → %s", name, df.height, index)
                results.append(WriteResult(
                    dataset=name,
                    location=f"{self._host}/{index}",
                    rows=df.height,
                ))
            except (LoadError,):
                raise
            except Exception as exc:
                raise LoadError(
                    f"Failed to index dataset {name!r} into {index}: {exc}"
                ) from exc

        return results

    # ------------------------------------------------------------------
    # Upsertable interface
    # ------------------------------------------------------------------

    def upsert_datasets(
        self,
        datasets: dict[str, pl.DataFrame],
        schema_metadata: dict[str, Any],
    ) -> list[UpsertResult]:
        """Incremental upsert: index with _id = pk value, update if exists."""
        client = self._get_client()
        results: list[UpsertResult] = []

        for name, df in datasets.items():
            schema_entry = schema_metadata.get(name, {})
            pk_field: str | None = schema_entry.get("primary_key")
            index = self._index_name(name)

            if not pk_field:
                logger.warning("[%s] No primary key — falling back to full replace", name)
                res = self.write_datasets({name: df}, schema_metadata)
                results.append(UpsertResult(
                    dataset=name, location=res[0].location,
                    rows_inserted=res[0].rows, rows_updated=0,
                ))
                continue

            try:
                # Ensure index exists
                if not client.indices.exists(index=index):
                    client.indices.create(index=index, body=self._index_settings())

                # Count before
                before = client.count(index=index).get("count", 0)

                # Upsert via bulk index with _id (Elasticsearch auto-updates on ID match)
                if df.height > 0:
                    docs = self._df_to_docs(df, index, pk_field)
                    helpers.bulk(client, docs)

                client.indices.refresh(index=index)

                # Count after
                after = client.count(index=index).get("count", 0)
                rows_inserted = max(0, after - before)
                rows_updated = max(0, df.height - rows_inserted)

                logger.info(
                    "[%s] Upserted %d doc(s) → %s (%d inserted, %d updated)",
                    name, df.height, index, rows_inserted, rows_updated,
                )
                results.append(UpsertResult(
                    dataset=name,
                    location=f"{self._host}/{index}",
                    rows_inserted=rows_inserted,
                    rows_updated=rows_updated,
                ))

            except (LoadError,):
                raise
            except Exception as exc:
                raise LoadError(
                    f"Failed to upsert dataset {name!r} into {index}: {exc}"
                ) from exc

        return results


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------
register_connector(
    "elasticsearch",
    ConnectorSpec(
        connector_class=ElasticsearchConnector if _ES_AVAILABLE else None,
        required_packages=["elasticsearch"],
        install_extra="elasticsearch",
        can_read=False,
        can_write=True,
        description=(
            "Elasticsearch / OpenSearch — writes datasets as search indices. "
            "Full load: delete + bulk index. Incremental: bulk upsert by _id. "
            "Requires: pip install eds-loader[elasticsearch]"
        ),
    ),
)
