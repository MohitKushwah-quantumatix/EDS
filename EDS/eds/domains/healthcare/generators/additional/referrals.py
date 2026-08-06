"""Generate referrals dataset."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import make_rng, resolve_seed

__all__ = ["generate_referrals"]

REFERRAL_REASONS = ["Cardiac evaluation", "Dermatology consult", "Neurology assessment", "Orthopedic review", "General checkup"]


def generate_referrals(
    config: SimulationConfig,
    upstream: Mapping[str, pl.DataFrame],
) -> pl.DataFrame:
    seed = resolve_seed(config.platform.seed)
    rng = make_rng(seed, "referrals")

    encounters = upstream.get("encounters")
    providers = upstream.get("providers")
    if encounters is None or encounters.is_empty():
        return pl.DataFrame(schema={
            "referral_id": pl.Int64(),
            "patient_id": pl.Int64(),
            "encounter_id": pl.Int64(),
            "referring_provider": pl.Int64(),
            "referred_to_provider": pl.Int64(),
            "referral_reason": pl.String(),
            "referral_date": pl.Date(),
            "status": pl.String(),
        })

    n = len(encounters)
    provider_ids = [int(x) for x in providers["provider_id"].to_list()] if providers is not None and not providers.is_empty() else [1]
    rows = []
    for i in range(n):
        enc = encounters.row(i, named=True)
        ref_to = int(rng.choice(provider_ids))
        while ref_to == int(enc.get("provider_id", -1)):
            ref_to = int(rng.choice(provider_ids))
        rows.append({
            "referral_id": int(i + 1),
            "patient_id": int(enc["patient_id"]),
            "encounter_id": int(enc["encounter_id"]),
            "referring_provider": int(enc["provider_id"]),
            "referred_to_provider": ref_to,
            "referral_reason": str(rng.choice(REFERRAL_REASONS)),
            "referral_date": enc["admission_date"],
            "status": str(rng.choice(["PENDING", "COMPLETED", "CANCELLED"])),
        })

    df = pl.DataFrame(rows)
    if not df.is_empty():
        df = df.with_columns(pl.col("referral_date").cast(pl.Date()))
    return df
