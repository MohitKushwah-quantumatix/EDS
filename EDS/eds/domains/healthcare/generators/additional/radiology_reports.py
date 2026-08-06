"""Generate radiology_reports dataset."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import make_rng, resolve_seed

__all__ = ["generate_radiology_reports"]

MODALITIES = ["X-RAY", "CT", "MRI", "ULTRASOUND", "PET", "MAMMOGRAPHY"]
BODY_PARTS = ["CHEST", "BRAIN", "SPINE", "ABDOMEN", "PELVIS", "EXTREMITY", "HEAD", "NECK"]
FINDINGS = ["Clear lungs", "No acute changes", "Mild degeneration", "Normal", "Fracture noted", "Mass detected", "Inflammation present"]
IMPRESSIONS = ["Normal", "Mild degeneration", "Acute changes", "Chronic changes", "Requires follow-up"]


def generate_radiology_reports(
    config: SimulationConfig,
    upstream: Mapping[str, pl.DataFrame],
) -> pl.DataFrame:
    seed = resolve_seed(config.platform.seed)
    rng = make_rng(seed, "radiology_reports")

    encounters = upstream.get("encounters")
    providers = upstream.get("providers")
    if encounters is None or encounters.is_empty():
        return pl.DataFrame(schema={
            "radiology_id": pl.Int64(),
            "encounter_id": pl.Int64(),
            "patient_id": pl.Int64(),
            "modality": pl.String(),
            "body_part": pl.String(),
            "findings": pl.String(),
            "impression": pl.String(),
            "performed_at": pl.Date(),
            "radiologist_id": pl.Int64(),
        })

    n = len(encounters)
    rows = []
    provider_ids = [int(x) for x in providers["provider_id"].to_list()] if providers is not None and not providers.is_empty() else [1]
    for i in range(n):
        enc = encounters.row(i, named=True)
        rows.append({
            "radiology_id": int(i + 1),
            "encounter_id": int(enc["encounter_id"]),
            "patient_id": int(enc["patient_id"]),
            "modality": str(rng.choice(MODALITIES)),
            "body_part": str(rng.choice(BODY_PARTS)),
            "findings": str(rng.choice(FINDINGS)),
            "impression": str(rng.choice(IMPRESSIONS)),
            "performed_at": enc["admission_date"],
            "radiologist_id": int(rng.choice(provider_ids)),
        })

    df = pl.DataFrame(rows)
    if not df.is_empty():
        df = df.with_columns(pl.col("performed_at").cast(pl.Date()))
    return df
