"""Generate provider demographic records."""

from __future__ import annotations

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_providers"]


def generate_providers(
    config, master_data: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "providers")
    departments = master_data["departments"]
    specialties = master_data["specialties"]
    department_ids = departments["department_id"].to_list()
    specialty_ids = specialties["specialty_id"].to_list()

    first_names = ["Raj", "Priya", "Aditya", "Kavya", "Aarav", "Ananya", "Diya", "Riya", "Saanvi", "Vihaan"]
    last_names = ["Sharma", "Patel", "Singh", "Kumar", "Gupta", "Verma", "Reddy", "Joshi", "Iyer", "Kapoor"]

    rows = []
    for i in range(1, config.provider_count + 1):
        department_id = rng.choice(department_ids)
        specialty_id = rng.choice(specialty_ids)
        provider_type = ["PHYSICIAN", "NURSE", "SPECIALIST", "TECHNICIAN", "ADMIN"][i % 5]
        first_name = rng.choice(first_names)
        last_name = rng.choice(last_names)
        rows.append({
            "provider_id": i,
            "provider_number": f"PROV-{i:06d}",
            "first_name": first_name,
            "last_name": last_name,
            "full_name": f"{first_name} {last_name}",
            "provider_type": provider_type,
            "specialty_id": specialty_id,
            "department_id": department_id,
            "license_number": f"LIC-{rng.randint(100000, 999999)}",
            "status": "ACTIVE",
            "hire_date": f"{config.reference_date.year - rng.randint(1, 5)}-01-01",
            "termination_date": None,
            "created_at": config.reference_date.isoformat(),
        })

    return pl.DataFrame(rows)
