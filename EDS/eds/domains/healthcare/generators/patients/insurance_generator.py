"""Generate patient insurance records."""

from __future__ import annotations

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
        rows.append({
            "insurance_id": insurance_id,
            "patient_id": patient_id,
            "insurance_plan_id": plan_id,
            "policy_number": f"POL-{rng.randint(100000, 999999)}",
            "group_number": f"GRP-{rng.randint(1000, 9999)}",
            "effective_date": f"{config.reference_date.year - rng.randint(0, 365)}-01-01",
            "expiration_date": f"{config.reference_date.year + rng.randint(0, 365)}-12-31",
            "is_primary": True,
            "created_at": config.reference_date.isoformat(),
        })
        insurance_id += 1

    return pl.DataFrame(rows)
