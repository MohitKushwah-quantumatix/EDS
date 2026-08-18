"""Generate patient allergy records."""

from __future__ import annotations

from datetime import datetime

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_allergies"]


def generate_allergies(
    config, patients: pl.DataFrame, seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "patient_allergies")
    allergens = ["Penicillin", "Sulfa", "Aspirin", "Ibuprofen", "Codeine", "Morphine", "Latex", "Peanuts", "Shellfish", "Dust Mites", "Pollen", "Dust", "Mold", "Eggs", "Milk", "Soy", "Wheat", "Tree Nuts", "Fish", "Sesame", "Bee Sting", "Cotton", "Nickel", "Latex Gloves", "Contrast Dye"]

    rows = []
    allergy_id = 1
    for patient_row in patients.iter_rows():
        patient_id = patient_row[0]
        if rng.random() < 0.3:
            num_allergies = rng.randint(1, 3)
            for _ in range(num_allergies):
                _reg_date = patient_row[9]
                _rec_year = _reg_date.year - rng.randint(0, 3) if _reg_date else config.reference_date.year
                recorded_at = f"{_rec_year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
                rows.append({
                    "allergy_id": allergy_id,
                    "patient_id": patient_id,
                    "allergen": rng.choice(allergens),
                    "severity": rng.choice(["MILD", "MODERATE", "SEVERE"]),
                    "reaction": rng.choice(["RASH", "SWELLING", "ANAPHYLAXIS", "NAUSEA", "VOMITING", "DIARRHEA", "HIVES", "ITCHING", "WHEEZING", "COUGH", "FEVER", "HEADACHE", "DIZZINESS", "SHORTNESS_OF_BREATH", "CHEST_PAIN"]),
                    "status": "ACTIVE",
                    "recorded_at": recorded_at,
                    "created_at": datetime.strptime(recorded_at, "%Y-%m-%d"),
                })
                allergy_id += 1

    df = pl.DataFrame(rows)
    if df.height > 0:
        df = df.with_columns([
            pl.col("recorded_at").str.strptime(pl.Date(), "%Y-%m-%d"),
            pl.col("created_at").cast(pl.Datetime("us")),
        ])
    return df

