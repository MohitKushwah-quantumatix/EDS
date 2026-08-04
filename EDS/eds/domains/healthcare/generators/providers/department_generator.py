"""Generate provider-department mapping records."""

from __future__ import annotations

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_provider_departments"]


def generate_provider_departments(
    config, providers: pl.DataFrame, master_data: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "provider_departments")
    department_ids = master_data["departments"]["department_id"].to_list()

    rows = []
    pd_id = 1
    for provider_row in providers.iter_rows():
        provider_id = provider_row[0]
        num_depts = rng.randint(1, min(3, len(department_ids)))
        chosen = [department_ids[rng.randint(0, len(department_ids) - 1)] for _ in range(num_depts)]
        for idx, dept_id in enumerate(chosen):
            rows.append({
                "provider_department_id": pd_id,
                "provider_id": provider_id,
                "department_id": dept_id,
                "role": ["HEAD", "SENIOR", "JUNIOR"][idx % 3],
                "is_primary": idx == 0,
                "start_date": provider_row[10],
                "end_date": None,
                "created_at": config.reference_date.isoformat(),
            })
            pd_id += 1

    return pl.DataFrame(rows)
