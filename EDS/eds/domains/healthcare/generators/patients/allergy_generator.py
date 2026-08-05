"""Generate patient allergy records."""

from __future__ import annotations

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
                rows.append({
                    "allergy_id": allergy_id,
                    "patient_id": patient_id,
                    "allergen": rng.choice(allergens),
                    "severity": rng.choice(["MILD", "MODERATE", "SEVERE"]),
                    "reaction": rng.choice(["RASH", "SWELLING", "ANAPHYLAXIS", "NAUSEA", "VOMITING", "DIARRHEA", "HIVES", "ITCHING", "WHEEZING", "COUGH", "FEVER", "HEADACHE", "DIZZINESS", "SHORTNESS_OF_BREATH", "CHEST_PAIN"]),
                    "status": "ACTIVE",
                    "recorded_at": f"{config.reference_date.year - rng.randint(0, 365)}-01-01",
                    "created_at": config.reference_date.isoformat(),
                })
                allergy_id += 1

    return pl.DataFrame(rows)

