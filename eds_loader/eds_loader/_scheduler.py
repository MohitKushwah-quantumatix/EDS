"""Scheduler engine for eds_loader.

Provides:
- ``build_cron_expression`` -- converts ScheduleConfig to a 5-field cron string
- ``should_run_today``      -- runtime skip-date guard (called at load start)
- ``register_schedule``     -- creates OS task (Windows Task Scheduler / crontab)
- ``remove_schedule``       -- deletes the OS task
- ``pause_schedule``        -- disables without deleting
- ``resume_schedule``       -- re-enables a paused task
- ``get_schedule_status``   -- returns current state of the registered task

Platform detection is automatic: Windows uses PowerShell Task Scheduler;
Linux/Mac uses crontab.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from eds_loader.config import ScheduleConfig

__all__ = [
    "ScheduleStatus",
    "build_cron_expression",
    "should_run_today",
    "register_schedule",
    "remove_schedule",
    "pause_schedule",
    "resume_schedule",
    "get_schedule_status",
]

# Weekday name → cron day-of-week number (0 = Sunday in most cron implementations;
# we use 1=Monday … 7=Sunday to match ISO weekday and Windows Task Scheduler)
_WEEKDAY_TO_CRON = {
    "Monday":    "1",
    "Tuesday":   "2",
    "Wednesday": "3",
    "Thursday":  "4",
    "Friday":    "5",
    "Saturday":  "6",
    "Sunday":    "0",
}

_ISO_WEEKDAY_NAMES = {
    1: "Monday", 2: "Tuesday", 3: "Wednesday",
    4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday",
}


# ---------------------------------------------------------------------------
# ScheduleStatus
# ---------------------------------------------------------------------------

@dataclass
class ScheduleStatus:
    """Current state of a registered scheduled task."""
    registered: bool
    paused: bool
    task_name: str
    next_run: datetime | None = None
    last_run: datetime | None = None
    cron_expression: str | None = None


# ---------------------------------------------------------------------------
# build_cron_expression
# ---------------------------------------------------------------------------

def build_cron_expression(cfg: ScheduleConfig) -> str:
    """Convert a :class:`~eds_loader.config.ScheduleConfig` to a 5-field cron string.

    If ``cfg.cron`` is already set, it is returned unchanged.

    The 5 fields are: ``minute hour day-of-month month day-of-week``.

    Args:
        cfg: A validated :class:`ScheduleConfig` instance.

    Returns:
        A 5-field cron expression string.

    Examples::

        # daily at 02:00
        build_cron_expression(ScheduleConfig(time="02:00"))
        # → "0 2 * * *"

        # every other day at 06:30
        build_cron_expression(ScheduleConfig(time="06:30", frequency="every_other_day"))
        # → "30 6 */2 * *"

        # weekly on Monday at 02:00
        build_cron_expression(ScheduleConfig(time="02:00", frequency="weekly", on_day="Monday"))
        # → "0 2 * * 1"

        # monthly on 1st at 02:00
        build_cron_expression(ScheduleConfig(time="02:00", frequency="monthly", on_date=1))
        # → "0 2 1 * *"
    """
    if cfg.cron:
        return cfg.cron

    # Parse HH:MM
    hour, minute = cfg.time.split(":")  # type: ignore[union-attr]

    freq = cfg.frequency

    if freq == "daily":
        return f"{int(minute)} {int(hour)} * * *"

    if freq == "every_other_day":
        return f"{int(minute)} {int(hour)} */2 * *"

    if freq == "weekly":
        dow = _WEEKDAY_TO_CRON[cfg.on_day]  # type: ignore[index]
        return f"{int(minute)} {int(hour)} * * {dow}"

    if freq == "monthly":
        return f"{int(minute)} {int(hour)} {cfg.on_date} * *"

    # Fallback (shouldn't reach here — Pydantic validates frequency)
    return f"{int(minute)} {int(hour)} * * *"


# ---------------------------------------------------------------------------
# should_run_today
# ---------------------------------------------------------------------------

def should_run_today(cfg: ScheduleConfig, today: date | None = None) -> tuple[bool, str]:
    """Check whether the loader should run on *today*'s date.

    This guard is called at the start of every scheduled run to enforce rules
    that a cron expression cannot express (date range, skip_dates, skip_weekends,
    skip_days).

    Args:
        cfg:   The schedule configuration.
        today: The date to check (defaults to ``date.today()``).

    Returns:
        A ``(should_run, reason)`` tuple.
        ``should_run`` is ``True`` if the run should proceed, ``False`` to skip.
        ``reason`` is a human-readable explanation (used in the CLI output).
    """
    today = today or date.today()
    today_str = today.isoformat()
    weekday_name = _ISO_WEEKDAY_NAMES[today.isoweekday()]  # 1=Monday … 7=Sunday

    # Date range: before start_date
    if cfg.start_date and today < date.fromisoformat(cfg.start_date):
        return False, f"Skipped — before start_date ({cfg.start_date})"

    # Date range: after end_date
    if cfg.end_date and today > date.fromisoformat(cfg.end_date):
        return False, f"Skipped — after end_date ({cfg.end_date})"

    # skip_dates (specific holidays etc.)
    if today_str in cfg.skip_dates:
        return False, f"Skipped — {today_str} is in skip_dates"

    # skip_weekends (shortcut for Saturday + Sunday)
    if cfg.skip_weekends and weekday_name in ("Saturday", "Sunday"):
        return False, f"Skipped — {weekday_name} (skip_weekends=true)"

    # skip_days (explicit list)
    if weekday_name in cfg.skip_days:
        return False, f"Skipped — {weekday_name} is in skip_days"

    return True, "OK"


# ---------------------------------------------------------------------------
# OS dispatch helpers
# ---------------------------------------------------------------------------

def _is_windows() -> bool:
    return sys.platform == "win32"


def _get_backend():
    """Return the platform-specific backend module."""
    if _is_windows():
        from eds_loader import _scheduler_windows as backend
    else:
        from eds_loader import _scheduler_unix as backend  # type: ignore[no-redef]
    return backend


def _task_name(config_path: Path) -> str:
    """Generate a unique Task Scheduler / crontab task name for this config file."""
    stem = config_path.resolve().stem
    return f"eds-loader [{stem}]"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_schedule(cfg: ScheduleConfig, config_path: Path) -> str:
    """Register (or update) the scheduled task on the host OS.

    Args:
        cfg:         The validated schedule configuration.
        config_path: Absolute path to the loader YAML config file.

    Returns:
        The task name that was registered.

    Raises:
        RuntimeError: If the backend fails to register the task.
    """
    cron = build_cron_expression(cfg)
    task_name = _task_name(config_path)
    backend = _get_backend()
    backend.register(
        task_name=task_name,
        cron=cron,
        timezone=cfg.timezone,
        config_path=config_path.resolve(),
    )
    return task_name


def remove_schedule(config_path: Path) -> str:
    """Remove the registered scheduled task.

    Args:
        config_path: Path to the loader YAML config file.

    Returns:
        The task name that was removed.

    Raises:
        RuntimeError: If the task is not found or removal fails.
    """
    task_name = _task_name(config_path)
    backend = _get_backend()
    backend.remove(task_name=task_name)
    return task_name


def pause_schedule(config_path: Path) -> str:
    """Disable the scheduled task without removing it.

    Args:
        config_path: Path to the loader YAML config file.

    Returns:
        The task name that was paused.
    """
    task_name = _task_name(config_path)
    backend = _get_backend()
    backend.pause(task_name=task_name)
    return task_name


def resume_schedule(config_path: Path) -> str:
    """Re-enable a paused scheduled task.

    Args:
        config_path: Path to the loader YAML config file.

    Returns:
        The task name that was resumed.
    """
    task_name = _task_name(config_path)
    backend = _get_backend()
    backend.resume(task_name=task_name)
    return task_name


def get_schedule_status(config_path: Path) -> ScheduleStatus:
    """Return the current status of the registered scheduled task.

    Args:
        config_path: Path to the loader YAML config file.

    Returns:
        A :class:`ScheduleStatus` dataclass.
    """
    task_name = _task_name(config_path)
    backend = _get_backend()
    return backend.status(task_name=task_name)
