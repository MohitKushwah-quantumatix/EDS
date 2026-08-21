"""Generate immunizations dataset."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import make_rng, resolve_seed

__all__ = ["generate_immunizations"]

VACCINES = ["COVID-19", "Influenza", "Hepatitis B", "Tetanus", "Pneumococcal", "HPV", "MMR", "Varicella"]
SITES = ["LEFT_ARM", "RIGHT_ARM", "LEFT_THIGH", "RIGHT_THIGH", "ABDOMEN"]


def generate_immunizations(
    config: SimulationConfig,
    upstream: Mapping[str, pl.DataFrame],
) -> pl.DataFrame:
    seed = resolve_seed(config.platform.seed)
    rng = make_rng(seed, "immunizations")

    patients = upstream.get("patients")
    providers = upstream.get("providers")
    if patients is None or patients.is_empty():
        return pl.DataFrame(schema={
            "immunization_id": pl.Int64(),
            "patient_id": pl.Int64(),
            "vaccine_name": pl.String(),
            "dose_number": pl.Int64(),
            "administered_at": pl.Date(),
            "administered_by": pl.Int64(),
            "site": pl.String(),
            "lot_number": pl.String(),
        })

    n = len(patients)
    provider_ids = [int(x) for x in providers["provider_id"].to_list()] if providers is not None and not providers.is_empty() else [1]
    rows = []
    for i in range(n):
        pat = patients.row(i, named=True)
        rows.append({
            "immunization_id": int(i + 1),
            "patient_id": int(pat["patient_id"]),
            "vaccine_name": str(rng.choice(VACCINES)),
            "dose_number": int(rng.randint(1, 4)),
            "administered_at": config.patients.reference_date,
            "administered_by": int(rng.choice(provider_ids)),
            "site": str(rng.choice(SITES)),
            "lot_number": str(f"LOT-{int(rng.randint(10000, 99999))}"),
        })

    df = pl.DataFrame(rows)
    if not df.is_empty():
        df = df.with_columns(pl.col("administered_at").cast(pl.Date()))
    return df
