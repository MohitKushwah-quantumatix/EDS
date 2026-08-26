"""Cron-driven daily simulation runner.

Reads settings from config.yaml in the same directory.
Uses SQLite in-memory for simulation history with JSON backup for crash recovery.

Usage:
    python cron_runner.py
"""

from __future__ import annotations

import json
import time
import webbrowser
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
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running {domain} for {target_date.isoformat()}...")
    
    if domain == "retail":
        run_retail_day(project_dir, target_date, seed)
    else:
        run_healthcare_day(project_dir, target_date, seed)
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Completed {target_date.isoformat()}")


def run_cron_scheduler(config: dict[str, Any]) -> None:
    domain = config["domain"]
    start_date = config["start_date"]
    end_date = config["end_date"]
    interval_minutes = config.get("cron_interval_minutes", 5)
    seed = config.get("seed", 42)
    project_dir = Path(config.get("project_dir", f"my-{domain}"))
    
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)
    
    total_days = (end_date - start_date).days + 1
    
    checkpoint = load_checkpoint(project_dir)
    if checkpoint is None:
        current_day = 0
        print(f"Starting fresh: {total_days} days from {start_date.isoformat()} to {end_date.isoformat()}")
    else:
        current_day = (checkpoint - start_date).days + 1
        print(f"Resuming from checkpoint: day {current_day + 1}/{total_days}")
    
    if current_day >= total_days:
        print("All days already completed!")
        return
    
    for i in range(current_day, total_days):
        target_date = start_date + timedelta(days=i)
        
        if i > current_day:
            wait_seconds = interval_minutes * 60
            next_sim_date = start_date + timedelta(days=i)
            print(f"Waiting {interval_minutes} minutes until next run...")
            print(f"Next run scheduled at: {next_sim_date.isoformat()}")
            time.sleep(wait_seconds)
        
        try:
            run_single_day(domain, target_date, project_dir, seed)
        except Exception as e:
            print(f"ERROR on {target_date.isoformat()}: {e}")
            raise
    
    print(f"\nAll {total_days} days completed successfully!")
    print(f"Simulation period: {start_date.isoformat()} to {end_date.isoformat()}")


def main() -> None:
    config = load_config()
    run_cron_scheduler(config)


if __name__ == "__main__":
    main()
