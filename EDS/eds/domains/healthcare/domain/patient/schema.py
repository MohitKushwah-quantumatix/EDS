"""Schemas for the patient master datasets.

Patient data references the F001 geography datasets through
``city_id``, ``state_id``, and ``country_id``. Those foreign keys are declared
here in the same way F001 declares its own, so the shared referential
validator resolves them without any patient-specific code.
"""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = [
    "PATIENTS",
    "PATIENT_ADDRESSES",
    "PATIENT_INSURANCE",
    "PATIENT_ALLERGIES",
    "PATIENT_DATASETS",
    "patient_dataset_by_name",
    "patient_dataset_names",
]

PATIENTS = Dataset(
    name="patients",
    columns={
        "patient_id": pl.Int64(),
        "patient_number": pl.String(),
        "first_name": pl.String(),
        "last_name": pl.String(),
        "full_name": pl.String(),
        "gender": pl.String(),
        "date_of_birth": pl.Date(),
        "email": pl.String(),
        "phone": pl.String(),
        "registration_date": pl.Date(),
        "status": pl.String(),
        "insurance_type": pl.String(),
        "primary_facility_id": pl.Int64(),
        "created_at": pl.Datetime("us"),
        "updated_at": pl.Datetime("us"),
    },
    primary_key="patient_id",
    unique_columns=("patient_number", "email", "phone"),
)

PATIENT_ADDRESSES = Dataset(
    name="patient_addresses",
    columns={
        "address_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "address_type": pl.String(),
        "line1": pl.String(),
        "line2": pl.String(),
        "city_id": pl.Int64(),
        "state_id": pl.Int64(),
        "country_id": pl.Int64(),
        "postal_code": pl.String(),
        "is_primary": pl.Boolean(),
        "latitude": pl.Float64(),
        "longitude": pl.Float64(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="address_id",
    foreign_keys=(
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("city_id", "cities", "city_id"),
        ForeignKey("state_id", "states", "state_id"),
        ForeignKey("country_id", "countries", "country_id"),
    ),
)

PATIENT_INSURANCE = Dataset(
    name="patient_insurance",
    columns={
        "insurance_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "insurance_plan_id": pl.Int64(),
        "policy_number": pl.String(),
        "group_number": pl.String(),
        "effective_date": pl.Date(),
        "expiration_date": pl.Date(),
        "is_primary": pl.Boolean(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="insurance_id",
    foreign_keys=(
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("insurance_plan_id", "insurance_plans", "insurance_plan_id"),
    ),
    unique_columns=("patient_id",),
)

PATIENT_ALLERGIES = Dataset(
    name="patient_allergies",
    columns={
        "allergy_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "allergen": pl.String(),
        "severity": pl.String(),
        "reaction": pl.String(),
        "status": pl.String(),
        "recorded_at": pl.Date(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="allergy_id",
    foreign_keys=(ForeignKey("patient_id", "patients", "patient_id"),),
)

PATIENT_DATASETS: tuple[Dataset, ...] = (
    PATIENTS,
    PATIENT_ADDRESSES,
    PATIENT_INSURANCE,
    PATIENT_ALLERGIES,
)

_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in PATIENT_DATASETS}


def patient_dataset_names() -> tuple[str, ...]:
    """Return every patient dataset name in dependency order."""
    return tuple(_BY_NAME)


def patient_dataset_by_name(name: str) -> Dataset:
    """Look up a patient dataset declaration by name."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown patient dataset: {name!r}. Known datasets: {patient_dataset_names()}"
        ) from None
