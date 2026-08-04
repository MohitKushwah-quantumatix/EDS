"""Generate patient address records."""

from __future__ import annotations

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_addresses"]


def generate_addresses(
    config, patients: pl.DataFrame, master_data: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "patient_addresses")
    cities = master_data["cities"]["city_id"].to_list()
    states = master_data["states"]["state_id"].to_list()
    countries = master_data["countries"]["country_id"].to_list()

    rows = []
    address_id = 1
    for patient_row in patients.iter_rows():
        patient_id = patient_row[0]
        num_addresses = rng.randint(config.min_addresses, config.max_addresses)
        for addr_idx in range(num_addresses):
            rows.append({
                "address_id": address_id,
                "patient_id": patient_id,
                "address_type": ["HOME", "WORK", "BILLING"][addr_idx % 3],
                "line1": f"{rng.randint(1, 9999)} Main St",
                "line2": "",
                "city_id": rng.choice(cities),
                "state_id": rng.choice(states),
                "country_id": rng.choice(countries),
                "postal_code": f"{rng.randint(100000, 999999)}",
                "is_primary": addr_idx == 0,
                "latitude": rng.uniform(-90.0, 90.0),
                "longitude": rng.uniform(-180.0, 180.0),
                "created_at": config.reference_date.isoformat(),
            })
            address_id += 1

    return pl.DataFrame(rows)
