"""Generate diagnosis records."""

from __future__ import annotations

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_diagnoses"]


def generate_diagnoses(
    config, encounters: pl.DataFrame, upstream: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "diagnoses")
    diagnosis_code_ids = upstream["diagnosis_codes"]["diagnosis_code_id"].to_list()
    diagnosis_types = ["PRIMARY", "SECONDARY", "COMPLICATION"]

    rows = []
    diagnosis_id = 1
    for encounter_row in encounters.iter_rows():
        if rng.random() < 0.8:
            num_diagnoses = rng.randint(1, 3)
            for _ in range(num_diagnoses):
                rows.append({
                    "diagnosis_id": diagnosis_id,
                    "encounter_id": encounter_row[0],
                    "patient_id": encounter_row[2],
                    "provider_id": encounter_row[3],
                    "diagnosis_code_id": rng.choice(diagnosis_code_ids),
                    "diagnosis_type": rng.choice(diagnosis_types),
                    "onset_date": f"{config.reference_date.year - rng.randint(0, 365)}-01-01",
                    "status": "CONFIRMED",
                    "recorded_at": f"{encounter_row[7]} 10:00:00",
                    "created_at": config.reference_date.isoformat(),
                })
                diagnosis_id += 1

    return pl.DataFrame(rows)
