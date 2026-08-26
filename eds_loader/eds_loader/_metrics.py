"""Run metrics — write a machine-readable JSON snapshot after every load run.

Every successful or failed run produces a ``run_metrics.json`` file (or
appends to a JSONL run log — see :mod:`eds_loader._run_log`).

The metrics file is suitable for:
- Grafana / Prometheus scraping
- CI pipeline assertions (``assert metrics["status"] == "success"``)
- Quick shell inspection (``cat run_metrics.json | python -m json.tool``)

The file is written atomically (``<path>.tmp`` → rename) so a concurrent
reader never sees a partial write.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any

__all__ = ["RunMetrics", "write_metrics"]


class RunMetrics:
    """Captures all statistics for one loader run.

    Attributes:
        config_file: Path to the config YAML that drove this run.
        load_mode: ``"full"`` or ``"incremental"``.
        status: ``"success"`` or ``"failed"``.
        error: Error message string if ``status == "failed"``, else ``None``.
        started_at: ISO-8601 UTC timestamp when the run started.
        finished_at: ISO-8601 UTC timestamp when the run ended (success or fail).
        duration_seconds: Wall-clock duration of the run.
        datasets: Per-dataset statistics dict.
        total_rows_affected: Sum of all rows inserted + updated across datasets.
    """

    def __init__(self, config_file: str | Path, load_mode: str) -> None:
        self.config_file = str(config_file)
        self.load_mode = load_mode
        self.status = "running"
        self.error: str | None = None
        self.started_at: str = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        self.finished_at: str | None = None
        self.duration_seconds: float = 0.0
        self.datasets: dict[str, dict[str, Any]] = {}
        self.total_rows_affected: int = 0

    def record_dataset(
        self,
        name: str,
        status: str,                # "written" | "upserted" | "skipped" | "failed"
        rows_written: int = 0,
        rows_inserted: int = 0,
        rows_updated: int = 0,
        location: str = "",
    ) -> None:
        """Record per-dataset statistics."""
        self.datasets[name] = {
            "status": status,
            "rows_written": rows_written,
            "rows_inserted": rows_inserted,
            "rows_updated": rows_updated,
            "location": location,
        }

    def finish_success(self, duration: float, total_rows: int) -> None:
        """Mark run as successful."""
        self.status = "success"
        self.duration_seconds = round(duration, 3)
        self.total_rows_affected = total_rows
        self.finished_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()

    def finish_failure(self, duration: float, error: str) -> None:
        """Mark run as failed."""
        self.status = "failed"
        self.duration_seconds = round(duration, 3)
        self.error = error
        self.finished_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "timestamp": self.started_at,
            "config": self.config_file,
            "load_mode": self.load_mode,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "total_rows_affected": self.total_rows_affected,
            "datasets": self.datasets,
        }


def write_metrics(metrics: RunMetrics, path: Path) -> None:
    """Write *metrics* to *path* atomically.

    Args:
        metrics: The completed :class:`RunMetrics` object.
        path: Destination file path (e.g. ``run_metrics.json``).

    Raises:
        OSError: If the file cannot be written (permissions, disk full, etc.).
            Callers should catch and log this rather than crashing the run.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    data = json.dumps(metrics.to_dict(), indent=2, default=str) + "\n"
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)
