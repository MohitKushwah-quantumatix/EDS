"""Run the retail or healthcare simulation for exactly one day.

Uses an in-memory SQLite database for simulation history (no cumulative
parquet files on disk). After each day, the new rows are exported to a
date-stamped folder and a JSON backup is saved for crash recovery.

Usage:
    python run_day.py --domain retail --date 2026-01-01
    python run_day.py --domain healthcare --date 2026-01-01
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import polars as pl
from eds.adapters.base import DatasetReader, DatasetWriter
from eds.adapters.sqlite.adapter import SQLiteAdapter
from eds.platform.project.project import create_project, open_project
from eds.platform.run.configuration import RunConfiguration
from eds.platform.run.run import create_run
from eds.platform.run.stop import AfterTicks
from eds.platform.scheduler.scheduler import execute
from eds.platform.time.clock import create_clock


INTERNAL_DIR = ".internal"
CHECKPOINT_FILE = "daily_checkpoint.json"
BACKUP_FILE = "backup.json"
LOADED_MARKER = ".loaded"

DATE_COLUMN_PREFERENCES = (
    "created_at",
    "order_date",
    "registration_date",
    "admission_date",
    "admitted_at",
    "scheduled_date",
    "recorded_at",
    "prescribed_at",
    "onset_date",
    "performed_at",
    "reported_at",
    "administered_at",
    "referral_date",
    "billing_date",
    "submitted_date",
    "processed_date",
    "follow_up_date",
    "hire_date",
    "certification_date",
    "effective_date",
    "start_date",
)

MASTER_DATA_TABLES = {
    "retail": {
        "countries", "states", "cities", "products", "brands",
        "suppliers", "warehouses", "categories", "coupon_types",
        "customer_addresses", "customer_preferences", "inventory",
        "payment_methods", "return_reasons", "shipping_methods",
        "tax_codes",
    },
    "healthcare": {
        "countries", "states", "cities", "departments", "specialties",
        "insurance_plans", "room_types", "medications", "diagnosis_codes",
        "procedure_codes", "billing_codes", "facilities", "providers",
    },
}


def _checkpoint_path(project_dir: Path) -> Path:
    return project_dir / CHECKPOINT_FILE


def load_checkpoint(project_dir: Path) -> date | None:
    import json
    path = _checkpoint_path(project_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return date.fromisoformat(data["last_completed_day"]) if data.get("last_completed_day") else None
    except Exception:
        return None


def save_checkpoint(project_dir: Path, completed_day: date) -> None:
    import json
    path = _checkpoint_path(project_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_completed_day": completed_day.isoformat()}, f)


def _backup_path(project_dir: Path) -> Path:
    return project_dir / INTERNAL_DIR / BACKUP_FILE


def save_backup(project_dir: Path, adapter: SQLiteAdapter, domain: str, completed_day: date) -> None:
    """Save backup metadata and last entry of each table for crash recovery."""
    from datetime import datetime, timezone
    backup_path = _backup_path(project_dir)
    all_data = adapter.read_all()

    backup = {
        "domain": domain,
        "last_completed_day": completed_day.isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "last_entries": {},
        "schema": {},
    }

    for name, df in all_data.items():
        if name.startswith("_"):
            continue
        if df.is_empty():
            continue
        backup["schema"][name] = {col: str(dtype) for col, dtype in df.schema.items()}
        last_row = df.tail(1).to_dicts()
        if last_row:
            backup["last_entries"][name] = last_row[0]

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2, default=str)


def load_backup(project_dir: Path, adapter: SQLiteAdapter) -> date | None:
    """Read backup file and return last completed day for crash recovery."""
    backup_path = _backup_path(project_dir)
    if not backup_path.exists():
        return None

    try:
        backup = json.loads(backup_path.read_text())
    except Exception:
        return None

    last_day = backup.get("last_completed_day")
    if last_day:
        try:
            return date.fromisoformat(last_day)
        except Exception:
            pass
    return None




def _prepare_project(project_dir: Path, domain: str, seed: int) -> "Project":
    if not project_dir.exists() or not (project_dir / "manifest.json").exists():
        return create_project(project_dir, name=f"{domain.title()} Project", domain=domain, seed=seed)
    return open_project(project_dir)


def _prepare_workspace(project_dir: Path) -> None:
    (project_dir / "data").mkdir(parents=True, exist_ok=True)


def _apply_config_overrides(config, overrides: dict):
    """Apply generic config overrides to a SimulationConfig."""
    updates = {}
    for key, value in overrides.items():
        if hasattr(config, key):
            current = getattr(config, key)
            if hasattr(current, "model_copy"):
                overrides_inner = value if isinstance(value, dict) else {}
                updates[key] = current.model_copy(update=overrides_inner)
            else:
                updates[key] = value
    if updates:
        return config.model_copy(update=updates)
    return config


def _apply_healthcare_config_overrides(config, overrides: dict):
    """Apply healthcare-specific config overrides."""
    section_map = {
        "master_data": "master_data",
        "patients": "patients",
        "providers": "providers",
        "encounters": "encounters",
        "billing": "billing",
        "evolution": "evolution",
    }
    updates = {}
    for key, section_name in section_map.items():
        if key in overrides and hasattr(config, section_name):
            current = getattr(config, section_name)
            updates[section_name] = current.model_copy(update=overrides[key])
    if updates:
        return config.model_copy(update=updates)
    return config


def _create_sqlite_adapter(project_dir: Path, domain: str) -> SQLiteAdapter:
    internal_dir = project_dir / INTERNAL_DIR
    internal_dir.mkdir(parents=True, exist_ok=True)
    db_path = internal_dir / "simulation.db"
    return SQLiteAdapter(db_path=db_path)


def _pick_date_column(df: pl.DataFrame) -> str | None:
    for name in DATE_COLUMN_PREFERENCES:
        if name in df.columns:
            dtype = str(df.schema[name]).lower()
            if "date" in dtype or "datetime" in dtype:
                return name
    for col, dtype in df.schema.items():
        if "date" in str(dtype).lower() or "datetime" in str(dtype).lower():
            return col
    return None


def _export_daily_data(adapter: SQLiteAdapter, project_dir: Path, domain: str, target_date: date, is_first_day: bool) -> Path:
    output_dir = project_dir / "output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_data = adapter.read_all()
    master_tables = MASTER_DATA_TABLES.get(domain, set())

    schema = {}

    for name, df in all_data.items():
        if name.startswith("_"):
            continue

        schema[name] = {col: str(dtype) for col, dtype in df.schema.items()}

        if df.is_empty():
            dest = output_dir / f"{name}.parquet"
            df.write_parquet(dest, compression="snappy")
            continue

        if name in master_tables:
            dest = output_dir / f"{name}.parquet"
            df.write_parquet(dest, compression="snappy")
            continue

        date_col = _pick_date_column(df)
        if date_col is None:
            dest = output_dir / f"{name}.parquet"
            df.write_parquet(dest, compression="snappy")
            continue

        col_type = str(df.schema[date_col]).lower()
        if "datetime" in col_type:
            filtered = df.filter(pl.col(date_col).dt.date().cast(pl.String) == target_date.isoformat())
        else:
            filtered = df.filter(pl.col(date_col).cast(pl.String) == target_date.isoformat())

        dest = output_dir / f"{name}.parquet"
        filtered.write_parquet(dest, compression="snappy")

    schema_path = project_dir / "schema.json"
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, default=str)

    return output_dir


def _cleanup_previous_day(project_dir: Path, current_date: date) -> None:
    output_dir = project_dir / "output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
        print(f"  Cleaned up previous output folder")


def _mark_loaded(project_dir: Path, target_date: date) -> None:
    marker = project_dir / "output" / LOADED_MARKER
    with open(marker, "w", encoding="utf-8") as f:
        f.write("loaded")


def run_retail_day(project_dir: Path, target_date: date, seed: int = 42, config_overrides: dict | None = None) -> None:
    from eds.domains.retail.config import load_config
    from eds.runners.retail import RetailExecutor

    config = load_config()
    if config_overrides:
        config = _apply_config_overrides(config, config_overrides)

    project = _prepare_project(project_dir, "retail", seed)
    _prepare_workspace(project_dir)
    adapter = _create_sqlite_adapter(project_dir, "retail")

    checkpoint = load_checkpoint(project_dir)
    is_first_day = checkpoint is None

    if is_first_day:
        restored_day = load_backup(project_dir, adapter)
        if restored_day is not None:
            checkpoint = restored_day
            is_first_day = False
            print(f"  Restored from backup: resuming after {restored_day.isoformat()}")

    executor = RetailExecutor(config=config, reader=adapter, writer=adapter)

    run = create_run(
        project,
        create_clock(target_date, end=target_date + timedelta(days=1)),
        RunConfiguration(stop_condition=AfterTicks(1)),
        run_id=f"retail-{target_date.isoformat()}",
    )

    report = execute(run, executor)
    if report.result.status.name != "COMPLETED":
        raise RuntimeError(f"retail day {target_date} failed: {report.result.stages}")

    _export_daily_data(adapter, project_dir, "retail", target_date, is_first_day)
    save_checkpoint(project_dir, target_date)
    save_backup(project_dir, adapter, "retail", target_date)
    _mark_loaded(project_dir, target_date)


def run_healthcare_day(project_dir: Path, target_date: date, seed: int = 42, config_overrides: dict | None = None) -> None:
    from eds.domains.healthcare.config import load_config
    from eds.runners.healthcare import HealthcareExecutor

    config = load_config()
    if config_overrides:
        config = _apply_healthcare_config_overrides(config, config_overrides)

    project = _prepare_project(project_dir, "healthcare", seed)
    _prepare_workspace(project_dir)
    adapter = _create_sqlite_adapter(project_dir, "healthcare")

    checkpoint = load_checkpoint(project_dir)
    is_first_day = checkpoint is None

    if is_first_day:
        restored_day = load_backup(project_dir, adapter)
        if restored_day is not None:
            checkpoint = restored_day
            is_first_day = False
            print(f"  Restored from backup: resuming after {restored_day.isoformat()}")

    executor = HealthcareExecutor(config=config, reader=adapter, writer=adapter)

    run = create_run(
        project,
        create_clock(target_date, end=target_date + timedelta(days=1)),
        RunConfiguration(stop_condition=AfterTicks(1)),
        run_id=f"healthcare-{target_date.isoformat()}",
    )

    report = execute(run, executor)
    if report.result.status.name != "COMPLETED":
        raise RuntimeError(f"healthcare day {target_date} failed: {report.result.stages}")

    _export_daily_data(adapter, project_dir, "healthcare", target_date, is_first_day)
    save_checkpoint(project_dir, target_date)
    save_backup(project_dir, adapter, "healthcare", target_date)
    _mark_loaded(project_dir, target_date)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one day of simulation")
    parser.add_argument("--domain", required=True, choices=["retail", "healthcare"])
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    domain_defaults = {
        "retail": Path("my-shop"),
        "healthcare": Path("my-hospital"),
    }
    project_dir = Path(args.project_dir) if args.project_dir else domain_defaults[args.domain]

    if args.domain == "retail":
        run_retail_day(project_dir, args.date, args.seed)
    else:
        run_healthcare_day(project_dir, args.date, args.seed)


if __name__ == "__main__":
    main()
