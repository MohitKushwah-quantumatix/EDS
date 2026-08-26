"""Google BigQuery connector — write target.

Writes EDS datasets to BigQuery tables using the ``google-cloud-bigquery``
client library.

Supported modes
---------------
- ``full``:        Truncate the table then load all rows (``WRITE_TRUNCATE``).
- ``incremental``: Upsert via a ``MERGE`` DML statement using the dataset's
                   primary key from ``schema.json``.

Driver
------
:pypi:`google-cloud-bigquery` (``pip install eds-loader[bigquery]``).

When the driver is not installed, this module still imports cleanly.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import polars as pl

from eds_loader.connectors.base import UpsertResult, WriteResult
from eds_loader.connectors.registry import ConnectorSpec, register_connector
from eds_loader.exceptions import LoadError

__all__ = ["BigQueryConnector"]

logger = logging.getLogger("eds_loader.connectors.bigquery")

try:
    from google.cloud import bigquery as _bq  # type: ignore[import]
    from google.oauth2 import service_account  # type: ignore[import]
    _BQ_AVAILABLE = True
except ImportError:
    _bq = None  # type: ignore[assignment]
    service_account = None  # type: ignore[assignment]
    _BQ_AVAILABLE = False

# ---------------------------------------------------------------------------
# Type map
# ---------------------------------------------------------------------------
_BQ_TYPE_MAP: dict[str, str] = {
    "Int8": "INT64",   "Int16": "INT64",   "Int32": "INT64",   "Int64": "INT64",
    "UInt8": "INT64",  "UInt16": "INT64",  "UInt32": "INT64",  "UInt64": "NUMERIC",
    "Float32": "FLOAT64", "Float64": "FLOAT64",
    "String": "STRING", "Utf8": "STRING",
    "Boolean": "BOOL",
    "Date": "DATE",
    "Datetime": "DATETIME",
    "List": "JSON",
    "Struct": "JSON",
}


class BigQueryConnector:
    """Write EDS datasets to Google BigQuery.

    Config fields
    -------------
    ``project``           : GCP project ID (required).
    ``dataset``           : BigQuery dataset name (required).
    ``credentials_file``  : Path to a service-account JSON key file.
                            When omitted, Application Default Credentials are used.
    ``location``          : BQ dataset location (default: ``"US"``).
    ``create_dataset``    : Create the BQ dataset if it does not exist (default: ``True``).
    """

    def __init__(
        self,
        project: str,
        dataset: str,
        credentials_file: str | None = None,
        location: str = "US",
        create_dataset: bool = True,
        **_kwargs: Any,
    ) -> None:
        self._project = project
        self._dataset = dataset
        self._credentials_file = credentials_file
        self._location = location
        self._create_dataset = create_dataset
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if _bq is None:
            raise LoadError(
                "google-cloud-bigquery is not installed. "
                "Fix: pip install eds-loader[bigquery]"
            )
        try:
            if self._credentials_file:
                creds = service_account.Credentials.from_service_account_file(
                    self._credentials_file,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                self._client = _bq.Client(project=self._project, credentials=creds)
            else:
                self._client = _bq.Client(project=self._project)
            return self._client
        except Exception as exc:
            raise LoadError(f"Cannot initialise BigQuery client: {exc}") from exc

    def _ensure_dataset(self, client: Any) -> None:
        if not self._create_dataset:
            return
        dataset_ref = _bq.Dataset(f"{self._project}.{self._dataset}")
        dataset_ref.location = self._location
        try:
            client.create_dataset(dataset_ref, exists_ok=True)
        except Exception as exc:
            raise LoadError(f"Cannot create BigQuery dataset {self._dataset}: {exc}") from exc

    def _table_id(self, name: str) -> str:
        return f"{self._project}.{self._dataset}.{name}"

    def _polars_to_bq_schema(self, df: pl.DataFrame) -> list[Any]:
        """Convert Polars schema to BigQuery field schema list."""
        fields = []
        for col, dtype in df.schema.items():
            bq_type = _BQ_TYPE_MAP.get(str(dtype), "STRING")
            fields.append(_bq.SchemaField(col, bq_type, mode="NULLABLE"))
        return fields

    def _df_to_parquet_bytes(self, df: pl.DataFrame) -> bytes:
        buf = io.BytesIO()
        df.write_parquet(buf)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Writable interface
    # ------------------------------------------------------------------

    def write_datasets(
        self,
        datasets: dict[str, pl.DataFrame],
        schema_metadata: dict[str, Any],
    ) -> list[WriteResult]:
        """Full load: truncate + insert each dataset."""
        client = self._get_client()
        self._ensure_dataset(client)
        results: list[WriteResult] = []

        for name, df in datasets.items():
            table_id = self._table_id(name)
            bq_schema = self._polars_to_bq_schema(df)
            job_config = _bq.LoadJobConfig(
                schema=bq_schema,
                write_disposition=_bq.WriteDisposition.WRITE_TRUNCATE,
                source_format=_bq.SourceFormat.PARQUET,
            )
            try:
                data = self._df_to_parquet_bytes(df)
                job = client.load_table_from_file(
                    io.BytesIO(data), table_id, job_config=job_config
                )
                job.result()  # wait for completion
                logger.info("[%s] Loaded %d row(s) to BigQuery %s", name, df.height, table_id)
                results.append(WriteResult(
                    dataset=name,
                    location=f"bq://{self._project}/{self._dataset}/{name}",
                    rows=df.height,
                ))
            except Exception as exc:
                raise LoadError(
                    f"Failed to write dataset {name!r} to BigQuery {table_id}: {exc}"
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
        """Incremental load: MERGE via a temporary staging table."""
        client = self._get_client()
        self._ensure_dataset(client)
        results: list[UpsertResult] = []

        for name, df in datasets.items():
            schema_entry = schema_metadata.get(name, {})
            pk_col: str | None = schema_entry.get("primary_key")

            if not pk_col:
                logger.warning("[%s] No primary key — falling back to full replace", name)
                res = self.write_datasets({name: df}, schema_metadata)
                results.append(UpsertResult(
                    dataset=name,
                    location=res[0].location,
                    rows_inserted=res[0].rows,
                    rows_updated=0,
                ))
                continue

            table_id = self._table_id(name)
            staging_id = self._table_id(f"_stage_{name}")
            bq_schema = self._polars_to_bq_schema(df)

            try:
                # 1. Load into staging table (WRITE_TRUNCATE)
                job_config = _bq.LoadJobConfig(
                    schema=bq_schema,
                    write_disposition=_bq.WriteDisposition.WRITE_TRUNCATE,
                    source_format=_bq.SourceFormat.PARQUET,
                )
                data = self._df_to_parquet_bytes(df)
                job = client.load_table_from_file(
                    io.BytesIO(data), staging_id, job_config=job_config
                )
                job.result()

                # 2. Ensure target table exists
                client.create_table(_bq.Table(table_id, schema=bq_schema), exists_ok=True)

                # 3. MERGE staging → target
                cols = df.columns
                non_pk = [c for c in cols if c != pk_col]
                set_clause = ", ".join(f"T.`{c}` = S.`{c}`" for c in non_pk)
                ins_cols = ", ".join(f"`{c}`" for c in cols)
                ins_vals = ", ".join(f"S.`{c}`" for c in cols)
                merge_sql = f"""
                    MERGE `{table_id}` T
                    USING `{staging_id}` S
                    ON T.`{pk_col}` = S.`{pk_col}`
                    {"WHEN MATCHED THEN UPDATE SET " + set_clause if non_pk else ""}
                    WHEN NOT MATCHED THEN INSERT ({ins_cols}) VALUES ({ins_vals})
                """
                job = client.query(merge_sql)
                job.result()

                stats = job.dml_stats
                rows_inserted = getattr(stats, "inserted_row_count", df.height)
                rows_updated = getattr(stats, "updated_row_count", 0)

                # 4. Drop staging table
                client.delete_table(staging_id, not_found_ok=True)

                logger.info(
                    "[%s] Upserted to BigQuery: %d inserted, %d updated",
                    name, rows_inserted, rows_updated,
                )
                results.append(UpsertResult(
                    dataset=name,
                    location=f"bq://{self._project}/{self._dataset}/{name}",
                    rows_inserted=rows_inserted,
                    rows_updated=rows_updated,
                ))

            except Exception as exc:
                client.delete_table(staging_id, not_found_ok=True)
                raise LoadError(
                    f"Failed to upsert dataset {name!r} to BigQuery {table_id}: {exc}"
                ) from exc

        return results


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------
register_connector(
    "bigquery",
    ConnectorSpec(
        connector_class=BigQueryConnector if _BQ_AVAILABLE else None,
        required_packages=["google.cloud.bigquery"],
        install_extra="bigquery",
        can_read=False,
        can_write=True,
        description=(
            "Google BigQuery — writes datasets as BQ tables. "
            "Full load via WRITE_TRUNCATE; incremental via MERGE DML. "
            "Requires: pip install eds-loader[bigquery]"
        ),
    ),
)
