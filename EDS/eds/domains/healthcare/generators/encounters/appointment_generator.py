"""Generate appointment records."""

from __future__ import annotations

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
            admission_date = encounter_row[7]
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
                "created_at": config.reference_date.isoformat(),
            })
            appointment_id += 1

    return pl.DataFrame(rows)
