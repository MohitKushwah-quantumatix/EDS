"""The output adapter extension point.

An adapter is the only component that knows how generated data is persisted.
Under PADR-003 no business generator may import an adapter and no adapter may
import a generator; they meet only at :class:`polars.DataFrame` and at the
protocols here.

**Why the destination is not a call argument.** P001 declared
``write(datasets, destination: Path)``. That signature is a file system leaking
into the contract: a SQL adapter has a connection and a schema, a Kafka adapter
has brokers and a topic, a REST adapter has a base URL and credentials. None of
them is a ``Path``, and none of them can be expressed as one. The same applied
to the return type, ``tuple[Path, ...]``, which is meaningless for a table or a
topic.

So the destination is now bound when the adapter is *constructed*, exactly as a
database connection is, and the call says only what the caller means: persist
these named datasets. What comes back is a :class:`WriteResult` per dataset -
what was written, where it landed as an opaque identifier, and how many rows -
which every conceivable adapter can answer honestly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import polars as pl

__all__ = ["AdapterError", "DatasetReader", "DatasetWriter", "WriteResult"]


class AdapterError(RuntimeError):
    """Base class for adapter failures.

    Concrete adapters raise their own subclasses, so a caller can catch either
    one specific failure or anything an adapter can go wrong with, without
    importing a storage-specific exception type.
    """


@dataclass(frozen=True, slots=True)
class WriteResult:
    """What one dataset became when it was persisted.

    Attributes:
        dataset: The dataset name that was written.
        location: Where it landed, as an identifier meaningful to the adapter -
            a file path, a qualified table name, a topic. Deliberately a string
            rather than a :class:`~pathlib.Path`, because most targets are not
            files.
        rows: How many rows were written.
    """

    dataset: str
    location: str
    rows: int

    def __post_init__(self) -> None:
        """Reject a result that could not be traced back to what was written.

        Raises:
            ValueError: If the dataset or location is empty, or the row count
                is negative.
        """
        if not self.dataset.strip():
            raise ValueError("a write result must name its dataset")
        if not self.location.strip():
            raise ValueError(f"write result for {self.dataset!r} must record a location")
        if self.rows < 0:
            raise ValueError(f"write result for {self.dataset!r} cannot have negative rows")


@runtime_checkable
class DatasetWriter(Protocol):
    """Persists generated datasets to wherever the adapter was pointed.

    Implementations must be deterministic for a given input: writing the same
    frames twice produces the same result. That is what lets the CLI's
    determinism tests compare two runs byte for byte.
    """

    @property
    def name(self) -> str:
        """Return the adapter's registry name, such as ``"parquet"``."""
        ...

    def write(self, datasets: Mapping[str, pl.DataFrame]) -> tuple[WriteResult, ...]:
        """Persist every dataset.

        Args:
            datasets: Dataset name to frame.

        Returns:
            One result per dataset, in the order the datasets were given.

        Raises:
            AdapterError: If any dataset cannot be written.
        """
        ...


@runtime_checkable
class DatasetReader(Protocol):
    """Reads previously persisted datasets back.

    Each feature reads what earlier features wrote rather than regenerating it,
    so this is on the critical path of every command after the first.
    """

    @property
    def name(self) -> str:
        """Return the adapter's registry name, such as ``"parquet"``."""
        ...

    def read(self, names: Iterable[str]) -> dict[str, pl.DataFrame]:
        """Read the named datasets.

        Args:
            names: Dataset names to read.

        Returns:
            Dataset name to frame.

        Raises:
            AdapterError: If any dataset is missing or unreadable.
        """
        ...
