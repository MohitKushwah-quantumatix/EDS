"""Generate discharge_summaries dataset."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import make_rng, resolve_seed

__all__ = ["generate_discharge_summaries"]

DISCHARGE_DIAGNOSES = ["Acute Appendicitis", "Pneumonia", "Hypertension", "Diabetes Type 2", "Fracture", "Infection", "Cardiac Arrhythmia"]
INSTRUCTIONS = [
    "Complete rest, avoid heavy lifting",
    "Complete antibiotics course",
    "Monitor BP daily",
    "Follow up in 2 weeks",
    "Physical therapy recommended",
    "Dietary changes advised",
    "Return if symptoms worsen",
]


def generate_discharge_summaries(
    config: SimulationConfig,
    upstream: Mapping[str, pl.DataFrame],
) -> pl.DataFrame:
    seed = resolve_seed(config.platform.seed)
    rng = make_rng(seed, "discharge_summaries")

    encounters = upstream.get("encounters")
    providers = upstream.get("providers")
    if encounters is None or encounters.is_empty():
        return pl.DataFrame(schema={
            "discharge_id": pl.Int64(),
            "encounter_id": pl.Int64(),
            "patient_id": pl.Int64(),
            "discharge_diagnosis": pl.String(),
            "discharge_instructions": pl.String(),
            "follow_up_date": pl.Date(),
            "follow_up_physician": pl.Int64(),
            "discharge_disposition": pl.String(),
        })

    n = len(encounters)
    provider_ids = [int(x) for x in providers["provider_id"].to_list()] if providers is not None and not providers.is_empty() else [1]
    rows = []
    for i in range(n):
        enc = encounters.row(i, named=True)
        follow_up_date = enc["discharge_date"]
        rows.append({
            "discharge_id": int(i + 1),
            "encounter_id": int(enc["encounter_id"]),
            "patient_id": int(enc["patient_id"]),
            "discharge_diagnosis": str(rng.choice(DISCHARGE_DIAGNOSES)),
            "discharge_instructions": str(rng.choice(INSTRUCTIONS)),
            "follow_up_date": follow_up_date,
            "follow_up_physician": int(rng.choice(provider_ids)),
            "discharge_disposition": str(rng.choice(["HOME", "TRANSFER", "EXPIRED", "LEFT_AMA", "OTHER"])),
        })

    df = pl.DataFrame(rows)
    if not df.is_empty():
        df = df.with_columns(pl.col("follow_up_date").cast(pl.Date()))
    return df
