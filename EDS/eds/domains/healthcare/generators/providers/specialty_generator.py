"""Generate provider-specialty mapping records."""

from __future__ import annotations

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
            rows.append({
                "provider_specialty_id": ps_id,
                "provider_id": provider_id,
                "specialty_id": specialty_id,
                "certification_date": f"{config.reference_date.year - rng.randint(1, 3)}-01-01",
                "created_at": config.reference_date.isoformat(),
            })
            ps_id += 1

    return pl.DataFrame(rows)
