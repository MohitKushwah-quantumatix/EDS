"""
EDS Date-Range Generator
========================
Give it a start date and end date, and it simulates data *day by day* —
exactly as if Aug 25 data was generated on Aug 25, Aug 26 on Aug 26, etc.

Usage
-----
  python generate_date_range.py --start 2026-08-25 --end 2026-08-30

Output
------
  <project-dir>/
  ├── manifest.json         project identity + seed
  ├── state.json            current_date + completed stages
  └── data/                 all Parquet files (one store of record, appended each tick)

The script reads today's real date and automatically sizes the run
to cover only the days from --start up to today (or --end, whichever
is earlier).  That lets you call it on a daily schedule and it will
always catch up to "today".
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# EDS imports
# ---------------------------------------------------------------------------
from eds.domains.retail.config import load_config
from eds.platform.project.project import create_project
from eds.platform.run.configuration import RunConfiguration
from eds.platform.run.run import create_run
from eds.platform.run.stop import EndOfPeriod
from eds.platform.scheduler.scheduler import execute
from eds.platform.time.clock import create_clock
from eds.runners.retail import RetailExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}'. Use YYYY-MM-DD format.")


def _days_between(start: date, end: date) -> int:
    return (end - start).days + 1          # inclusive on both ends


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate EDS data for a date range, one tick (day) at a time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--start",
        required=True,
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="First day to simulate (e.g. 2026-08-25).",
    )
    parser.add_argument(
        "--end",
        required=True,
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="Last day to simulate (e.g. 2026-08-30).",
    )
    parser.add_argument(
        "--output",
        default="./eds-output",
        metavar="DIR",
        help="Directory where the project (manifest, state, data/) is written. "
             "Default: ./eds-output",
    )
    parser.add_argument(
        "--customers",
        type=int,
        default=None,
        metavar="N",
        help="Override customer count (smaller = faster, e.g. --customers 50).",
    )
    parser.add_argument(
        "--products",
        type=int,
        default=None,
        metavar="N",
        help="Override product count.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility. Default: 42.",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        metavar="DIR",
        help="Path to the directory containing your YAML config files. "
             "Defaults to the EDS built-in configs.",
    )

    args = parser.parse_args()

    start: date = args.start
    end: date   = args.end

    # Clamp 'end' to today -- so a daily scheduled run never tries to simulate
    # future days that haven't happened yet.
    today = date.today()
    if end > today:
        print(f"[info] --end {end} is in the future; clamping to today ({today}).")
        end = today

    if end < start:
        print(
            f"[error] --start {start} is after --end {end}.  Nothing to do.",
            file=sys.stderr,
        )
        sys.exit(1)

    total_days = _days_between(start, end)
    print(f"[eds] Simulating {total_days} day(s): {start}  ->  {end}")
    print(f"[eds] Output directory : {Path(args.output).resolve()}")
    print(f"[eds] Seed             : {args.seed}")
    print()

    # ------------------------------------------------------------------
    # Load and (optionally) override the EDS configuration
    # ------------------------------------------------------------------
    config_dir = Path(args.config_dir) if args.config_dir else None
    config = load_config(config_dir)

    # Apply scale overrides so a quick test run finishes fast
    overrides: dict = {}
    if args.customers is not None:
        overrides["customers"] = config.customers.model_copy(
            update={"customer_count": args.customers}
        )
    if args.products is not None:
        overrides["master_data"] = config.master_data.model_copy(
            update={"product_count": args.products}
        )
    if overrides:
        config = config.model_copy(update=overrides)

    # ------------------------------------------------------------------
    # Build the project, clock, and run
    # ------------------------------------------------------------------
    output_dir = Path(args.output)

    # create_project is idempotent -- if the directory already exists it
    # just opens the existing project (safe for daily re-runs).
    project = create_project(
        output_dir,
        name="EDS Date-Range Run",
        domain="retail",
        seed=args.seed,
    )

    # create_clock(start, end=end) gives us a DAILY tick clock that
    # runs from `start` to `end` inclusive.
    clock = create_clock(start, end=end)

    # EndOfPeriod: keep ticking until the clock reaches `end`.
    run = create_run(
        project,
        clock,
        RunConfiguration(stop_condition=EndOfPeriod()),
    )

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    print(f"[eds] Running {total_days} tick(s) ...")
    report = execute(run, RetailExecutor(config=config))

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    print()
    print(f"[eds] Status : {report.result.status.value}")
    print(f"[eds] Ticks  : {report.progress.completed_ticks} completed")
    print()

    if not report.succeeded:
        f = report.result.failure
        print(f"[error] {f.failure_type}: {f.message}", file=sys.stderr)
        if f.cause:
            print(f"        cause: {f.cause}", file=sys.stderr)
        sys.exit(1)

    # Per-stage summary
    print("Stage results:")
    for stage in report.result.stages:
        rows = sum(stage.rows_by_dataset.values())
        print(
            f"  {stage.stage_id:<30}  {stage.status.value:<12}  "
            f"{stage.start_date} -> {stage.end_date}   {rows:>8,} rows"
        )

    print()
    data_dir = output_dir / "data"
    parquet_files = list(data_dir.glob("*.parquet")) if data_dir.exists() else []
    print(f"[eds] {len(parquet_files)} Parquet file(s) written to: {data_dir.resolve()}")
    print()
    print("[eds] Done.")


if __name__ == "__main__":
    main()
