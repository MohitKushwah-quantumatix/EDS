"""Generate provider demographic records."""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_providers"]


def generate_providers(
    config, master_data: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "providers")
    departments = master_data["departments"]
    specialties = master_data["specialties"]
    department_ids = departments["department_id"].to_list()
    specialty_ids = specialties["specialty_id"].to_list()

    first_names = ["Raj", "Priya", "Aditya", "Kavya", "Aarav", "Ananya", "Diya", "Riya", "Saanvi", "Vihaan"]
    last_names = ["Sharma", "Patel", "Singh", "Kumar", "Gupta", "Verma", "Reddy", "Joshi", "Iyer", "Kapoor"]

    rows = []
    for i in range(1, config.provider_count + 1):
        department_id = rng.choice(department_ids)
        specialty_id = rng.choice(specialty_ids)
        provider_type = rng.choice(["PHYSICIAN", "NURSE", "SPECIALIST", "TECHNICIAN", "ADMIN", "SURGEON", "ANESTHETIST", "RADIOLOGIST", "LAB_TECHNICIAN", "PHARMACIST", "RESIDENT", "FELLOW", "COORDINATOR", "THERAPIST", "ATTENDING"])
        first_name = rng.choice(first_names)
        last_name = rng.choice(last_names)
        from datetime import timedelta, date
        max_lookback = (config.reference_date - date(2026, 1, 1)).days
        hire_days_back = rng.randint(0, max_lookback)
        hire_date = (config.reference_date - timedelta(days=hire_days_back)).isoformat()
        rows.append({
            "provider_id": i,
            "provider_number": f"PROV-{i:06d}",
            "first_name": first_name,
            "last_name": last_name,
            "full_name": f"{first_name} {last_name}",
            "provider_type": provider_type,
            "specialty_id": specialty_id,
            "department_id": department_id,
            "license_number": f"LIC-{rng.randint(100000, 999999)}",
            "status": "ACTIVE",
            "hire_date": hire_date,
            "termination_date": None,
            "created_at": datetime.strptime(hire_date, "%Y-%m-%d"),
        })

    df = pl.DataFrame(rows)
    if df.height > 0:
        df = df.with_columns([
            pl.col("hire_date").str.strptime(pl.Date(), "%Y-%m-%d"),
            pl.col("termination_date").cast(pl.Date()),
            pl.col("created_at").cast(pl.Datetime("us")),
        ])
    return df

