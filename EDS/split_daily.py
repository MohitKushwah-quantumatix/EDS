"""Split cumulative simulation data into a single daily folder.

Usage:
    python split_daily.py --domain retail --date 2026-01-01
    python split_daily.py --domain healthcare --date 2026-01-01
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import polars as pl

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


def _is_date_like(value) -> bool:
    if value is None:
        return False
    return hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day")


def split_day(project_dir: Path, domain: str, target_date: date) -> Path:
    daily_dir = project_dir / target_date.isoformat()
    daily_dir.mkdir(parents=True, exist_ok=True)

    data_dir = project_dir / "data"
    if not data_dir.exists():
        return daily_dir

    parquet_files = sorted(data_dir.glob("*.parquet"))
    if not parquet_files:
        return daily_dir

    master_data_tables = {
        "retail": {"countries", "states", "cities", "products", "brands", "suppliers", "warehouses", "categories"},
        "healthcare": {
            "countries",
            "states",
            "cities",
            "departments",
            "specialties",
            "insurance_plans",
            "room_types",
            "medications",
            "diagnosis_codes",
            "procedure_codes",
            "billing_codes",
            "facilities",
        },
    }
    master_tables = master_data_tables.get(domain, set())
    existing_daily_dirs = [d for d in project_dir.iterdir() if d.is_dir() and d.name != "data"] if project_dir.exists() else []
    is_first_day = len(existing_daily_dirs) == 0

    for src in parquet_files:
        stem = src.stem
        if stem in master_tables and not is_first_day:
            continue

        df = pl.read_parquet(src)
        if df.is_empty():
            continue

        date_col = _pick_date_column(df)
        if date_col is None:
            continue

        col_type = str(df.schema[date_col]).lower()
        if "datetime" in col_type:
            filtered = df.filter(pl.col(date_col).dt.date() == target_date)
        else:
            filtered = df.filter(pl.col(date_col) == target_date)

        if filtered.is_empty():
            continue

        dest = daily_dir / src.name
        filtered.write_parquet(dest)

    return daily_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Split cumulative data into a daily folder")
    parser.add_argument("--domain", required=True, choices=["retail", "healthcare"])
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--project-dir", default=None)
    args = parser.parse_args()

    domain_defaults = {
        "retail": Path("my-shop"),
        "healthcare": Path("my-hospital"),
    }
    project_dir = Path(args.project_dir) if args.project_dir else domain_defaults[args.domain]
    split_day(project_dir, args.domain, args.date)


if __name__ == "__main__":
    main()
