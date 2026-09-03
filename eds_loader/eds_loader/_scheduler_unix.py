"""Linux / macOS crontab backend for eds_loader schedule feature.

All operations manipulate the current user's crontab via
``crontab -l`` (read) and ``crontab -`` (write).

Each task managed by eds_loader is identified by a unique comment marker
on the line immediately before the cron entry::

    # eds-loader: /abs/path/to/loader.yaml
    0 2 * * * eds-loader run -c /abs/path/to/loader.yaml

The marker makes it safe to run multiple loader configs side by side — each
one is identified and updated independently.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from eds_loader._scheduler import ScheduleStatus

__all__ = ["register", "remove", "pause", "resume", "status"]

# Marker format — must be unique per config path
_MARKER_PREFIX = "# eds-loader:"
_PAUSE_COMMENT = "# eds-loader-paused:"


def _marker(config_path: Path) -> str:
    return f"{_MARKER_PREFIX} {config_path}"


def _pause_marker(config_path: Path) -> str:
    return f"{_PAUSE_COMMENT} {config_path}"


# ---------------------------------------------------------------------------
# Low-level crontab read / write
# ---------------------------------------------------------------------------

def _read_crontab() -> str:
    """Return the current user's crontab as a string (empty string if none)."""
    result = subprocess.run(
        ["crontab", "-l"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout
    # crontab -l exits 1 when there is no crontab yet
    if "no crontab" in result.stderr.lower():
        return ""
    raise RuntimeError(f"Failed to read crontab: {result.stderr.strip()}")


def _write_crontab(content: str) -> None:
    """Write *content* as the current user's crontab."""
    result = subprocess.run(
        ["crontab", "-"],
        input=content,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to write crontab: {result.stderr.strip()}")


# ---------------------------------------------------------------------------
# Block helpers
# ---------------------------------------------------------------------------

def _make_cron_line(cron: str, config_path: Path) -> str:
    """Build the two-line crontab block for this config.

    The cron entry uses ``cd <config_dir> &&`` before the eds-loader command
    so that the working directory is always the folder containing the config
    file. This ensures ``logs/<YYYY-MM-DD>.log`` is written next to the config
    (e.g. /home/mohit/eds/eds_loader/logs/) instead of the user's home dir,
    which is cron's default CWD.
    """
    exe = _find_eds_loader()
    work_dir = config_path.parent
    return (
        f"{_marker(config_path)}\n"
        f"{cron} cd {work_dir} && {exe} run -c {config_path}\n"
    )


def _remove_block(lines: list[str], config_path: Path) -> list[str]:
    """Remove marker + cron line for *config_path* from *lines*."""
    marker = _marker(config_path)
    pause_marker = _pause_marker(config_path)
    result: list[str] = []
    skip_next = False
    for line in lines:
        if line.strip() in (marker, pause_marker):
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        result.append(line)
    return result


def _find_block(lines: list[str], config_path: Path) -> tuple[int, int] | None:
    """Return (marker_idx, cron_idx) if the block exists, else None."""
    marker = _marker(config_path)
    pause_marker = _pause_marker(config_path)
    for i, line in enumerate(lines):
        if line.strip() in (marker, pause_marker):
            if i + 1 < len(lines):
                return i, i + 1
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register(
    task_name: str,
    cron: str,
    timezone: str,
    config_path: Path,
) -> None:
    """Add or update a crontab entry for this config."""
    current = _read_crontab()
    lines = current.splitlines(keepends=True)

    # Remove existing block (idempotent)
    lines = _remove_block(lines, config_path)

    # Add new block at end
    block = _make_cron_line(cron, config_path)
    new_content = "".join(lines)
    if not new_content.endswith("\n") and new_content:
        new_content += "\n"
    new_content += block

    _write_crontab(new_content)


def remove(task_name: str) -> None:
    """Remove the crontab entry identified by *task_name*.

    task_name for Unix backend encodes the config path as:
    ``eds-loader [<stem>]`` — we need to find it by scanning markers.
    Since we always call ``_remove_block(config_path)`` from higher level,
    this function is called with the raw task_name and we scan all markers.
    """
    current = _read_crontab()
    lines = current.splitlines(keepends=True)

    # Find any line matching our prefix and containing task_name stem
    stem = task_name.replace("eds-loader [", "").replace("]", "").strip()

    result: list[str] = []
    skip_next = False
    found = False
    for line in lines:
        stripped = line.strip()
        if (
            stripped.startswith(_MARKER_PREFIX)
            or stripped.startswith(_PAUSE_COMMENT)
        ) and stem in stripped:
            skip_next = True
            found = True
            continue
        if skip_next:
            skip_next = False
            continue
        result.append(line)

    if not found:
        raise RuntimeError(f"Scheduled task not found in crontab: {task_name!r}")

    _write_crontab("".join(result))


def pause(task_name: str) -> None:
    """Comment out the cron line (keep the marker for resume)."""
    current = _read_crontab()
    lines = current.splitlines(keepends=True)
    stem = task_name.replace("eds-loader [", "").replace("]", "").strip()

    result: list[str] = []
    i = 0
    found = False
    while i < len(lines):
        stripped = lines[i].strip()
        if (
            stripped.startswith(_MARKER_PREFIX)
            and stem in stripped
        ):
            # Replace marker with paused marker
            paused_marker = stripped.replace(_MARKER_PREFIX, _PAUSE_COMMENT)
            result.append(paused_marker + "\n")
            # Comment out the following cron line
            if i + 1 < len(lines):
                i += 1
                result.append("# " + lines[i])
            found = True
        else:
            result.append(lines[i])
        i += 1

    if not found:
        raise RuntimeError(f"Scheduled task not found in crontab: {task_name!r}")

    _write_crontab("".join(result))


def resume(task_name: str) -> None:
    """Uncomment a paused cron line."""
    current = _read_crontab()
    lines = current.splitlines(keepends=True)
    stem = task_name.replace("eds-loader [", "").replace("]", "").strip()

    result: list[str] = []
    i = 0
    found = False
    while i < len(lines):
        stripped = lines[i].strip()
        if (
            stripped.startswith(_PAUSE_COMMENT)
            and stem in stripped
        ):
            # Restore active marker
            active_marker = stripped.replace(_PAUSE_COMMENT, _MARKER_PREFIX)
            result.append(active_marker + "\n")
            # Uncomment the following line
            if i + 1 < len(lines):
                i += 1
                cron_line = lines[i]
                if cron_line.startswith("# "):
                    cron_line = cron_line[2:]
                result.append(cron_line)
            found = True
        else:
            result.append(lines[i])
        i += 1

    if not found:
        raise RuntimeError(f"Scheduled task not found in crontab: {task_name!r}")

    _write_crontab("".join(result))


def status(task_name: str) -> ScheduleStatus:
    """Return the current status of the crontab entry."""
    current = _read_crontab()
    lines = current.splitlines()
    stem = task_name.replace("eds-loader [", "").replace("]", "").strip()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(_MARKER_PREFIX) and stem in stripped:
            return ScheduleStatus(
                registered=True,
                paused=False,
                task_name=task_name,
            )
        if stripped.startswith(_PAUSE_COMMENT) and stem in stripped:
            return ScheduleStatus(
                registered=True,
                paused=True,
                task_name=task_name,
            )

    return ScheduleStatus(registered=False, paused=False, task_name=task_name)


def _find_eds_loader() -> str:
    """Find the eds-loader executable path."""
    import shutil
    exe = shutil.which("eds-loader")
    if exe:
        return exe
    return f"{sys.executable} -m eds_loader.cli.main"
