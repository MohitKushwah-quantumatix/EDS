"""Generate medication prescription records."""

from __future__ import annotations

from datetime import datetime

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_medications"]


def generate_medications(
    config, encounters: pl.DataFrame, upstream: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "medications_prescribed")
    medication_ids = upstream["medications"]["medication_id"].to_list()
    dosages = ["10mg", "20mg", "50mg", "100mg", "250mg", "500mg"]
    frequencies = ["OD", "BD", "TDS", "QDS", "PRN"]
    routes = ["ORAL", "IV", "IM", "SC", "TOPICAL"]
    statuses = ["ACTIVE", "COMPLETED", "DISCONTINUED"]

    rows = []
    prescription_id = 1
    for encounter_row in encounters.iter_rows():
        if rng.random() < 0.6:
            num_meds = rng.randint(1, 3)
            for _ in range(num_meds):
                rows.append({
                    "prescription_id": prescription_id,
                    "encounter_id": encounter_row[0],
                    "patient_id": encounter_row[2],
                    "provider_id": encounter_row[3],
                    "medication_id": rng.choice(medication_ids),
                    "dosage": rng.choice(dosages),
                    "frequency": rng.choice(frequencies),
                    "route": rng.choice(routes),
                    "duration_days": rng.randint(5, 90),
                    "status": rng.choice(statuses),
                    "prescribed_at": f"{encounter_row[8]} 10:00:00",
                    "created_at": f"{encounter_row[8]} 10:00:00",
                })
                prescription_id += 1

    df = pl.DataFrame(rows)
    if df.height > 0:
        df = df.with_columns([
            pl.col("prescribed_at").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S"),
            pl.col("created_at").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S"),
        ])
    return df
