"""Generate patient demographic records."""

from __future__ import annotations

from datetime import date
import random

import polars as pl

from eds.core.random_streams import make_rng

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
        reg_year = config.reference_date.year - rng.randint(0, config.registration_years)
        reg_month = rng.randint(1, 12)
        reg_day = rng.randint(1, 28)
        registration_date = date(reg_year, reg_month, reg_day)
        dob_year = reg_year - rng.randint(18, 80)
        dob_month = rng.randint(1, 12)
        dob_day = rng.randint(1, 28)
        date_of_birth = date(dob_year, dob_month, dob_day)

        rows.append({
            "patient_id": i,
            "patient_number": f"PAT-{i:06d}",
            "first_name": first_name,
            "last_name": last_name,
            "full_name": f"{first_name} {last_name}",
            "gender": gender,
            "date_of_birth": date_of_birth,
            "email": f"patient{i}@example.com",
            "phone": f"+91{rng.randint(7000000000, 9999999999)}",
            "registration_date": registration_date,
            "status": status,
            "insurance_type": insurance_type,
            "primary_facility_id": facility_id,
            "created_at": config.reference_date,
            "updated_at": config.reference_date,
        })

    df = pl.DataFrame(rows)
    # Ensure date types match schema
    df = df.with_columns([
        pl.col("date_of_birth").cast(pl.Date()),
        pl.col("registration_date").cast(pl.Date()),
        pl.col("created_at").cast(pl.Datetime("us")),
        pl.col("updated_at").cast(pl.Datetime("us")),
    ])
    return df
