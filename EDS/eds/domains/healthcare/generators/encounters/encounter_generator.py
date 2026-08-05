"""Generate encounter records."""

from __future__ import annotations

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_encounters"]


def generate_encounters(
    config, upstream: dict[str, pl.DataFrame], seed: int, max_encounters_per_patient: int = 5
) -> pl.DataFrame:
    """Generate encounter records.

    Args:
        config: The encounter configuration.
        upstream: The upstream datasets (patients, providers, master_data).
        seed: The resolved random seed.
        max_encounters_per_patient: Maximum encounters per patient per day.

    Returns:
        A frame of encounter records.
    """
    rng = make_rng(seed, "encounters")
    patients = upstream["patients"]
    providers = upstream["providers"]
    departments = upstream["departments"]
    facilities = upstream["facilities"]

    patient_ids = patients["patient_id"].to_list()
    provider_ids = providers["provider_id"].to_list()
    department_ids = departments["department_id"].to_list()
    facility_ids = facilities["facility_id"].to_list()

    encounter_types = ["INPATIENT", "OUTPATIENT", "EMERGENCY", "TELEHEALTH"]
    admit_sources = ["EMERGENCY", "REFERRAL", "TRANSFER", "DIRECT_ADMIT"]
    statuses = ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    dispositions = ["HOME", "TRANSFER", "DECEASED", "LEFT_AMALGAMATED"]

    rows = []
    encounter_id = 1
    for patient_id in patient_ids:
        num_encounters = rng.randint(1, max_encounters_per_patient)
        for _ in range(num_encounters):
            encounter_type = rng.choice(encounter_types)
            status = rng.choice(statuses)
            admission_year = config.reference_date.year - rng.randint(0, 1)
            admission_month = rng.randint(1, 12)
            admission_day = rng.randint(1, 28)
            admission_date = f"{admission_year}-{admission_month:02d}-{admission_day:02d}"
            discharge_date = None
            if encounter_type == "INPATIENT":
                discharge_day = min(admission_day + rng.randint(1, 30), 28)
                discharge_date = f"{admission_year}-{admission_month:02d}-{discharge_day:02d}"

            rows.append({
                "encounter_id": encounter_id,
                "encounter_number": f"ENC-{encounter_id:06d}",
                "patient_id": patient_id,
                "provider_id": rng.choice(provider_ids),
                "department_id": rng.choice(department_ids),
                "encounter_type": encounter_type,
                "admit_source": rng.choice(admit_sources) if encounter_type == "INPATIENT" else None,
                "status": status,
                "admission_date": admission_date,
                "discharge_date": discharge_date,
                "discharge_disposition": rng.choice(dispositions) if discharge_date else None,
                "facility_id": rng.choice(facility_ids),
                "room_number": f"R{rng.randint(100, 999)}",
                "bed_number": f"B{rng.randint(1, 10)}",
                "created_at": config.reference_date.isoformat(),
            })
            encounter_id += 1

    return pl.DataFrame(rows)

