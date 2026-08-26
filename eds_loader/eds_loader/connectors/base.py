"""Base protocols and result types shared by all eds_loader connectors.

Every connector — local filesystem, SSH/SFTP, S3, Azure Blob, GCS,
PostgreSQL, MongoDB — implements one or both protocols here:

- :class:`Readable` — the connector can act as a **source**: it reads
  Parquet datasets and the ``schema.json`` written alongside them.
- :class:`Writable` — the connector can act as a **target**: it receives
  DataFrames and schema metadata and persists them.

Both protocols are :pep:`544` structural protocols (``@runtime_checkable``),
so a connector need not inherit from anything — structural conformance is
enough.  The same connector class can implement both (e.g. local filesystem
or S3 can be either a source or a target), or just one (e.g. a write-only
audit log target).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import polars as pl

__all__ = ["Readable", "Writable", "Upsertable", "WriteResult", "UpsertResult"]


@dataclass(frozen=True, slots=True)
class WriteResult:
    """What one dataset became when it was persisted to the target.

    Attributes:
        dataset: The dataset name that was written (e.g. ``"orders"``).
        location: Where it landed — a file path, qualified table name,
            object storage key, or any opaque identifier meaningful to the
            connector.  Always a string so every connector can answer.
        rows: Number of rows written.
    """

    dataset: str
    location: str
    rows: int

    def __post_init__(self) -> None:
        if not self.dataset.strip():
            raise ValueError("WriteResult must name its dataset")
        if not self.location.strip():
            raise ValueError(f"WriteResult for {self.dataset!r} must record a location")
        if self.rows < 0:
            raise ValueError(f"WriteResult for {self.dataset!r} cannot have negative rows")


@dataclass(frozen=True, slots=True)
class UpsertResult:
    """What one dataset became after an incremental upsert to the target.

    Attributes:
        dataset: The dataset name that was upserted (e.g. ``"orders"``).
        location: Where it landed — same semantics as :attr:`WriteResult.location`.
        rows_inserted: Net new rows that did not previously exist in the target.
        rows_updated: Rows that already existed and were updated with new values.
    """

    dataset: str
    location: str
    rows_inserted: int
    rows_updated: int

    @property
    def rows(self) -> int:
        """Total rows affected (inserted + updated)."""
        return self.rows_inserted + self.rows_updated

    def __post_init__(self) -> None:
        if not self.dataset.strip():
            raise ValueError("UpsertResult must name its dataset")
        if not self.location.strip():
            raise ValueError(f"UpsertResult for {self.dataset!r} must record a location")
        if self.rows_inserted < 0 or self.rows_updated < 0:
            raise ValueError(f"UpsertResult for {self.dataset!r} cannot have negative row counts")


@runtime_checkable
class Readable(Protocol):
    """A connector that can serve as a data **source**.

    Implementations must be able to:

    1. Return the schema metadata from ``schema.json`` so the loader
       knows which columns are primary keys, foreign keys, and unique.
    2. Return one or more named datasets as Polars DataFrames.

    Connector classes satisfy this protocol structurally — no inheritance
    required.
    """

    def read_schema_metadata(self) -> dict[str, Any]:
        """Return the full contents of ``schema.json`` as a plain dict.

        The returned dict maps dataset name to its schema entry::

            {
              "customers": {
                "columns": {"customer_id": "int64", ...},
                "primary_key": "customer_id",
                "unique_columns": ["email"],
                "foreign_keys": [...]
              },
              ...
            }

        Returns:
            Schema metadata for every dataset available at this source.

        Raises:
            ~eds_loader.exceptions.LoadError: If ``schema.json`` is missing
                or cannot be parsed.
        """
        ...

    def read_datasets(
        self,
        names: list[str] | None = None,
    ) -> dict[str, pl.DataFrame]:
        """Read datasets from this source.

        Args:
            names: Dataset names to read.  ``None`` means read every
                dataset available at the source.

        Returns:
            Dict mapping dataset name to its Polars DataFrame.

        Raises:
            ~eds_loader.exceptions.LoadError: If any requested dataset is
                missing or cannot be read.
        """
        ...


@runtime_checkable
class Writable(Protocol):
    """A connector that can serve as a data **target**.

    Implementations receive DataFrames and schema metadata and persist them
    in whatever form the target supports (Parquet files, database tables,
    object storage blobs, etc.).

    Connector classes satisfy this protocol structurally — no inheritance
    required.
    """

    def write_datasets(
        self,
        datasets: dict[str, pl.DataFrame],
        schema_metadata: dict[str, Any],
    ) -> list[WriteResult]:
        """Write datasets to this target.

        Args:
            datasets: Dataset name to Polars DataFrame.
            schema_metadata: Parsed ``schema.json`` contents for the
                datasets being written.  SQL-family connectors use this to
                enforce primary key / foreign key / unique constraints.
                Pass an empty dict to skip constraint enforcement.

        Returns:
            One :class:`WriteResult` per dataset written, in write order.

        Raises:
            ~eds_loader.exceptions.LoadError: If any dataset cannot be
                written (I/O error, constraint violation, etc.).
        """
        ...


@runtime_checkable
class Upsertable(Protocol):
    """A connector that supports incremental upsert into an existing target.

    Connectors that implement this protocol can be used as targets in
    ``load_mode: incremental`` runs.  Instead of dropping and recreating
    tables/collections, they merge new data with existing data using
    primary-key-based ``INSERT ... ON CONFLICT`` / ``MERGE`` / ``replace_one``
    semantics.

    Connector classes satisfy this protocol structurally — no inheritance
    required.
    """

    def upsert_datasets(
        self,
        datasets: dict[str, pl.DataFrame],
        schema_metadata: dict[str, Any],
    ) -> list[UpsertResult]:
        """Upsert datasets into this target, merging with existing data.

        For each dataset the connector must:

        1. Ensure the target table / collection exists (create if missing).
        2. For each row, ``INSERT`` if the primary key is new, ``UPDATE``
           if it already exists.
        3. Return one :class:`UpsertResult` per dataset with counts of
           inserted vs updated rows.

        Datasets without a primary key (empty ``schema_metadata`` or no
        ``primary_key`` field) **must** fall back to a full replace for that
        dataset and log a warning — they must not raise.

        Args:
            datasets: Dataset name → Polars DataFrame with the latest source
                data for that dataset.
            schema_metadata: Parsed ``schema.json`` contents.  Used to
                obtain the primary key column name per dataset.

        Returns:
            One :class:`UpsertResult` per dataset in *datasets* iteration order.

        Raises:
            ~eds_loader.exceptions.LoadError: If any dataset cannot be
                upserted (connection error, constraint violation, etc.).
        """
        ...
