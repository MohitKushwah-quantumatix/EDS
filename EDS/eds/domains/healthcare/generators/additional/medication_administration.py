"""Generate medication_administration dataset."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import make_rng, resolve_seed

__all__ = ["generate_medication_administration"]

ROUTES = ["ORAL", "IV", "IM", "SC", "TOPICAL", "INHALATION"]


def generate_medication_administration(
    config: SimulationConfig,
    upstream: Mapping[str, pl.DataFrame],
) -> pl.DataFrame:
    seed = resolve_seed(config.platform.seed)
    rng = make_rng(seed, "medication_administration")

    encounters = upstream.get("encounters")
    medications = upstream.get("medications")
    providers = upstream.get("providers")
    if encounters is None or encounters.is_empty():
        return pl.DataFrame(schema={
            "administration_id": pl.Int64(),
            "encounter_id": pl.Int64(),
            "medication_id": pl.Int64(),
            "dose": pl.String(),
            "route": pl.String(),
            "administered_at": pl.Date(),
            "administered_by": pl.Int64(),
        })

    n = len(encounters)
    med_ids = [int(x) for x in medications["medication_id"].to_list()] if medications is not None and not medications.is_empty() else [1]
    provider_ids = [int(x) for x in providers["provider_id"].to_list()] if providers is not None and not providers.is_empty() else [1]
    rows = []
    for i in range(n):
        enc = encounters.row(i, named=True)
        rows.append({
            "administration_id": int(i + 1),
            "encounter_id": int(enc["encounter_id"]),
            "medication_id": int(rng.choice(med_ids)),
            "dose": str(f"{int(rng.choice([50, 100, 250, 500]))}mg"),
            "route": str(rng.choice(ROUTES)),
            "administered_at": enc["admission_date"],
            "administered_by": int(rng.choice(provider_ids)),
        })

    df = pl.DataFrame(rows)
    if not df.is_empty():
        df = df.with_columns(pl.col("administered_at").cast(pl.Date()))
    return df
