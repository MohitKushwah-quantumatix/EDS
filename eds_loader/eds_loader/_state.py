"""State management for incremental loads.

Tracks the hash and stats of each dataset after a successful run so that
the next run can detect what changed and skip unchanged datasets.

The state is persisted as a human-readable JSON file (typically
``.eds_loader_state.json``) written next to the config file.

File format example::

    {
      "version": 1,
      "config_file": "loader.yaml",
      "last_run": "2026-08-24T14:35:15+05:30",
      "mode": "incremental",
      "datasets": {
        "customers": {
          "source_hash": "sha256:abc123...",
          "rows_at_source": 12500,
          "rows_inserted": 0,
          "rows_updated": 0,
          "skipped": true,
          "last_changed": "2026-08-23T02:00:00+05:30"
        },
        "orders": {
          "source_hash": "sha256:9ef789...",
          "rows_at_source": 47200,
          "rows_inserted": 2100,
          "rows_updated": 890,
          "skipped": false,
          "last_changed": "2026-08-24T14:35:15+05:30"
        }
      }
    }

The state file is **config-specific** — each loader.yaml gets its own state
file so multiple configs running in parallel don't interfere.

If the state file is corrupted or missing, a fresh full load is performed
automatically and a new state file is written on success.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from eds_loader.exceptions import LoadError

__all__ = [
    "DatasetState",
    "RunState",
    "load_state",
    "save_state",
    "file_sha256",
    "bytes_sha256",
    "dataframe_hash",
    "schema_fingerprint",
]


@dataclass
class DatasetState:
    """State record for one dataset from the previous run.

    Attributes:
        source_hash: SHA-256 hex digest of the source data, prefixed with
            ``"sha256:"``.  Used to detect whether the source changed.
        rows_at_source: Number of rows in the source dataset on the last run.
        rows_inserted: Net new rows inserted into the target on the last run.
            Zero for skipped datasets.
        rows_updated: Rows updated in the target on the last run.
            Zero for skipped datasets.
        skipped: ``True`` if the dataset was skipped (no change detected).
        last_changed: ISO-8601 timestamp of the run that last wrote changes
            for this dataset.
    """

    source_hash: str
    rows_at_source: int
    rows_inserted: int
    rows_updated: int
    skipped: bool
    last_changed: str
    schema_fingerprint: dict[str, str] = field(default_factory=dict)


@dataclass
class RunState:
    """Full state from the last incremental run.

    Attributes:
        version: Schema version — always ``1`` for now.
        config_file: Basename of the config file this state belongs to.
        last_run: ISO-8601 timestamp of the last run (success or partial).
        mode: Always ``"incremental"`` for state files written by this module.
        datasets: Dataset name → :class:`DatasetState`.
    """

    version: int = 1
    config_file: str = ""
    last_run: str = ""
    mode: str = "incremental"
    datasets: dict[str, DatasetState] = field(default_factory=dict)


def load_state(state_path: Path) -> RunState | None:
    """Load state from a JSON file.

    Args:
        state_path: Path to the state file.

    Returns:
        A :class:`RunState` if the file exists and is valid JSON, otherwise
        ``None`` (which the loader treats as a first run → full load).
    """
    if not state_path.is_file():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        datasets: dict[str, DatasetState] = {}
        for name, ds_data in data.get("datasets", {}).items():
            try:
                datasets[name] = DatasetState(
                    source_hash=ds_data.get("source_hash", ""),
                    rows_at_source=int(ds_data.get("rows_at_source", 0)),
                    rows_inserted=int(ds_data.get("rows_inserted", 0)),
                    rows_updated=int(ds_data.get("rows_updated", 0)),
                    skipped=bool(ds_data.get("skipped", False)),
                    last_changed=ds_data.get("last_changed", ""),
                    schema_fingerprint=ds_data.get("schema_fingerprint", {}),
                )
            except (TypeError, ValueError):
                # Corrupted dataset entry — skip it (treat as unseen).
                continue
        return RunState(
            version=int(data.get("version", 1)),
            config_file=str(data.get("config_file", "")),
            last_run=str(data.get("last_run", "")),
            mode=str(data.get("mode", "incremental")),
            datasets=datasets,
        )
    except Exception:
        # Corrupted state file — treat as first run.
        return None


def save_state(state_path: Path, state: RunState) -> None:
    """Write state to a JSON file atomically.

    The file is written to a ``.tmp`` sibling and then renamed so a
    concurrent crash cannot leave a half-written state file.

    Args:
        state_path: Destination path.
        state: State to persist.

    Raises:
        ~eds_loader.exceptions.LoadError: If the file cannot be written.
    """
    data: dict = {
        "version": state.version,
        "config_file": state.config_file,
        "last_run": state.last_run,
        "mode": state.mode,
        "datasets": {
            name: {
                "source_hash": ds.source_hash,
                "rows_at_source": ds.rows_at_source,
                "rows_inserted": ds.rows_inserted,
                "rows_updated": ds.rows_updated,
                "skipped": ds.skipped,
                "last_changed": ds.last_changed,
                "schema_fingerprint": ds.schema_fingerprint,
            }
            for name, ds in state.datasets.items()
        },
    }
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp_path = state_path.with_suffix(".tmp")
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(state_path)
    except OSError as exc:
        raise LoadError(
            f"Cannot write state file {state_path}: {exc}"
        ) from exc


def file_sha256(path: Path) -> str:
    """Compute a SHA-256 hash of a file on disk.

    Reads in 64 KiB chunks to stay memory-efficient for large Parquet files.

    Args:
        path: Path to the file.

    Returns:
        A string of the form ``"sha256:<hex-digest>"``.

    Raises:
        ~eds_loader.exceptions.LoadError: If the file cannot be read.
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65_536), b""):
                h.update(chunk)
    except OSError as exc:
        raise LoadError(f"Cannot hash file {path}: {exc}") from exc
    return f"sha256:{h.hexdigest()}"


def bytes_sha256(data: bytes) -> str:
    """Compute a SHA-256 hash of an in-memory byte string.

    Used by cloud and SSH connectors that download file bytes directly.

    Args:
        data: Raw file bytes.

    Returns:
        A string of the form ``"sha256:<hex-digest>"``.
    """
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def dataframe_hash(df: pl.DataFrame) -> str:
    """Compute a SHA-256 hash of a Polars DataFrame's content.

    Serialises the DataFrame to uncompressed Parquet bytes in memory and
    hashes those bytes.  This is stable across Python sessions and works
    for DataFrames read from any source connector (local, cloud, SSH).

    Args:
        df: The DataFrame to hash.

    Returns:
        A string of the form ``"sha256:<hex-digest>"``.
    """
    buf = io.BytesIO()
    df.write_parquet(buf, compression="uncompressed")
    return f"sha256:{hashlib.sha256(buf.getvalue()).hexdigest()}"


def schema_fingerprint(df: pl.DataFrame) -> dict[str, str]:
    """Return a ``{column: dtype_string}`` fingerprint of *df*'s schema.

    Stored in the state file so that schema drift can be detected on the
    next run by :func:`~eds_loader._schema_drift.detect_drift`.

    Args:
        df: The DataFrame whose schema to fingerprint.

    Returns:
        Dict mapping column name to Polars dtype string, e.g.
        ``{"id": "Int64", "name": "String", "created_at": "Datetime"}}``.
    """
    return {name: str(dtype) for name, dtype in df.schema.items()}
