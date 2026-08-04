"""Schemas for the encounter datasets.

Encounter data references the patient and provider datasets through
foreign keys, and references master data datasets through
``department_id``, ``specialty_id``, etc.
"""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = [
    "ENCOUNTERS",
    "APPOINTMENTS",
    "VITALS",
    "MEDICATIONS_PRESCRIBED",
    "DIAGNOSES",
    "PROCEDURES",
    "ENCOUNTER_DATASETS",
    "encounter_dataset_by_name",
    "encounter_dataset_names",
]

ENCOUNTERS = Dataset(
    name="encounters",
    columns={
        "encounter_id": pl.Int64(),
        "encounter_number": pl.String(),
        "patient_id": pl.Int64(),
        "provider_id": pl.Int64(),
        "department_id": pl.Int64(),
        "encounter_type": pl.String(),
        "admit_source": pl.String(),
        "status": pl.String(),
        "admission_date": pl.Date(),
        "discharge_date": pl.Date(),
        "discharge_disposition": pl.String(),
        "facility_id": pl.Int64(),
        "room_number": pl.String(),
        "bed_number": pl.String(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="encounter_id",
    foreign_keys=(
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("provider_id", "providers", "provider_id"),
        ForeignKey("department_id", "departments", "department_id"),
        ForeignKey("facility_id", "facilities", "facility_id"),
    ),
    unique_columns=("encounter_number",),
)

APPOINTMENTS = Dataset(
    name="appointments",
    columns={
        "appointment_id": pl.Int64(),
        "encounter_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "provider_id": pl.Int64(),
        "department_id": pl.Int64(),
        "appointment_type": pl.String(),
        "scheduled_date": pl.Date(),
        "start_time": pl.Datetime("us"),
        "end_time": pl.Datetime("us"),
        "status": pl.String(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="appointment_id",
    foreign_keys=(
        ForeignKey("encounter_id", "encounters", "encounter_id"),
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("provider_id", "providers", "provider_id"),
        ForeignKey("department_id", "departments", "department_id"),
    ),
)

VITALS = Dataset(
    name="vitals",
    columns={
        "vital_id": pl.Int64(),
        "encounter_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "temperature": pl.Float64(),
        "heart_rate": pl.Int64(),
        "blood_pressure_systolic": pl.Int64(),
        "blood_pressure_diastolic": pl.Int64(),
        "respiratory_rate": pl.Int64(),
        "oxygen_saturation": pl.Float64(),
        "height_cm": pl.Float64(),
        "weight_kg": pl.Float64(),
        "bmi": pl.Float64(),
        "recorded_at": pl.Datetime("us"),
        "created_at": pl.Datetime("us"),
    },
    primary_key="vital_id",
    foreign_keys=(
        ForeignKey("encounter_id", "encounters", "encounter_id"),
        ForeignKey("patient_id", "patients", "patient_id"),
    ),
)

MEDICATIONS_PRESCRIBED = Dataset(
    name="medications_prescribed",
    columns={
        "prescription_id": pl.Int64(),
        "encounter_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "provider_id": pl.Int64(),
        "medication_id": pl.Int64(),
        "dosage": pl.String(),
        "frequency": pl.String(),
        "route": pl.String(),
        "duration_days": pl.Int64(),
        "status": pl.String(),
        "prescribed_at": pl.Datetime("us"),
        "created_at": pl.Datetime("us"),
    },
    primary_key="prescription_id",
    foreign_keys=(
        ForeignKey("encounter_id", "encounters", "encounter_id"),
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("provider_id", "providers", "provider_id"),
        ForeignKey("medication_id", "medications", "medication_id"),
    ),
)

DIAGNOSES = Dataset(
    name="diagnoses",
    columns={
        "diagnosis_id": pl.Int64(),
        "encounter_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "provider_id": pl.Int64(),
        "diagnosis_code_id": pl.Int64(),
        "diagnosis_type": pl.String(),
        "onset_date": pl.Date(),
        "status": pl.String(),
        "recorded_at": pl.Datetime("us"),
        "created_at": pl.Datetime("us"),
    },
    primary_key="diagnosis_id",
    foreign_keys=(
        ForeignKey("encounter_id", "encounters", "encounter_id"),
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("provider_id", "providers", "provider_id"),
        ForeignKey("diagnosis_code_id", "diagnosis_codes", "diagnosis_code_id"),
    ),
)

PROCEDURES = Dataset(
    name="procedures",
    columns={
        "procedure_id": pl.Int64(),
        "encounter_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "provider_id": pl.Int64(),
        "procedure_code_id": pl.Int64(),
        "procedure_description": pl.String(),
        "performed_at": pl.Datetime("us"),
        "created_at": pl.Datetime("us"),
    },
    primary_key="procedure_id",
    foreign_keys=(
        ForeignKey("encounter_id", "encounters", "encounter_id"),
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("provider_id", "providers", "provider_id"),
        ForeignKey("procedure_code_id", "procedure_codes", "procedure_code_id"),
    ),
)

ENCOUNTER_DATASETS: tuple[Dataset, ...] = (
    ENCOUNTERS,
    APPOINTMENTS,
    VITALS,
    MEDICATIONS_PRESCRIBED,
    DIAGNOSES,
    PROCEDURES,
)

_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in ENCOUNTER_DATASETS}


def encounter_dataset_names() -> tuple[str, ...]:
    """Return every encounter dataset name in dependency order."""
    return tuple(_BY_NAME)


def encounter_dataset_by_name(name: str) -> Dataset:
    """Look up an encounter dataset declaration by name."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown encounter dataset: {name!r}. Known datasets: {encounter_dataset_names()}"
        ) from None
