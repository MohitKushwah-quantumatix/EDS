"""Generate lab_results dataset."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import make_rng, resolve_seed

__all__ = ["generate_lab_results"]

TEST_NAMES = [
    "Complete Blood Count",
    "Blood Glucose",
    "HbA1c",
    "Lipid Profile",
    "Liver Function Test",
    "Kidney Function Test",
    "Thyroid Profile",
    "Urine Routine",
    "Electrolytes",
    "Coagulation Profile",
]

UNITS = ["g/dL", "mg/dL", "%", "mmol/L", "U/L", "mg/L", "IU/L", "mEq/L"]
NORMAL_RANGES = ["12-16", "70-110", "4-5.6", "100-200", "7-56", "0.6-1.2", "0.3-4.2", "950-1300"]
RESULT_STATUSES = ["NORMAL", "HIGH", "LOW", "BORDERLINE"]


def generate_lab_results(
    config: SimulationConfig,
    upstream: Mapping[str, pl.DataFrame],
) -> pl.DataFrame:
    seed = resolve_seed(config.platform.seed)
    rng = make_rng(seed, "lab_results")

    encounters = upstream.get("encounters")
    if encounters is None or encounters.is_empty():
        return pl.DataFrame(schema={
            "lab_result_id": pl.Int64(),
            "encounter_id": pl.Int64(),
            "patient_id": pl.Int64(),
            "test_name": pl.String(),
            "result_value": pl.String(),
            "unit": pl.String(),
            "normal_range": pl.String(),
            "result_status": pl.String(),
            "reported_at": pl.Date(),
        })

    n = len(encounters)
    rows = []
    for i in range(n):
        enc = encounters.row(i, named=True)
        reported_at = enc["admission_date"]
        rows.append({
            "lab_result_id": int(i + 1),
            "encounter_id": int(enc["encounter_id"]),
            "patient_id": int(enc["patient_id"]),
            "test_name": str(rng.choice(TEST_NAMES)),
            "result_value": str(round(float(rng.uniform(10.0, 500.0)), 1)),
            "unit": str(rng.choice(UNITS)),
            "normal_range": str(rng.choice(NORMAL_RANGES)),
            "result_status": str(rng.choice(RESULT_STATUSES)),
            "reported_at": reported_at,
        })

    df = pl.DataFrame(rows)
    if not df.is_empty():
        df = df.with_columns(pl.col("reported_at").cast(pl.Date()))
    return df
