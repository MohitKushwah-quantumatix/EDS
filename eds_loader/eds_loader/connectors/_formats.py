"""Format registry — maps a ``format`` name to its file extension(s) and reader.

All source connectors delegate to :func:`read_path` or :func:`read_bytes` so
that adding a new format only requires a change here, not in every connector.

Supported formats
-----------------
+----------+-----------------------+-------------------+------------------+
| Name     | Extension(s)          | Polars reader     | Extra dep        |
+==========+=======================+===================+==================+
| parquet  | .parquet              | read_parquet      | —                |
| csv      | .csv                  | read_csv          | —                |
| json     | .json                 | read_json         | —                |
| ndjson   | .ndjson / .jsonl      | read_ndjson       | —                |
| excel    | .xlsx / .xls          | read_excel        | openpyxl         |
| avro     | .avro                 | read_avro         | —                |
| orc      | .orc                  | read_orc          | —                |
+----------+-----------------------+-------------------+------------------+

Excel — multi-sheet behaviour
------------------------------
When an Excel file contains **more than one sheet**, each sheet is returned as
a separate dataset named ``<stem>_<sheet_name>`` (e.g. ``sales_Jan``,
``sales_Feb``).  Single-sheet workbooks use the bare stem (``sales``).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import polars as pl

from eds_loader.exceptions import LoadError

__all__ = [
    "FORMATS",
    "primary_extension",
    "all_extensions",
    "read_path",
    "read_bytes",
]

# ---------------------------------------------------------------------------
# Internal format table
# ---------------------------------------------------------------------------

#: (primary_extension, all_extensions) keyed by format name.
_FORMAT_META: dict[str, tuple[str, list[str]]] = {
    "parquet": (".parquet", [".parquet"]),
    "csv":     (".csv",     [".csv"]),
    "json":    (".json",    [".json"]),
    "ndjson":  (".ndjson",  [".ndjson", ".jsonl"]),
    "excel":   (".xlsx",    [".xlsx", ".xls"]),
    "avro":    (".avro",    [".avro"]),
    "orc":     (".orc",     [".orc"]),
}

#: All recognised format names.
FORMATS: frozenset[str] = frozenset(_FORMAT_META)


def _check_format(fmt: str) -> None:
    if fmt not in _FORMAT_META:
        known = ", ".join(sorted(_FORMAT_META))
        raise LoadError(f"Unknown format {fmt!r}. Known formats: {known}")


def primary_extension(fmt: str) -> str:
    """Return the primary file extension for *fmt* (e.g. ``\".parquet\"``)."""
    _check_format(fmt)
    return _FORMAT_META[fmt][0]


def all_extensions(fmt: str) -> list[str]:
    """Return all accepted file extensions for *fmt*."""
    _check_format(fmt)
    return list(_FORMAT_META[fmt][1])


# ---------------------------------------------------------------------------
# Excel helper — shared between path and bytes readers
# ---------------------------------------------------------------------------

def _check_excel_dep() -> None:
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:
        raise LoadError(
            "Excel format requires openpyxl. "
            "Install it with: pip install eds-loader[excel]"
        ) from exc


def _sheets_to_datasets(
    stem: str,
    sheets: dict[str, pl.DataFrame],
) -> dict[str, pl.DataFrame]:
    """Convert a sheet-name -> DataFrame dict to dataset-name -> DataFrame.

    Single-sheet workbooks: dataset name = file stem (e.g. ``"sales"``).
    Multi-sheet workbooks:  dataset name = ``"<stem>_<sheet>"`` (e.g. ``"sales_Jan"``).
    """
    if len(sheets) == 1:
        return {stem: next(iter(sheets.values()))}
    return {f"{stem}_{sheet}": df for sheet, df in sheets.items()}


# ---------------------------------------------------------------------------
# Public readers
# ---------------------------------------------------------------------------

def read_path(fmt: str, path: Path) -> dict[str, pl.DataFrame]:
    """Read one dataset file from a local *path*.

    Args:
        fmt:  Format name (``"parquet"``, ``"csv"``, etc.).
        path: Absolute or relative path to the file.

    Returns:
        ``{dataset_name: DataFrame}`` -- usually a single entry, but Excel
        multi-sheet files produce one entry per sheet.

    Raises:
        ~eds_loader.exceptions.LoadError: On format errors or read failures.
    """
    _check_format(fmt)
    stem = path.stem
    try:
        if fmt == "parquet":
            return {stem: pl.read_parquet(path)}
        if fmt == "csv":
            return {stem: pl.read_csv(path)}
        if fmt == "json":
            return {stem: pl.read_json(path)}
        if fmt == "ndjson":
            return {stem: pl.read_ndjson(path)}
        if fmt == "avro":
            return {stem: pl.read_avro(path)}
        if fmt == "orc":
            return {stem: pl.read_orc(path)}
        # excel
        _check_excel_dep()
        sheets: Any = pl.read_excel(path, sheet_name=None)
        return _sheets_to_datasets(stem, sheets)
    except LoadError:
        raise
    except Exception as exc:
        raise LoadError(
            f"Cannot read {fmt} file {path}: {exc}"
        ) from exc


def read_bytes(fmt: str, stem: str, data: bytes) -> dict[str, pl.DataFrame]:
    """Read one dataset from raw *data* bytes (cloud / remote use-case).

    Args:
        fmt:  Format name.
        stem: Dataset stem name (filename without extension).
        data: Raw file bytes.

    Returns:
        ``{dataset_name: DataFrame}`` -- same semantics as :func:`read_path`.

    Raises:
        ~eds_loader.exceptions.LoadError: On format errors or read failures.
    """
    _check_format(fmt)
    buf = io.BytesIO(data)
    try:
        if fmt == "parquet":
            return {stem: pl.read_parquet(buf)}
        if fmt == "csv":
            return {stem: pl.read_csv(buf)}
        if fmt == "json":
            return {stem: pl.read_json(buf)}
        if fmt == "ndjson":
            return {stem: pl.read_ndjson(buf)}
        if fmt == "avro":
            return {stem: pl.read_avro(buf)}
        if fmt == "orc":
            return {stem: pl.read_orc(buf)}
        # excel
        _check_excel_dep()
        sheets: Any = pl.read_excel(io.BytesIO(data), sheet_name=None)
        return _sheets_to_datasets(stem, sheets)
    except LoadError:
        raise
    except Exception as exc:
        raise LoadError(
            f"Cannot read {fmt} data for {stem!r}: {exc}"
        ) from exc
