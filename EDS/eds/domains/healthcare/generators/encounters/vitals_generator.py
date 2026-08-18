"""Generate vital signs records."""

from __future__ import annotations

from datetime import datetime

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_vitals"]


def generate_vitals(
    config, encounters: pl.DataFrame, upstream: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "vitals")

    rows = []
    vital_id = 1
    for encounter_row in encounters.iter_rows():
        if rng.random() < 0.9:
            admission_date = encounter_row[8]
            rows.append({
                "vital_id": vital_id,
                "encounter_id": encounter_row[0],
                "patient_id": encounter_row[2],
                "temperature": round(rng.uniform(36.0, 40.0), 1),
                "heart_rate": rng.randint(60, 120),
                "blood_pressure_systolic": rng.randint(100, 160),
                "blood_pressure_diastolic": rng.randint(60, 100),
                "respiratory_rate": rng.randint(12, 30),
                "oxygen_saturation": round(rng.uniform(90.0, 100.0), 1),
                "height_cm": round(rng.uniform(150.0, 190.0), 1),
                "weight_kg": round(rng.uniform(50.0, 120.0), 1),
                "bmi": round(rng.uniform(18.0, 35.0), 1),
                "recorded_at": f"{admission_date} 10:00:00",
                "created_at": f"{admission_date} 10:00:00",
            })
            vital_id += 1

    df = pl.DataFrame(rows)
    if df.height > 0:
        df = df.with_columns([
            pl.col("recorded_at").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S"),
            pl.col("created_at").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S"),
        ])
    return df
