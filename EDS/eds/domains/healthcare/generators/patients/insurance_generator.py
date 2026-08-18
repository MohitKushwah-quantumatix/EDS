"""Generate patient insurance records."""

from __future__ import annotations

from datetime import datetime, date, timedelta

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_insurance"]


def generate_insurance(
    config, patients: pl.DataFrame, master_data: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "patient_insurance")
    insurance_plans = master_data["insurance_plans"]["insurance_plan_id"].to_list()

    rows = []
    insurance_id = 1
    for patient_row in patients.iter_rows():
        patient_id = patient_row[0]
        plan_id = rng.choice(insurance_plans)
        _reg_date = patient_row[9]
        _reg_year = _reg_date.year if _reg_date else config.reference_date.year
        _eff_years_ago = rng.randint(0, 1)
        _eff_year = _reg_year - _eff_years_ago
        _exp_year = _eff_year + rng.randint(3, 5)
        effective_date = f"{_eff_year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        expiration_date = f"{_exp_year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        rows.append({
            "insurance_id": insurance_id,
            "patient_id": patient_id,
            "insurance_plan_id": plan_id,
            "policy_number": f"POL-{rng.randint(100000, 999999)}",
            "group_number": f"GRP-{rng.randint(1000, 9999)}",
            "effective_date": effective_date,
            "expiration_date": expiration_date,
            "is_primary": True,
            "created_at": datetime.strptime(effective_date, "%Y-%m-%d"),
        })
        insurance_id += 1

    df = pl.DataFrame(rows)
    if df.height > 0:
        df = df.with_columns([
            pl.col("effective_date").str.strptime(pl.Date(), "%Y-%m-%d"),
            pl.col("expiration_date").str.strptime(pl.Date(), "%Y-%m-%d"),
            pl.col("created_at").cast(pl.Datetime("us")),
        ])
    return df

