"""Portable schema export for consumers outside the EDS process.

A ``Dataset`` (see :mod:`eds.core.schema`) is a Python object: primary key,
foreign keys, and column dtypes as :mod:`polars` types. That is fine for
code running inside EDS, but the Loader Tool (``eds_loader``, a separate
package with no dependency on EDS's own code -- see the requirements
document, FR-1 and FR-2) needs the same information without importing any
of it. This module writes that information as plain JSON, next to the
Parquet output, so a completely independent process can read it with the
standard library alone.

**One file across four generation stages.** ``eds generate`` runs in four
separate commands (master-data, customers, journey, commerce), each writing
its own subset of datasets. :func:`export_schema_json` merges into any
``schema.json`` already present rather than overwriting it, so the file
accumulates into a complete picture of every dataset generated so far,
however many separate commands produced them.

**Column types are named, not Polars objects.** ``_PORTABLE_TYPE_NAMES``
gives each dtype a short string ("int64", "string", ...) independent of any
Python library -- the same small vocabulary
:mod:`eds.adapters.postgres.schema_ddl` already maps into PostgreSQL types,
now available to a reader that has never imported Polars either.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import polars as pl

from eds.core.schema import Dataset

__all__ = ["SCHEMA_EXPORT_FILE", "export_schema_json"]

SCHEMA_EXPORT_FILE: Final[str] = "schema.json"

# The same dtypes eds.adapters.postgres.schema_ddl maps to PostgreSQL types,
# named portably here so a consumer needs no Polars import to read them.
_PORTABLE_TYPE_NAMES: dict[type, str] = {
    pl.Int64: "int64",
    pl.Float64: "float64",
    pl.Boolean: "boolean",
    pl.String: "string",
    pl.Date: "date",
    pl.Datetime: "datetime",
}


def _type_name(dtype: pl.DataType) -> str:
    """Portable name for a column's dtype, defaulting to ``"string"``."""
    return _PORTABLE_TYPE_NAMES.get(dtype.base_type(), "string")


def _dataset_to_dict(dataset: Dataset) -> dict:
    """Serialize one Dataset into the plain-JSON shape a reader expects."""
    return {
        "columns": {name: _type_name(dtype) for name, dtype in dataset.columns.items()},
        "primary_key": dataset.primary_key,
        "unique_columns": list(dataset.unique_columns),
        "foreign_keys": [
            {
                "column": fk.column,
                "references": fk.references,
                "referenced_column": fk.referenced_column,
                "nullable": fk.nullable,
            }
            for fk in dataset.foreign_keys
        ],
    }


def export_schema_json(datasets: Mapping[str, Dataset], path: Path, *, merge: bool = True) -> Path:
    """Write (or extend) a portable schema description as JSON.

    Args:
        datasets: Dataset name to declaration, for whatever subset was just
            generated -- not necessarily every dataset that will ever exist
            at ``path``.
        path: File to write, typically ``<output_directory>/schema.json``.
        merge: If ``True`` (the default) and ``path`` already holds valid
            JSON, its entries are loaded first and then updated with
            ``datasets`` -- so calling this once per generation stage builds
            up one complete file rather than each call discarding the last.
            If ``False``, ``path`` is always overwritten with only
            ``datasets``.

    Returns:
        ``path``, for chaining into a log message or a returned result.
    """
    existing: dict = {}
    if merge and path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    existing.update({name: _dataset_to_dict(dataset) for name, dataset in datasets.items()})

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
