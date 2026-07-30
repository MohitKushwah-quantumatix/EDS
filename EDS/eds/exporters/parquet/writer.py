"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.adapters.parquet.writer`
instead.
"""

from __future__ import annotations

from eds.adapters.parquet.writer import (
    ExportError as ExportError,
)
from eds.adapters.parquet.writer import (
    write_dataset as write_dataset,
)
from eds.adapters.parquet.writer import (
    write_datasets as write_datasets,
)
