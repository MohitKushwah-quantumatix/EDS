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
      - ``*/N * * * *``      → every N minutes (repetition trigger)
      - ``M H * * *``        → daily at H:M
      - ``M H */N * *``      → every N days (repetition trigger)
      - ``M H * * DOW``      → weekly on day DOW
      - ``M H DOM * *``      → monthly on day DOM

    Returns a PowerShell expression that evaluates to a ScheduledTaskTrigger.
    """
    parts = cron.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Expected 5-field cron expression, got: {cron!r}")

    minute, hour, dom, month, dow = parts

    # ── Every-N-minutes pattern  (e.g. */2 * * * *) ──────────────────────────
    if minute.startswith("*/") and hour == "*" and dom == "*":
        n = int(minute[2:])
        # Use Get-Date so the first run fires at next interval from NOW,
        # not from midnight. RepetitionDuration of 1 day renews at midnight.
        return (
            f"$t = New-ScheduledTaskTrigger -Once -At (Get-Date) "
            f"-RepetitionInterval (New-TimeSpan -Minutes {n}) "
            f"-RepetitionDuration (New-TimeSpan -Days 9999); $t"
        )

    # ── Resolve hour and minute (may be '*' for wildcard → default to 0) ─────
    try:
        h = int(hour) if hour != "*" else 0
        m = int(minute) if minute != "*" else 0
    except ValueError as exc:
        raise ValueError(
            f"Unsupported cron expression {cron!r}: {exc}. "
            "Supported patterns: '*/N * * * *' (every N min), "
            "'M H * * *' (daily), 'M H */N * *' (every N days), "
            "'M H * * DOW' (weekly), 'M H DOM * *' (monthly)."
        ) from exc
    time_str = f"{h:02d}:{m:02d}:00"

    # ── Every N days pattern  (e.g. */2) ─────────────────────────────────────
    if dom.startswith("*/") and dow == "*":
        n = int(dom[2:])
        return (
            f"$t = New-ScheduledTaskTrigger -Daily -At '{time_str}'; "
            f"$t.Repetition = $null; "
            f"$t.DaysInterval = {n}; $t"
        )

    # ── Weekly  (e.g. * * * * 1) ─────────────────────────────────────────────
    if dom == "*" and dow != "*":
        dow_map = {
            "0": "Sunday", "1": "Monday", "2": "Tuesday",
            "3": "Wednesday", "4": "Thursday", "5": "Friday", "6": "Saturday",
            "7": "Sunday",
        }
        day_name = dow_map.get(dow, "Monday")
        return f"New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek {day_name} -At '{time_str}'"

    # ── Monthly  (e.g. 1 2 15 * *) ───────────────────────────────────────────
    if dom != "*" and dow == "*":
        return f"New-ScheduledTaskTrigger -Monthly -DaysOfMonth {int(dom)} -At '{time_str}'"

    # ── Daily (default) ───────────────────────────────────────────────────────
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

    Raises:
        RuntimeError: If the process is not running as Administrator, or if
            PowerShell fails to register the task.
    """
    # ── Admin check — Register-ScheduledTask requires elevated privileges ──
    admin_check = _run_ps(
        "([Security.Principal.WindowsPrincipal]"
        "[Security.Principal.WindowsIdentity]::GetCurrent())"
        ".IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)",
        check=False,
    )
    if admin_check.stdout.strip().lower() != "true":
        raise RuntimeError(
            "Administrator privileges required to register a Windows Scheduled Task.\n"
            "Please re-run this command from an Administrator PowerShell prompt:\n"
            "  Right-click PowerShell → 'Run as administrator', then run:\n"
            "  eds-loader schedule -c loader.yaml"
        )

    # Resolve the eds-loader executable
    eds_loader_exe = _find_eds_loader()

    trigger_expr = _cron_to_task_trigger(cron, timezone)
    config_path_str = str(config_path).replace("'", "''")  # escape for PS string
    task_name_esc = task_name.replace("'", "''")
    working_dir = str(config_path.parent).replace("'", "''")
    logs_dir = str(config_path.parent / "logs").replace("'", "''")

    # Build a wrapper script path alongside the config file
    wrapper_path = config_path.parent / ".eds_loader_task.ps1"
    wrapper_path_esc = str(wrapper_path).replace("'", "''")

    # Write the wrapper PowerShell script — it:
    #   1. Re-loads user env vars (including password vars) from registry
    #   2. Calls eds-loader with the absolute config path
    #   3. Logs all output to logs/<date>.log for easy debugging
    wrapper_script = f"""\
# Auto-generated by eds-loader schedule — do not edit manually.
# Re-apply user-level environment variables so passwords are available.
$userEnv = [System.Environment]::GetEnvironmentVariables('User')
foreach ($key in $userEnv.Keys) {{
    if (-not [System.Environment]::GetEnvironmentVariable($key, 'Process')) {{
        [System.Environment]::SetEnvironmentVariable($key, $userEnv[$key], 'Process')
    }}
}}

$logsDir = '{logs_dir}'
if (-not (Test-Path $logsDir)) {{ New-Item -ItemType Directory -Path $logsDir | Out-Null }}
$datePart = (Get-Date).ToString('yyyy-MM-dd')
$logFile = "$logsDir\$datePart.task.log"

$timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Add-Content -Path $logFile -Value "[$timestamp] eds-loader scheduled run starting..." -Encoding UTF8

& '{eds_loader_exe}' run -c '{config_path_str}' 2>&1 | ForEach-Object {{
    $line = $_ | Out-String
    Add-Content -Path $logFile -Value $line.TrimEnd() -Encoding UTF8
    Write-Host $line.TrimEnd()
}}

$exitCode = $LASTEXITCODE
$timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Add-Content -Path $logFile -Value "[$timestamp] eds-loader exited with code: $exitCode" -Encoding UTF8
exit $exitCode
"""
    wrapper_path.write_text(wrapper_script, encoding="utf-8")

    ps_script = f"""
$ErrorActionPreference = 'Stop'
$tn = [Management.Automation.WildcardPattern]::Escape('{task_name_esc}')
$trigger = {trigger_expr}
$action  = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument '-NonInteractive -ExecutionPolicy Bypass -File "{wrapper_path_esc}"' `
    -WorkingDirectory '{working_dir}'
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -RestartCount 0 `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

# Unregister if already exists (idempotent update)
Unregister-ScheduledTask -TaskName $tn -Confirm:$false -ErrorAction SilentlyContinue

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
# Escape wildcard chars so '[' in task name is treated as literal
$tn = [Management.Automation.WildcardPattern]::Escape('{task_name_esc}')
$t = Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue
if ($null -eq $t) {{
    Write-Error "Task not found: {task_name_esc}"
    exit 1
}}
Unregister-ScheduledTask -TaskName $tn -Confirm:$false
Write-Host "OK"
"""
    _run_ps(ps_script)


def pause(task_name: str) -> None:
    """Disable the scheduled task without removing it."""
    task_name_esc = task_name.replace("'", "''")
    ps_script = f"""
$tn = [Management.Automation.WildcardPattern]::Escape('{task_name_esc}')
$t = Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue
if ($null -eq $t) {{
    Write-Error "Task not found: {task_name_esc}"
    exit 1
}}
Disable-ScheduledTask -TaskName $tn | Out-Null
Write-Host "OK"
"""
    _run_ps(ps_script)


def resume(task_name: str) -> None:
    """Re-enable a disabled scheduled task."""
    task_name_esc = task_name.replace("'", "''")
    ps_script = f"""
$tn = [Management.Automation.WildcardPattern]::Escape('{task_name_esc}')
$t = Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue
if ($null -eq $t) {{
    Write-Error "Task not found: {task_name_esc}"
    exit 1
}}
Enable-ScheduledTask -TaskName $tn | Out-Null
Write-Host "OK"
"""
    _run_ps(ps_script)


def status(task_name: str) -> ScheduleStatus:
    """Return the current status of a scheduled task."""
    task_name_esc = task_name.replace("'", "''")
    ps_script = f"""
# Escape wildcard chars ([ ] * ?) so task name is matched literally
$tn = [Management.Automation.WildcardPattern]::Escape('{task_name_esc}')
$t = Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue
if ($null -eq $t) {{
    Write-Output '{{"found": false}}'
    exit 0
}}
$info = Get-ScheduledTaskInfo -TaskName $tn -ErrorAction SilentlyContinue
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
