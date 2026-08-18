"""Generate appointment records."""

from __future__ import annotations

from datetime import datetime

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_appointments"]


def generate_appointments(
    config, encounters: pl.DataFrame, upstream: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "appointments")
    appointment_types = ["CONSULTATION", "FOLLOW_UP", "PROCEDURE", "CHECKUP"]
    statuses = ["SCHEDULED", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW"]

    rows = []
    appointment_id = 1
    for encounter_row in encounters.iter_rows():
        if rng.random() < 0.8:
            admission_date = encounter_row[8]
            rows.append({
                "appointment_id": appointment_id,
                "encounter_id": encounter_row[0],
                "patient_id": encounter_row[2],
                "provider_id": encounter_row[3],
                "department_id": encounter_row[4],
                "appointment_type": rng.choice(appointment_types),
                "scheduled_date": admission_date,
                "start_time": f"{admission_date} {rng.randint(8, 17):02d}:00:00",
                "end_time": f"{admission_date} {rng.randint(8, 17) + 1:02d}:00:00",
                "status": rng.choice(statuses),
                "created_at": f"{admission_date} 12:00:00",
            })
            appointment_id += 1

    df = pl.DataFrame(rows)
    if df.height > 0:
        df = df.with_columns([
            pl.col("scheduled_date").cast(pl.Date()),
            pl.col("start_time").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S"),
            pl.col("end_time").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S"),
            pl.col("created_at").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S"),
        ])
    return df
