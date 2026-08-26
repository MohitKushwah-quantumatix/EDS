"""Central logging setup for eds_loader.

Every module in this package gets its logger via :func:`get_logger`, which
returns a child of the ``"eds_loader"`` logger. Nothing is configured (no
handlers, no level) until :func:`configure_logging` is called — importing
this module or any connector never prints anything on its own, so it is
safe to import eds_loader as a library without unwanted side effects.

Behaviour (fully automatic — no flags, no configuration needed):

- A ``logs/`` directory is created next to the current working directory
  (i.e. wherever ``eds-loader`` is invoked from) the first time logging is
  configured.
- All events (DEBUG and above — connections, per-table DDL, row counts,
  errors) are written to ``logs/<YYYY-MM-DD>.log``. Every run on the same
  calendar date appends to that same file, so a day's worth of runs stays
  in one place; a new day gets a new file automatically.
- Nothing is printed to the console by the logging system itself — console
  feedback is handled separately by :mod:`eds_loader._progress`, which
  renders a live progress line driven by the same log events.
- If the ``logs/`` directory can't be created or written to (e.g. a
  read-only filesystem), logging is silently disabled rather than crashing
  the CLI — a loader run should never fail *because logging failed*.

Usage (CLI, called automatically on every invocation)::

    from eds_loader._logging import configure_logging
    configure_logging()

Usage (any module in this package)::

    from eds_loader._logging import get_logger
    logger = get_logger(__name__)
    logger.info("Connected to %s:%s", host, port)

Secrets (passwords, key passphrases) are never logged. Only credential
*names* (e.g. an env-var name) are ever included in log messages, matching
the existing exception-message convention used across the connectors.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

__all__ = ["configure_logging", "get_logger", "LOGS_DIR"]

_ROOT_LOGGER_NAME = "eds_loader"
_FILE_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"

LOGS_DIR = Path("logs")

_configured = False


def get_logger(module_name: str) -> logging.Logger:
    """Return the logger for *module_name* (pass ``__name__``).

    Always returns a child of the ``"eds_loader"`` logger regardless of
    whether :func:`configure_logging` has been called yet — log calls made
    before configuration are simply dropped by the default "no handlers"
    behaviour of the ``logging`` module, never raise, and never print.
    """
    return logging.getLogger(module_name)


def configure_logging() -> Path | None:
    """Attach a daily file handler to the root eds_loader logger.

    Safe to call more than once — existing eds_loader file handlers are
    removed first so repeated calls (e.g. across tests) don't duplicate
    output or hold multiple open file handles.

    Returns:
        The path of today's log file, or ``None`` if file logging could
        not be set up (e.g. permissions) — in that case the run continues
        normally without a log file.
    """
    global _configured

    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(logging.DEBUG)  # the file handler does the actual filtering
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()

    today = datetime.date.today().isoformat()
    log_path = LOGS_DIR / f"{today}.log"

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError:
        # Never let a logging failure break the actual load.
        _configured = True
        return None

    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(file_handler)

    _configured = True
    return log_path
