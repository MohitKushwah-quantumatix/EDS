"""EDS Data Generator — driven by generate.yaml.

Reads a single YAML config file and runs the simulation for the requested
domain, date range, and mode (daily or batch). Supports custom config
directories so you can override domain settings without rebuilding the image.

Usage (local):
    python generate.py                          # uses generate.yaml in current dir
    python generate.py --config my-config.yaml  # uses a specific config file

Usage (Docker):
    docker run --rm \\
      -v ./generate.yaml:/config/generate.yaml \\
      -v ./my-hospital:/app/my-hospital \\
      eds-generator:latest \\
      python generate.py --config /config/generate.yaml

    # With custom domain configs (override defaults without rebuilding):
    docker run --rm \\
      -v ./generate.yaml:/config/generate.yaml \\
      -v ./my-configs:/config/domain-configs \\
      -v ./my-hospital:/app/my-hospital \\
      eds-generator:latest \\
      python generate.py --config /config/generate.yaml
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_generate_config(config_path: Path) -> dict:
    """Load and validate generate.yaml."""
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        print("  Create a generate.yaml file (see generate.yaml.example for reference)")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if cfg is None:
        print(f"ERROR: Config file is empty: {config_path}")
        sys.exit(1)

    # Validate required fields
    errors = []

    domain = cfg.get("domain", "").strip().lower()
    if domain not in ("retail", "healthcare"):
        errors.append(f"  'domain' must be 'retail' or 'healthcare', got: '{domain}'")

    mode = cfg.get("mode", "daily").strip().lower()
    if mode not in ("daily", "batch"):
        errors.append(f"  'mode' must be 'daily' or 'batch', got: '{mode}'")

    start_raw = cfg.get("start_date")
    end_raw   = cfg.get("end_date")

    if not start_raw:
        errors.append("  'start_date' is required (format: YYYY-MM-DD)")
    if not end_raw:
        errors.append("  'end_date' is required (format: YYYY-MM-DD)")

    if errors:
        print("ERROR: Invalid generate.yaml:")
        for e in errors:
            print(e)
        sys.exit(1)

    try:
        start_date = date.fromisoformat(str(start_raw))
    except ValueError:
        print(f"ERROR: 'start_date' is not a valid date: {start_raw}  (expected YYYY-MM-DD)")
        sys.exit(1)

    try:
        end_date = date.fromisoformat(str(end_raw))
    except ValueError:
        print(f"ERROR: 'end_date' is not a valid date: {end_raw}  (expected YYYY-MM-DD)")
        sys.exit(1)

    if end_date < start_date:
        print(f"ERROR: 'end_date' ({end_date}) must be >= 'start_date' ({start_date})")
        sys.exit(1)

    # Optional fields with defaults
    project_dir_raw = cfg.get("project_dir")
    if project_dir_raw:
        project_dir = Path(project_dir_raw)
    else:
        project_dir = Path("my-shop") if domain == "retail" else Path("my-hospital")

    seed = int(cfg.get("seed", 42))

    # Custom domain config directory (for overriding yaml files without rebuild)
    domain_config_dir_raw = cfg.get("domain_config_dir")
    domain_config_dir = Path(domain_config_dir_raw) if domain_config_dir_raw else None

    return {
        "domain": domain,
        "mode": mode,
        "start_date": start_date,
        "end_date": end_date,
        "project_dir": project_dir,
        "seed": seed,
        "domain_config_dir": domain_config_dir,
    }


# ---------------------------------------------------------------------------
# Date range helpers
# ---------------------------------------------------------------------------

def date_range(start: date, end: date):
    """Yield each date from start to end inclusive."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def total_days(start: date, end: date) -> int:
    return (end - start).days + 1


# ---------------------------------------------------------------------------
# Daily mode — runs one day at a time, maintains checkpoint
# ---------------------------------------------------------------------------

def run_daily(cfg: dict) -> None:
    """Loop through start_date..end_date, generating one day at a time."""
    from run_day import run_retail_day, run_healthcare_day, load_checkpoint

    domain      = cfg["domain"]
    start       = cfg["start_date"]
    end         = cfg["end_date"]
    project_dir = cfg["project_dir"]
    seed        = cfg["seed"]
    config_dir  = cfg["domain_config_dir"]
    days        = total_days(start, end)

    print(f"")
    print(f"  Domain      : {domain}")
    print(f"  Mode        : daily (one day per step)")
    print(f"  Date range  : {start} → {end}  ({days} days)")
    print(f"  Project dir : {project_dir}")
    print(f"  Config dir  : {config_dir or 'built-in defaults'}")
    print(f"")

    # Check existing checkpoint — resume from where we left off
    checkpoint = load_checkpoint(project_dir)
    if checkpoint is not None:
        next_day = checkpoint + timedelta(days=1)
        if next_day > end:
            print(f"All days already generated (last checkpoint: {checkpoint}). Nothing to do.")
            return
        if next_day > start:
            print(f"Resuming from checkpoint: {checkpoint} → starting at {next_day}")
            start = next_day

    completed = 0
    failed    = 0

    for target_date in date_range(start, end):
        print(f"[{completed + 1}/{total_days(start, end)}] Generating {domain} data for {target_date} ...", end=" ", flush=True)
        try:
            if domain == "retail":
                run_retail_day(project_dir, target_date, seed, config_overrides=None)
            else:
                run_healthcare_day(project_dir, target_date, seed, config_overrides=None)
            print("OK")
            completed += 1
        except Exception as exc:
            print(f"FAILED: {exc}")
            failed += 1
            print(f"\nStopping after failure on {target_date}.")
            break

    print(f"")
    print(f"  Completed : {completed} days")
    if failed:
        print(f"  Failed    : {failed} days")
        sys.exit(1)
    else:
        print(f"  All done. Output: {project_dir / 'output'}")


# ---------------------------------------------------------------------------
# Batch mode — generates all days at once using the demo-style executor
# ---------------------------------------------------------------------------

def run_batch(cfg: dict) -> None:
    """Generate all days from start_date to end_date in a single run."""
    import shutil

    domain      = cfg["domain"]
    start       = cfg["start_date"]
    end         = cfg["end_date"]
    project_dir = cfg["project_dir"]
    seed        = cfg["seed"]
    config_dir  = cfg["domain_config_dir"]
    days        = total_days(start, end)

    from eds.platform.project.project import create_project
    from eds.platform.run.configuration import RunConfiguration
    from eds.platform.run.run import create_run
    from eds.platform.run.stop import EndOfPeriod
    from eds.platform.scheduler.scheduler import execute
    from eds.platform.time.clock import create_clock

    print(f"")
    print(f"  Domain      : {domain}")
    print(f"  Mode        : batch (all {days} days at once)")
    print(f"  Date range  : {start} → {end}")
    print(f"  Project dir : {project_dir}")
    print(f"  Config dir  : {config_dir or 'built-in defaults'}")
    print(f"")

    # Clean previous project if exists
    if project_dir.exists():
        print(f"  Removing previous project at {project_dir} ...")
        shutil.rmtree(project_dir)

    project = create_project(project_dir, name=f"{domain.title()} Project", domain=domain, seed=seed)
    clock   = create_clock(start, end=end)
    run     = create_run(project, clock, RunConfiguration(stop_condition=EndOfPeriod()))

    if domain == "retail":
        from eds.domains.retail.config import load_config
        from eds.runners.retail import RetailExecutor
        sim_config = load_config(config_dir)
        executor   = RetailExecutor(config=sim_config)
    else:
        from eds.domains.healthcare.config import load_config
        from eds.runners.healthcare import HealthcareExecutor
        sim_config = load_config(config_dir)
        executor   = HealthcareExecutor(config=sim_config)

    print(f"  Running simulation ...")
    report = execute(run, executor)

    print(f"")
    print(f"  Status: {report.result.status.name}")
    print(f"  Stages completed: {report.progress.completed_stages}/{report.progress.total_stages}")
    for stage in report.result.stages:
        icon = "[OK]" if stage.status.name == "COMPLETED" else "[FAIL]"
        rows = sum(stage.rows_by_dataset.values()) if stage.rows_by_dataset else 0
        print(f"    {icon} {stage.stage_id}: {rows:,} rows")
        if stage.failure:
            print(f"         FAILURE: {stage.failure.message}")

    if report.result.status.name != "COMPLETED":
        print("\nERROR: Batch run did not complete successfully.")
        sys.exit(1)

    print(f"\n  Done. Output: {project_dir}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="EDS Data Generator — config-driven runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate.py                          # uses ./generate.yaml
  python generate.py --config /config/generate.yaml
        """,
    )
    parser.add_argument(
        "--config", "-c",
        default="generate.yaml",
        type=Path,
        help="Path to generate.yaml (default: ./generate.yaml)",
    )
    args = parser.parse_args()

    print(f"EDS Generator — reading config from: {args.config}")
    print("=" * 60)

    cfg = load_generate_config(args.config)

    if cfg["mode"] == "daily":
        run_daily(cfg)
    else:
        run_batch(cfg)


if __name__ == "__main__":
    main()
