"""Generate provider-specialty mapping records."""

from __future__ import annotations

from datetime import datetime, timedelta, date

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_provider_specialties"]


def generate_provider_specialties(
    config, providers: pl.DataFrame, master_data: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "provider_specialties")
    specialty_ids = master_data["specialties"]["specialty_id"].to_list()

    rows = []
    ps_id = 1
    for provider_row in providers.iter_rows():
        provider_id = provider_row[0]
        num_specs = rng.randint(config.min_specialties, config.max_specialties)
        chosen = [specialty_ids[rng.randint(0, len(specialty_ids) - 1)] for _ in range(num_specs)]
        for specialty_id in chosen:
            max_lookback = (config.reference_date - date(2026, 1, 1)).days
            cert_date = (config.reference_date - timedelta(days=rng.randint(0, max_lookback))).isoformat()
            rows.append({
                "provider_specialty_id": ps_id,
                "provider_id": provider_id,
                "specialty_id": specialty_id,
                "certification_date": cert_date,
                "effective_date": datetime.strptime(cert_date, "%Y-%m-%d").date(),
                "end_date": None,
                "created_at": datetime.strptime(cert_date, "%Y-%m-%d"),
            })
            ps_id += 1

    df = pl.DataFrame(rows)
    if df.height > 0:
        df = df.with_columns([
            pl.col("certification_date").str.strptime(pl.Date(), "%Y-%m-%d"),
            pl.col("effective_date").cast(pl.Date()),
            pl.col("end_date").cast(pl.Date()),
            pl.col("created_at").cast(pl.Datetime("us")),
        ])
    return df
