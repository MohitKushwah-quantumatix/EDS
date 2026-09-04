"""Generate patient demographic records."""

from __future__ import annotations

from datetime import date, timedelta
import random

import polars as pl

from eds.core.random_streams import make_rng
from eds.core.encoding import encode_hash

__all__ = ["generate_patients"]


def generate_patients(
    config, master_data: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    """Generate patient demographic records."""
    rng = make_rng(seed, "patients")
    facilities = master_data["facilities"]
    facility_ids = facilities["facility_id"].to_list()

    rows = []
    for i in range(1, config.patient_count + 1):
        facility_id = rng.choice(facility_ids)
        first_name = rng.choice(["Aarav", "Aditya", "Aryan", "Ishaan", "Kavya", "Priya", "Ananya", "Diya", "Riya", "Saanvi"])
        last_name = rng.choice(["Sharma", "Patel", "Singh", "Kumar", "Gupta", "Verma", "Reddy", "Joshi", "Iyer", "Kapoor"])
        gender = rng.choices(["MALE", "FEMALE", "NON_BINARY", "UNDISCLOSED"], weights=[48, 48, 2, 2], k=1)[0]
        status = rng.choice(["ACTIVE", "ACTIVE", "ACTIVE", "INACTIVE", "TRANSFERRED"])
        insurance_type = rng.choice(["PRIVATE", "PRIVATE", "MEDICARE", "MEDICAID", "SELF_PAY"])
        max_lookback = min((config.reference_date - date(2026, 1, 1)).days, 150)
        days_back = rng.randint(0, max_lookback)
        registration_date = config.reference_date - timedelta(days=days_back)
        age_years = rng.randint(18, 80)
        date_of_birth = registration_date - timedelta(days=age_years * 365)

        rows.append({
            "patient_id": i,
            "patient_number": f"PAT-{i:06d}",
            "first_name": first_name,
            "last_name": last_name,
            "full_name": f"{first_name} {last_name}",
            "gender": gender,
            "date_of_birth": date_of_birth,
            "email": encode_hash(f"patient{i}@example.com"),
            "phone": encode_hash(f"+91{rng.randint(7000000000, 9999999999)}"),
            "registration_date": registration_date,
            "status": status,
            "insurance_type": insurance_type,
            "primary_facility_id": facility_id,
            "effective_date": config.reference_date,
            "end_date": None,
            "created_at": config.reference_date,
            "updated_at": config.reference_date,
        })

    df = pl.DataFrame(rows)
    if df.height > 0:
        df = df.with_columns([
            pl.col("date_of_birth").cast(pl.Date()),
            pl.col("registration_date").cast(pl.Date()),
            pl.col("effective_date").cast(pl.Date()),
            pl.col("end_date").cast(pl.Date()),
            pl.col("created_at").cast(pl.Datetime("us")),
            pl.col("updated_at").cast(pl.Datetime("us")),
        ])
    return df
