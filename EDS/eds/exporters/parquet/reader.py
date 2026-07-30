"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.adapters.parquet.reader`
instead.
"""

from __future__ import annotations

from eds.adapters.parquet.reader import (
    DatasetNotFoundError as DatasetNotFoundError,
)
from eds.adapters.parquet.reader import (
    read_dataset as read_dataset,
)
from eds.adapters.parquet.reader import (
    read_datasets as read_datasets,
)
