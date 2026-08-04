"""The master data dataset registry."""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey
from eds.domains.healthcare.domain.patient.schema import PATIENT_DATASETS
from eds.domains.healthcare.domain.provider.schema import PROVIDER_DATASETS
from eds.domains.healthcare.domain.encounter.schema import ENCOUNTER_DATASETS
from eds.domains.healthcare.domain.billing.schema import BILLING_DATASETS

__all__ = [
    "MASTER_DATA_DATASETS",
    "COUNTRIES",
    "STATES",
    "CITIES",
    "DEPARTMENTS",
    "SPECIALTIES",
    "INSURANCE_PLAN_DATASETS",
    "ROOM_TYPE_DATASETS",
    "MEDICATION_DATASETS",
    "DIAGNOSIS_CODE_DATASETS",
    "PROCEDURE_CODE_DATASETS",
    "BILLING_CODE_DATASETS",
    "FACILITY_DATASETS",
    "dataset_by_name",
    "dataset_names",
]

# Country reference table
COUNTRIES = Dataset(
    name="countries",
    columns={
        "country_id": pl.Int64(),
        "country_code": pl.String(),
        "country_name": pl.String(),
    },
    primary_key="country_id",
    unique_columns=("country_code",),
)

# State reference table
STATES = Dataset(
    name="states",
    columns={
        "state_id": pl.Int64(),
        "state_code": pl.String(),
        "state_name": pl.String(),
        "country_id": pl.Int64(),
    },
    primary_key="state_id",
    unique_columns=("state_code",),
    foreign_keys=(ForeignKey("country_id", "countries", "country_id"),),
)

# City reference table
CITIES = Dataset(
    name="cities",
    columns={
        "city_id": pl.Int64(),
        "city_code": pl.String(),
        "city_name": pl.String(),
        "state_id": pl.Int64(),
    },
    primary_key="city_id",
    unique_columns=("city_code",),
    foreign_keys=(ForeignKey("state_id", "states", "state_id"),),
)

# Department reference table
DEPARTMENTS = Dataset(
    name="departments",
    columns={
        "department_id": pl.Int64(),
        "department_code": pl.String(),
        "department_name": pl.String(),
        "description": pl.String(),
    },
    primary_key="department_id",
    unique_columns=("department_code",),
)

DEPARTMENT_DATASETS: tuple[Dataset, ...] = (DEPARTMENTS,)

# Specialty reference table
SPECIALTIES = Dataset(
    name="specialties",
    columns={
        "specialty_id": pl.Int64(),
        "specialty_code": pl.String(),
        "specialty_name": pl.String(),
        "description": pl.String(),
    },
    primary_key="specialty_id",
    unique_columns=("specialty_code",),
)

SPECIALTY_DATASETS: tuple[Dataset, ...] = (SPECIALTIES,)

# Insurance plan reference table
INSURANCE_PLANS = Dataset(
    name="insurance_plans",
    columns={
        "insurance_plan_id": pl.Int64(),
        "plan_name": pl.String(),
        "plan_type": pl.String(),
        "coverage_tier": pl.String(),
        "premium_amount": pl.Float64(),
        "currency_code": pl.String(),
    },
    primary_key="insurance_plan_id",
    unique_columns=("plan_name",),
)

INSURANCE_PLAN_DATASETS: tuple[Dataset, ...] = (INSURANCE_PLANS,)

# Room type reference table
ROOM_TYPES = Dataset(
    name="room_types",
    columns={
        "room_type_id": pl.Int64(),
        "room_type_code": pl.String(),
        "room_type_name": pl.String(),
        "base_rate": pl.Float64(),
        "currency_code": pl.String(),
    },
    primary_key="room_type_id",
    unique_columns=("room_type_code",),
)

ROOM_TYPE_DATASETS: tuple[Dataset, ...] = (ROOM_TYPES,)

# Medication reference table
MEDICATIONS = Dataset(
    name="medications",
    columns={
        "medication_id": pl.Int64(),
        "medication_code": pl.String(),
        "medication_name": pl.String(),
        "form": pl.String(),
        "strength": pl.String(),
        "unit_of_measure": pl.String(),
    },
    primary_key="medication_id",
    unique_columns=("medication_code",),
)

MEDICATION_DATASETS: tuple[Dataset, ...] = (MEDICATIONS,)

# Diagnosis code reference table
DIAGNOSIS_CODES = Dataset(
    name="diagnosis_codes",
    columns={
        "diagnosis_code_id": pl.Int64(),
        "code": pl.String(),
        "description": pl.String(),
        "category": pl.String(),
    },
    primary_key="diagnosis_code_id",
    unique_columns=("code",),
)

DIAGNOSIS_CODE_DATASETS: tuple[Dataset, ...] = (DIAGNOSIS_CODES,)

# Procedure code reference table
PROCEDURE_CODES = Dataset(
    name="procedure_codes",
    columns={
        "procedure_code_id": pl.Int64(),
        "code": pl.String(),
        "description": pl.String(),
        "category": pl.String(),
    },
    primary_key="procedure_code_id",
    unique_columns=("code",),
)

PROCEDURE_CODE_DATASETS: tuple[Dataset, ...] = (PROCEDURE_CODES,)

# Billing code reference table
BILLING_CODES = Dataset(
    name="billing_codes",
    columns={
        "billing_code_id": pl.Int64(),
        "code": pl.String(),
        "description": pl.String(),
        "charge_amount": pl.Float64(),
        "currency_code": pl.String(),
    },
    primary_key="billing_code_id",
    unique_columns=("code",),
)

BILLING_CODE_DATASETS: tuple[Dataset, ...] = (BILLING_CODES,)

# Facility reference table
FACILITIES = Dataset(
    name="facilities",
    columns={
        "facility_id": pl.Int64(),
        "facility_code": pl.String(),
        "facility_name": pl.String(),
        "facility_type": pl.String(),
    },
    primary_key="facility_id",
    unique_columns=("facility_code",),
)

FACILITY_DATASETS: tuple[Dataset, ...] = (FACILITIES,)

MASTER_DATA_DATASETS: tuple[Dataset, ...] = (
    COUNTRIES,
    STATES,
    CITIES,
    *DEPARTMENT_DATASETS,
    *SPECIALTY_DATASETS,
    *INSURANCE_PLAN_DATASETS,
    *ROOM_TYPE_DATASETS,
    *MEDICATION_DATASETS,
    *DIAGNOSIS_CODE_DATASETS,
    *PROCEDURE_CODE_DATASETS,
    *BILLING_CODE_DATASETS,
    *FACILITY_DATASETS,
)

_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in MASTER_DATA_DATASETS}


def dataset_names() -> tuple[str, ...]:
    """Return every master dataset name in dependency order."""
    return tuple(_BY_NAME)


def dataset_by_name(name: str) -> Dataset:
    """Look up a dataset declaration by name."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"Unknown dataset: {name!r}. Known datasets: {dataset_names()}") from None
