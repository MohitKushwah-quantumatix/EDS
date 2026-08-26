"""Live terminal progress display for eds_loader CLI runs.

Renders a single self-updating line on the terminal (carriage-return
overwrite, no extra dependency) driven entirely by log records — connectors
and :mod:`eds_loader.loader` don't need to know a progress bar exists. They
just attach a small ``progress`` dict to specific ``INFO``-level log calls
via ``extra={"progress": {...}}``; :class:`TerminalProgress` reacts to those
and ignores every other log record, so the console shows *only* clean
progress output while the full text of every log call (this handler's
input included) still goes to the daily log file via the separate file
handler set up in :mod:`eds_loader._logging`.

``progress`` dict shape (all keys except ``stage`` are optional)::

    {
        "stage": "connect_source" | "read" | "connect_target" | "write" | "done",
        "current": 12,       # items completed so far in this stage
        "total": 39,         # total items in this stage
        "label": "categories",  # e.g. table name being processed right now
    }
"""

from __future__ import annotations

import logging
import sys

__all__ = ["TerminalProgress"]

_STAGE_LABELS = {
    "connect_source": "Connecting to source",
    "read": "Reading datasets",
    "connect_target": "Connecting to target",
    "write": "Writing datasets",
    "done": "Done",
}

_BAR_WIDTH = 24


class TerminalProgress(logging.Handler):
    """A ``logging.Handler`` that renders a live progress line on stderr.

    Use as a context manager around a loader run so the line is always
    cleanly finished (moved to its own final newline) even if the run
    raises::

        with TerminalProgress() as progress:
            logging.getLogger("eds_loader").addHandler(progress)
            try:
                load(config)
            finally:
                logging.getLogger("eds_loader").removeHandler(progress)

    When stderr is not an interactive terminal (e.g. output is piped to a
    file), rendering is skipped entirely — carriage-return overwriting only
    makes sense on a real terminal.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self._current_stage: str | None = None
        self._last_line_len = 0
        try:
            self._enabled = sys.stderr.isatty()
        except Exception:
            self._enabled = False

    def __enter__(self) -> TerminalProgress:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def emit(self, record: logging.LogRecord) -> None:
        if not self._enabled:
            return
        progress = getattr(record, "progress", None)
        if not progress:
            return
        try:
            self._handle(progress)
        except Exception:
            # A progress-bar bug must never break the actual load.
            pass

    def _handle(self, progress: dict) -> None:
        stage = progress.get("stage", "")
        if stage != self._current_stage:
            self._finish_line()
            self._current_stage = stage

        if stage == "done":
            self._finish_line()
            return

        label = _STAGE_LABELS.get(stage, stage)
        current = progress.get("current")
        total = progress.get("total")
        item = progress.get("label", "")

        if current is not None and total:
            filled = int(_BAR_WIDTH * current / max(total, 1))
            bar = "#" * filled + "-" * (_BAR_WIDTH - filled)
            text = f"{label} [{bar}] {current}/{total}"
            if item:
                text += f"  {item}"
        else:
            text = f"{label}..." if not item else f"{label}: {item}"

        self._write_line(text)

    def _write_line(self, text: str) -> None:
        pad = max(0, self._last_line_len - len(text))
        sys.stderr.write("\r" + text + (" " * pad))
        sys.stderr.flush()
        self._last_line_len = len(text)

    def _finish_line(self) -> None:
        if self._last_line_len:
            sys.stderr.write("\n")
            sys.stderr.flush()
            self._last_line_len = 0

    def close(self) -> None:
        self._finish_line()
        super().close()
