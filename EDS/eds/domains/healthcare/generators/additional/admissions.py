"""Generate admissions dataset."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import make_rng, resolve_seed

__all__ = ["generate_admissions"]

ADMISSION_TYPES = ["EMERGENCY", "ELECTIVE", "URGENT", "OBSERVATION"]
ADMISSION_SOURCES = ["ER", "OUTPATIENT", "TRANSFER", "PHYSICIAN_REFERRAL"]
WARDS = ["ICU", "GENERAL", "PRIVATE", "SEMI_PRIVATE", "EMERGENCY"]


def generate_admissions(
    config: SimulationConfig,
    upstream: Mapping[str, pl.DataFrame],
) -> pl.DataFrame:
    seed = resolve_seed(config.platform.seed)
    rng = make_rng(seed, "admissions")

    encounters = upstream.get("encounters")
    providers = upstream.get("providers")
    if encounters is None or encounters.is_empty():
        return pl.DataFrame(schema={
            "admission_id": pl.Int64(),
            "encounter_id": pl.Int64(),
            "patient_id": pl.Int64(),
            "admission_type": pl.String(),
            "admission_source": pl.String(),
            "admitted_at": pl.Date(),
            "discharged_at": pl.Date(),
            "ward": pl.String(),
            "bed_number": pl.String(),
            "attending_physician": pl.Int64(),
        })

    n = len(encounters)
    provider_ids = [int(x) for x in providers["provider_id"].to_list()] if providers is not None and not providers.is_empty() else [1]
    rows = []
    for i in range(n):
        enc = encounters.row(i, named=True)
        admitted_at = enc["admission_date"]
        discharged_at = enc["discharge_date"]
        rows.append({
            "admission_id": int(i + 1),
            "encounter_id": int(enc["encounter_id"]),
            "patient_id": int(enc["patient_id"]),
            "admission_type": str(rng.choice(ADMISSION_TYPES)),
            "admission_source": str(rng.choice(ADMISSION_SOURCES)),
            "admitted_at": admitted_at,
            "discharged_at": discharged_at,
            "ward": str(rng.choice(WARDS)),
            "bed_number": str(f"BED-{int(rng.randint(1, 500)):03d}"),
            "attending_physician": int(rng.choice(provider_ids)),
        })

    df = pl.DataFrame(rows)
    if not df.is_empty():
        df = df.with_columns([
            pl.col("admitted_at").cast(pl.Date()),
            pl.col("discharged_at").cast(pl.Date()),
        ])
    return df
