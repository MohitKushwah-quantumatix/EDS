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

__all__ = ["Readable", "Writable", "WriteResult"]


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
