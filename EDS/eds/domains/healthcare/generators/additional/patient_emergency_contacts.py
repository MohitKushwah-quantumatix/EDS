"""Generate patient_emergency_contacts dataset."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import make_rng, resolve_seed

__all__ = ["generate_patient_emergency_contacts"]

RELATIONSHIPS = ["SPOUSE", "PARENT", "SIBLING", "FRIEND", "GUARDIAN"]


def generate_patient_emergency_contacts(
    config: SimulationConfig,
    upstream: Mapping[str, pl.DataFrame],
) -> pl.DataFrame:
    seed = resolve_seed(config.platform.seed)
    rng = make_rng(seed, "patient_emergency_contacts")

    patients = upstream.get("patients")
    if patients is None or patients.is_empty():
        return pl.DataFrame(schema={
            "contact_id": pl.Int64(),
            "patient_id": pl.Int64(),
            "contact_name": pl.String(),
            "relationship": pl.String(),
            "phone_number": pl.String(),
            "email": pl.String(),
            "is_primary": pl.Boolean(),
            "created_at": pl.Datetime("us"),
        })

    n = len(patients)
    rows = []
    for i in range(n):
        pat = patients.row(i, named=True)
        rows.append({
            "contact_id": int(i + 1),
            "patient_id": int(pat["patient_id"]),
            "contact_name": str(f"Contact {i + 1}"),
            "relationship": str(rng.choice(RELATIONSHIPS)),
            "phone_number": str(f"+91987654321{i % 10}"),
            "email": str(f"contact{i + 1}@example.com"),
            "is_primary": True,
            "created_at": datetime.strptime(pat["registration_date"].isoformat(), "%Y-%m-%d"),
        })

    return pl.DataFrame(rows)
