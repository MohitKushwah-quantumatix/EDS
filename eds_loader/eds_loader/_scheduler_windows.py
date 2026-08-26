"""Windows Task Scheduler backend for eds_loader schedule feature.

Uses PowerShell's ``Register-ScheduledTask`` family of cmdlets.
All operations are performed via ``subprocess.run(["powershell", ...])``
so no extra Python dependencies are needed — PowerShell ships with every
modern Windows installation.

The registered task runs:
    eds-loader run -c <config_path>

under the SYSTEM account (no user login required), with the working directory
set to the parent folder of the config file.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from eds_loader._scheduler import ScheduleStatus

__all__ = ["register", "remove", "pause", "resume", "status"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_ps(script: str, check: bool = True) -> subprocess.CompletedProcess:
    """Execute a PowerShell script and return the completed process."""
    result = subprocess.run(
        ["powershell", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"PowerShell command failed (exit {result.returncode}):\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def _cron_to_task_trigger(cron: str, timezone: str) -> str:
    """Convert a 5-field cron expression to a PowerShell trigger block.

    Supported patterns:
      - ``M H * * *``         → daily at H:M
      - ``M H */N * *``       → every N days (repetition trigger)
      - ``M H * * DOW``       → weekly on day DOW
      - ``M H DOM * *``       → monthly on day DOM

    Returns a PowerShell expression that evaluates to a ScheduledTaskTrigger.
    """
    parts = cron.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Expected 5-field cron expression, got: {cron!r}")

    minute, hour, dom, month, dow = parts
    h, m = int(hour), int(minute)
    time_str = f"{h:02d}:{m:02d}:00"

    # Every N days pattern  (e.g. */2)
    if dom.startswith("*/") and dow == "*":
        n = int(dom[2:])
        return (
            f"$t = New-ScheduledTaskTrigger -Daily -At '{time_str}'; "
            f"$t.Repetition = $null; "
            f"$t.DaysInterval = {n}; $t"
        )

    # Weekly  (e.g. * * * * 1)
    if dom == "*" and dow != "*":
        # PowerShell day-of-week names
        dow_map = {
            "0": "Sunday", "1": "Monday", "2": "Tuesday",
            "3": "Wednesday", "4": "Thursday", "5": "Friday", "6": "Saturday",
            "7": "Sunday",
        }
        day_name = dow_map.get(dow, "Monday")
        return f"New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek {day_name} -At '{time_str}'"

    # Monthly  (e.g. 1 2 15 * *)
    if dom != "*" and dow == "*":
        return f"New-ScheduledTaskTrigger -Monthly -DaysOfMonth {int(dom)} -At '{time_str}'"

    # Daily (default)
    return f"New-ScheduledTaskTrigger -Daily -At '{time_str}'"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register(
    task_name: str,
    cron: str,
    timezone: str,
    config_path: Path,
) -> None:
    """Register (or update) a Windows Scheduled Task.

    Args:
        task_name:   Human-readable task name shown in Task Scheduler UI.
        cron:        5-field cron expression.
        timezone:    IANA timezone (informational; Windows uses local time zone).
        config_path: Absolute path to the loader YAML file.
    """
    # Resolve the eds-loader executable
    eds_loader_exe = _find_eds_loader()

    trigger_expr = _cron_to_task_trigger(cron, timezone)
    config_path_str = str(config_path).replace("'", "''")  # escape for PS string
    task_name_esc = task_name.replace("'", "''")
    working_dir = str(config_path.parent).replace("'", "''")

    ps_script = f"""
$trigger = {trigger_expr}
$action  = New-ScheduledTaskAction `
    -Execute '{eds_loader_exe}' `
    -Argument 'run -c \\"{config_path_str}\\"' `
    -WorkingDirectory '{working_dir}'
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -RestartCount 0 `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

# Unregister if already exists (idempotent update)
Unregister-ScheduledTask -TaskName '{task_name_esc}' -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName '{task_name_esc}' `
    -Trigger $trigger `
    -Action $action `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "OK"
"""
    _run_ps(ps_script)


def remove(task_name: str) -> None:
    """Unregister a scheduled task by name."""
    task_name_esc = task_name.replace("'", "''")
    ps_script = f"""
$t = Get-ScheduledTask -TaskName '{task_name_esc}' -ErrorAction SilentlyContinue
if ($null -eq $t) {{
    Write-Error "Task not found: {task_name_esc}"
    exit 1
}}
Unregister-ScheduledTask -TaskName '{task_name_esc}' -Confirm:$false
Write-Host "OK"
"""
    _run_ps(ps_script)


def pause(task_name: str) -> None:
    """Disable the scheduled task without removing it."""
    task_name_esc = task_name.replace("'", "''")
    ps_script = f"""
$t = Get-ScheduledTask -TaskName '{task_name_esc}' -ErrorAction SilentlyContinue
if ($null -eq $t) {{
    Write-Error "Task not found: {task_name_esc}"
    exit 1
}}
Disable-ScheduledTask -TaskName '{task_name_esc}' | Out-Null
Write-Host "OK"
"""
    _run_ps(ps_script)


def resume(task_name: str) -> None:
    """Re-enable a disabled scheduled task."""
    task_name_esc = task_name.replace("'", "''")
    ps_script = f"""
$t = Get-ScheduledTask -TaskName '{task_name_esc}' -ErrorAction SilentlyContinue
if ($null -eq $t) {{
    Write-Error "Task not found: {task_name_esc}"
    exit 1
}}
Enable-ScheduledTask -TaskName '{task_name_esc}' | Out-Null
Write-Host "OK"
"""
    _run_ps(ps_script)


def status(task_name: str) -> ScheduleStatus:
    """Return the current status of a scheduled task."""
    task_name_esc = task_name.replace("'", "''")
    ps_script = f"""
$t = Get-ScheduledTask -TaskName '{task_name_esc}' -ErrorAction SilentlyContinue
if ($null -eq $t) {{
    Write-Output '{{"found": false}}'
    exit 0
}}
$info = Get-ScheduledTaskInfo -TaskName '{task_name_esc}' -ErrorAction SilentlyContinue
$obj = @{{
    found       = $true
    state       = $t.State.ToString()
    last_run    = if ($info.LastRunTime)  {{ $info.LastRunTime.ToString("o")  }} else {{ $null }}
    next_run    = if ($info.NextRunTime)  {{ $info.NextRunTime.ToString("o")  }} else {{ $null }}
    task_name   = $t.TaskName
}}
Write-Output ($obj | ConvertTo-Json)
"""
    result = _run_ps(ps_script, check=False)
    try:
        data = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return ScheduleStatus(registered=False, paused=False, task_name=task_name)

    if not data.get("found"):
        return ScheduleStatus(registered=False, paused=False, task_name=task_name)

    state = data.get("state", "")
    paused = state.lower() == "disabled"

    last_run: datetime | None = None
    next_run: datetime | None = None
    try:
        if data.get("last_run"):
            last_run = datetime.fromisoformat(data["last_run"])
        if data.get("next_run"):
            next_run = datetime.fromisoformat(data["next_run"])
    except (ValueError, TypeError):
        pass

    return ScheduleStatus(
        registered=True,
        paused=paused,
        task_name=data.get("task_name", task_name),
        last_run=last_run,
        next_run=next_run,
    )


def _find_eds_loader() -> str:
    """Find the eds-loader executable path."""
    import shutil
    exe = shutil.which("eds-loader")
    if exe:
        return exe
    # Fallback: use python -m eds_loader.cli.main
    python = sys.executable.replace("'", "''")
    return f"{python}' -m eds_loader.cli.main"
