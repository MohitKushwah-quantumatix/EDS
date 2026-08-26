"""Append-only JSONL run log — persistent history of every loader run.

Each run appends one JSON line to ``<run_log_path>``.  The ``eds-loader
history`` command reads this file and renders a structured table.

File format
-----------
Each line is a standalone JSON object (JSON Lines / NDJSON):

.. code-block:: json

    {"timestamp": "2026-08-24T14:35:15+05:30", "config": "loader.yaml",
     "load_mode": "incremental", "status": "success", "duration_seconds": 1.9,
     "total_rows_affected": 2990, "datasets_changed": 1, "datasets_skipped": 2,
     "error": null}

The file is opened in append mode so concurrent writes from different
processes are as safe as the OS ``open(O_APPEND)`` guarantee (typically
atomic for small lines on POSIX; best-effort on Windows).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eds_loader._metrics import RunMetrics

__all__ = ["append_run_log", "read_run_log", "DEFAULT_LOG_NAME"]

DEFAULT_LOG_NAME = ".eds_loader_runs.jsonl"


def _summarise(metrics: RunMetrics) -> dict[str, Any]:
    """Reduce a RunMetrics to a compact log entry."""
    changed = sum(
        1 for d in metrics.datasets.values()
        if d.get("status") in ("written", "upserted")
    )
    skipped = sum(
        1 for d in metrics.datasets.values()
        if d.get("status") == "skipped"
    )
    return {
        "timestamp": metrics.finished_at or metrics.started_at,
        "config": metrics.config_file,
        "load_mode": metrics.load_mode,
        "status": metrics.status,
        "duration_seconds": metrics.duration_seconds,
        "total_rows_affected": metrics.total_rows_affected,
        "datasets_total": len(metrics.datasets),
        "datasets_changed": changed,
        "datasets_skipped": skipped,
        "error": metrics.error,
    }


def append_run_log(metrics: RunMetrics, log_path: Path) -> None:
    """Append one JSON line for *metrics* to *log_path*.

    Creates the file and any parent directories if they do not exist.
    Silently returns if the write fails — a run-log failure must never
    crash the actual loader.

    Args:
        metrics: The completed :class:`~eds_loader._metrics.RunMetrics`.
        log_path: Path to the JSONL history file.
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = json.dumps(_summarise(metrics), default=str)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(entry + "\n")
    except Exception:
        # Never let history-writing crash the run.
        pass


def read_run_log(log_path: Path, limit: int = 50) -> list[dict[str, Any]]:
    """Read the most recent *limit* entries from *log_path*.

    Args:
        log_path: Path to the JSONL history file.
        limit: Maximum number of entries to return (most recent first).

    Returns:
        List of dicts, most recent entry first.  Returns an empty list if
        the file does not exist or is unreadable.
    """
    if not log_path.is_file():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
        entries: list[dict[str, Any]] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(entries) >= limit:
                break
        return entries
    except OSError:
        return []
