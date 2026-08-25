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
        _ref_date = _reg_date if _reg_date else config.reference_date
        _eff_days_back = rng.randint(0, min((config.reference_date - date(2026, 1, 1)).days, 150))
        effective_date = (config.reference_date - timedelta(days=_eff_days_back)).isoformat()
        max_exp = (date(2026, 6, 1) - config.reference_date).days
        if max_exp > 0:
            _exp_days_after = rng.randint(1, max_exp)
        else:
            _exp_days_after = 0
        expiration_date = (config.reference_date + timedelta(days=_exp_days_after)).isoformat()
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

