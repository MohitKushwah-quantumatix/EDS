"""Generate procedure records."""

from __future__ import annotations

from datetime import datetime

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_procedures"]


def generate_procedures(
    config, encounters: pl.DataFrame, upstream: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "procedures")
    procedure_code_ids = upstream["procedure_codes"]["procedure_code_id"].to_list()

    rows = []
    procedure_id = 1
    for encounter_row in encounters.iter_rows():
        if rng.random() < 0.5:
            num_procedures = rng.randint(1, 2)
            for _ in range(num_procedures):
                rows.append({
                    "procedure_id": procedure_id,
                    "encounter_id": encounter_row[0],
                    "patient_id": encounter_row[2],
                    "provider_id": encounter_row[3],
                    "procedure_code_id": rng.choice(procedure_code_ids),
                    "procedure_description": f"Procedure {procedure_id}",
                    "performed_at": f"{encounter_row[8]} 10:00:00",
                    "created_at": f"{encounter_row[8]} 10:00:00",
                })
                procedure_id += 1

    df = pl.DataFrame(rows)
    if df.height > 0:
        df = df.with_columns([
            pl.col("performed_at").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S"),
            pl.col("created_at").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S"),
        ])
    return df
