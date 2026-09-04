"""Cron-driven daily simulation runner.

Reads settings from config.yaml in the same directory.
Uses SQLite in-memory for simulation history with JSON backup for crash recovery.

Supports two config formats:
  1. Single-domain (legacy): top-level keys (domain, project_dir, etc.)
  2. Multi-domain: a "domains" list where each entry has its own config

Both formats can be combined: top-level keys define defaults, and the
"domains" list overrides them for multi-domain runs.

Usage:
    python cron_runner.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from run_day import run_retail_day, run_healthcare_day, load_checkpoint

CONFIG_FILE = Path(__file__).parent / "config.yaml"
CHECKPOINT_FILE = "daily_checkpoint.json"


def load_config() -> dict[str, Any]:
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def run_single_day(domain: str, target_date: date, project_dir: Path, seed: int) -> None:
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"Running {domain} for {target_date.isoformat()}..."
    )

    if domain == "retail":
        run_retail_day(project_dir, target_date, seed)
    else:
        run_healthcare_day(project_dir, target_date, seed)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Completed {target_date.isoformat()}")


def _normalize_domain_configs(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of domain configs from either the new multi-domain
    format or the legacy single-domain format.

    If config has a "domains" key, use it directly. Otherwise wrap the
    top-level config into a single-element list (backward compatibility).
    """
    domains = config.get("domains")
    if domains:
        return domains
    return [config]


def _parse_date_range(dc: dict[str, Any]) -> tuple[date, date, int | None, str | None]:
    """Parse start_date, end_date, and scheduling settings from a domain config."""
    start_date = dc["start_date"]
    end_date = dc["end_date"]
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)
    interval_minutes = dc.get("cron_interval_minutes")
    daily_time = dc.get("cron_daily_time")
    return start_date, end_date, interval_minutes, daily_time


def run_cron_scheduler(config: dict[str, Any]) -> None:
    """Run a single domain's simulation day-by-day.

    Two scheduling modes:

    - **Testing mode** (``cron_interval_minutes`` set, no ``cron_daily_time``):
      Runs all days in a single process, sleeping ``interval_minutes``
      between each day. Day 1 runs immediately.

    - **Production mode** (``cron_daily_time`` set): Each invocation runs
      **only the next uncompleted day**, then exits. Use with OS cron
      (or Task Scheduler) to call this script daily at the desired time.
      Day 1 waits until the scheduled time on that day.
    """
    domain = config["domain"]
    project_dir = Path(config.get("project_dir", f"my-{domain}"))
    seed = config.get("seed", 42)
    start_date, end_date, interval_minutes, daily_time = _parse_date_range(config)

    total_days = (end_date - start_date).days + 1

    checkpoint = load_checkpoint(project_dir)
    if checkpoint is None:
        current_day = 0
        print(
            f"[{domain}] Starting fresh: {total_days} days from "
            f"{start_date.isoformat()} to {end_date.isoformat()}"
        )
    else:
        current_day = (checkpoint - start_date).days + 1
        print(
            f"[{domain}] Resuming from checkpoint: "
            f"day {current_day + 1}/{total_days}"
        )

    if current_day >= total_days:
        print(f"[{domain}] All days already completed!")
        return

    # ── Production mode: one day per invocation ─────────────────────────
    if daily_time:
        # Day 1: wait until the scheduled time on start_date
        # Day 2+: the OS cron should call us at the right time; just check
        #        the checkpoint and run the next incomplete day.
        target_date = start_date + timedelta(days=current_day)
        wait_seconds = _wait_until_daily_time(daily_time)
        if wait_seconds > 0:
            print(
                f"[{domain}] Waiting {wait_seconds // 60} minutes "
                f"until scheduled run at {daily_time}..."
            )
            time.sleep(wait_seconds)

        try:
            run_single_day(domain, target_date, project_dir, seed)
        except Exception as e:
            print(f"[{domain}] ERROR on {target_date.isoformat()}: {e}")
            raise

        remaining = (end_date - target_date).days
        if remaining > 0:
            print(
                f"[{domain}] Next run will handle {remaining} day(s) "
                f"starting {target_date + timedelta(days=1)}."
            )
            print(
                f"[{domain}] Schedule the next cron invocation at "
                f"{daily_time} for day {current_day + 2}/{total_days}."
            )
        else:
            print(f"[{domain}] All {total_days} days completed successfully!")
        return

    # ── Testing mode: all days in one process ───────────────────────────
    if interval_minutes is None:
        interval_minutes = 5

    for i in range(current_day, total_days):
        target_date = start_date + timedelta(days=i)

        if i > current_day:
            wait_seconds = interval_minutes * 60
            print(f"[{domain}] Waiting {interval_minutes} minutes until next run...")
            time.sleep(wait_seconds)

        try:
            run_single_day(domain, target_date, project_dir, seed)
        except Exception as e:
            print(f"[{domain}] ERROR on {target_date.isoformat()}: {e}")
            raise

    print(f"[{domain}] All {total_days} days completed successfully!")


def run_multi_domain(config: dict[str, Any]) -> None:
    """Run multiple domains in lockstep (day 1 of all domains, then day 2 of all, etc.).

    All domains use the same scheduling interval. Each domain has its own
    project_dir, checkpoint, and backup for independent crash recovery.

    In production mode (``cron_daily_time``), each invocation runs only the
    next uncompleted day for all domains, then exits.
    """
    domain_configs = _normalize_domain_configs(config)
    print(f"Multi-domain mode: running {len(domain_configs)} domains simultaneously:")
    for dc in domain_configs:
        dname = dc["domain"]
        dpath = dc.get("project_dir", f"my-{dname}")
        print(f"  - {dname} at {dpath}")

    # Use scheduling settings from the first domain config
    first_config = domain_configs[0]
    _, _, interval_minutes, daily_time = _parse_date_range(first_config)
    if interval_minutes is None:
        interval_minutes = 5

    total_domains = len(domain_configs)

    # ── Production mode: one day per invocation ─────────────────────────
    if daily_time:
        domains_done = 0

        # Determine which domains have an incomplete day to run
        to_run = []
        for dc in domain_configs:
            dname = dc["domain"]
            dpath = Path(dc.get("project_dir", f"my-{dname}"))
            dseed = dc.get("seed", 42)
            d_start, d_end, _, _ = _parse_date_range(dc)

            checkpoint = load_checkpoint(dpath)
            if checkpoint is None:
                current_day = 0
            else:
                current_day = (checkpoint - d_start).days + 1

            total_days_d = (d_end - d_start).days + 1
            if current_day >= total_days_d:
                print(f"[{dname}] All days already completed!")
                domains_done += 1
                continue

            target_date = d_start + timedelta(days=current_day)
            to_run.append((dname, dpath, dseed, target_date, current_day + 1, total_days_d))

        if not to_run:
            print(f"\nAll {total_domains} domains fully completed!")
            return

        # Wait once for all domains
        wait_seconds = _wait_until_daily_time(daily_time)
        if wait_seconds > 0:
            print(
                f"Scheduling: waiting {wait_seconds // 60} minutes "
                f"until scheduled run at {daily_time}..."
            )
            time.sleep(wait_seconds)

        # Run all pending domains in parallel so a failure in one
        # does not block the others, and both get the full time window.
        results: dict[str, BaseException | None] = {}
        threads: list[threading.Thread] = []

        def _run_domain(
            dname: str,
            dpath: Path,
            dseed: int,
            target_date: date,
            day_num: int,
            total_d: int,
        ) -> None:
            try:
                run_single_day(dname, target_date, dpath, dseed)
                results[dname] = None
                print(f"[{dname}] Day {day_num}/{total_d} completed.")
            except Exception as e:
                results[dname] = e
                print(f"[{dname}] ERROR on {target_date.isoformat()}: {e}")

        for dname, dpath, dseed, target_date, day_num, total_d in to_run:
            print(f"[{dname}] Starting day {day_num}/{total_d} ({target_date.isoformat()})")
            t = threading.Thread(
                target=_run_domain,
                args=(dname, dpath, dseed, target_date, day_num, total_d),
                daemon=True,
            )
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        domains_done = sum(1 for exc in results.values() if exc is None)
        for exc in results.values():
            if exc is not None:
                raise exc

        print(
            f"\nScheduling: {domains_done}/{total_domains} domains "
            f"completed for this run."
        )
        print(f"Schedule the next cron invocation at {daily_time} for the next day.")
        return

    # ── Testing mode: all days in one process ───────────────────────────
    ranges = []
    for dc in domain_configs:
        s, e, _, _ = _parse_date_range(dc)
        ranges.append((s, e))

    common_start = min(r[0] for r in ranges)
    common_end = min(r[1] for r in ranges)
    total_days = (common_end - common_start).days + 1

    for day_offset in range(total_days):
        target_date = common_start + timedelta(days=day_offset)

        if day_offset > 0:
            wait_seconds = interval_minutes * 60
            print(f"Scheduling: waiting {interval_minutes} minutes for all domains...")
            time.sleep(wait_seconds)

        domains_done = 0
        for dc in domain_configs:
            dname = dc["domain"]
            dpath = Path(dc.get("project_dir", f"my-{dname}"))
            dseed = dc.get("seed", 42)
            d_start, d_end, _, _ = _parse_date_range(dc)

            if target_date < d_start:
                print(f"[{dname}] Skipping {target_date.isoformat()} — before start date")
                continue
            if target_date > d_end:
                print(f"[{dname}] Skipping {target_date.isoformat()} — past end date")
                continue

            checkpoint = load_checkpoint(dpath)
            if checkpoint is not None and target_date <= checkpoint:
                print(f"[{dname}] Already completed {target_date.isoformat()} — skipping")
                domains_done += 1
                continue

            try:
                run_single_day(dname, target_date, dpath, dseed)
                domains_done += 1
            except Exception as e:
                print(f"[{dname}] ERROR on {target_date.isoformat()}: {e}")
                raise

        print(
            f"Scheduling: {domains_done}/{total_domains} domains "
            f"completed for {target_date.isoformat()}"
        )

    print(f"\nAll {total_domains} domains completed all days successfully!")


def _wait_until_daily_time(daily_time: str, now: datetime | None = None) -> int:
    """Calculate seconds to wait until the next occurrence of daily_time (HH:MM in 24h format).

    Returns 0 if the target time has already passed today or is right now
    (the caller should just run immediately). Returns a positive wait time
    only if the target is still in the future today.
    """
    if now is None:
        now = datetime.now()
    hour, minute = map(int, daily_time.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if now >= target:
        return 0

    wait_seconds = int((target - now).total_seconds())
    return max(wait_seconds, 0)


_CRON_MARKER = "# EDS cron_runner auto-generated - do not edit manually"


def _get_cron_command(daily_time: str) -> str:
    script_dir = Path(__file__).parent.resolve()
    python_exe = sys.executable
    log_file = script_dir.parent / "cron.log"
    return f"cd {script_dir} && {python_exe} cron_runner.py >> {log_file} 2>&1"


def _cron_job_exists() -> bool:
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return _CRON_MARKER in result.stdout
    except Exception:
        return False


def _install_cron_job(daily_time: str) -> None:
    # Skip cron job installation on Windows
    if os.name == "nt":
        print(f"[cron] Skipping cron job installation on Windows. Please use Task Scheduler to run the script daily at {daily_time}.")
        return

    hour, minute = daily_time.split(":")
    cron_cmd = _get_cron_command(daily_time)
    cron_entry = f"{minute} {hour} * * * {cron_cmd} {_CRON_MARKER}"

    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""
    except Exception:
        existing = ""

    new_crontab = existing.rstrip() + "\n" + cron_entry + "\n"

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".crontab") as f:
        f.write(new_crontab)
        tmp_path = f.name

    try:
        subprocess.run(["crontab", tmp_path], check=True)
        print(f"[cron] Installed daily cron job at {daily_time}")
    except Exception as e:
        print(f"[cron] Warning: could not install cron job: {e}")
    finally:
        os.unlink(tmp_path)


def _remove_cron_job() -> None:
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            return
        lines = result.stdout.splitlines()
        new_lines = [line for line in lines if _CRON_MARKER not in line]
        new_crontab = "\n".join(new_lines)
        if not new_crontab.endswith("\n") and new_crontab:
            new_crontab += "\n"

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".crontab") as f:
            f.write(new_crontab)
            tmp_path = f.name

        subprocess.run(["crontab", tmp_path], check=True)
        os.unlink(tmp_path)
        print("[cron] Removed EDS cron job (all days completed)")
    except Exception as e:
        print(f"[cron] Warning: could not remove cron job: {e}")


def _all_domains_complete(config: dict[str, Any]) -> bool:
    domain_configs = _normalize_domain_configs(config)
    for dc in domain_configs:
        dname = dc["domain"]
        dpath = Path(dc.get("project_dir", f"my-{dname}"))
        d_start, d_end, _, _ = _parse_date_range(dc)
        checkpoint = load_checkpoint(dpath)
        if checkpoint is None:
            return False
        total_days = (d_end - d_start).days + 1
        current_day = (checkpoint - d_start).days + 1
        if current_day < total_days:
            return False
    return True


def main() -> None:
    config = load_config()

    daily_time = config.get("cron_daily_time")
    if not daily_time:
        domains = config.get("domains")
        if domains:
            daily_time = domains[0].get("cron_daily_time")

    if daily_time and not _cron_job_exists():
        _install_cron_job(daily_time)

    if config.get("domains"):
        run_multi_domain(config)
    else:
        run_cron_scheduler(config)

    if daily_time and _all_domains_complete(config):
        _remove_cron_job()


if __name__ == "__main__":
    main()
