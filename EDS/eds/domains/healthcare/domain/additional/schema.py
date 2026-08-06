"""Schemas for additional healthcare datasets."""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = [
    "LAB_RESULTS",
    "RADIOLOGY_REPORTS",
    "MEDICATION_ADMINISTRATION",
    "ADMISSIONS",
    "DISCHARGE_SUMMARIES",
    "IMMUNIZATIONS",
    "REFERRALS",
    "PATIENT_EMERGENCY_CONTACTS",
    "ADDITIONAL_DATASETS",
]

LAB_RESULTS = Dataset(
    name="lab_results",
    columns={
        "lab_result_id": pl.Int64(),
        "encounter_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "test_name": pl.String(),
        "result_value": pl.String(),
        "unit": pl.String(),
        "normal_range": pl.String(),
        "result_status": pl.String(),
        "reported_at": pl.Date(),
    },
    primary_key="lab_result_id",
    foreign_keys=(
        ForeignKey("encounter_id", "encounters", "encounter_id"),
        ForeignKey("patient_id", "patients", "patient_id"),
    ),
)

RADIOLOGY_REPORTS = Dataset(
    name="radiology_reports",
    columns={
        "radiology_id": pl.Int64(),
        "encounter_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "modality": pl.String(),
        "body_part": pl.String(),
        "findings": pl.String(),
        "impression": pl.String(),
        "performed_at": pl.Date(),
        "radiologist_id": pl.Int64(),
    },
    primary_key="radiology_id",
    foreign_keys=(
        ForeignKey("encounter_id", "encounters", "encounter_id"),
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("radiologist_id", "providers", "provider_id"),
    ),
)

MEDICATION_ADMINISTRATION = Dataset(
    name="medication_administration",
    columns={
        "administration_id": pl.Int64(),
        "encounter_id": pl.Int64(),
        "medication_id": pl.Int64(),
        "dose": pl.String(),
        "route": pl.String(),
        "administered_at": pl.Date(),
        "administered_by": pl.Int64(),
    },
    primary_key="administration_id",
    foreign_keys=(
        ForeignKey("encounter_id", "encounters", "encounter_id"),
        ForeignKey("medication_id", "medications", "medication_id"),
        ForeignKey("administered_by", "providers", "provider_id"),
    ),
)

ADMISSIONS = Dataset(
    name="admissions",
    columns={
        "admission_id": pl.Int64(),
        "encounter_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "admission_type": pl.String(),
        "admission_source": pl.String(),
        "admitted_at": pl.Date(),
        "discharged_at": pl.Date(),
        "ward": pl.String(),
        "bed_number": pl.String(),
        "attending_physician": pl.Int64(),
    },
    primary_key="admission_id",
    foreign_keys=(
        ForeignKey("encounter_id", "encounters", "encounter_id"),
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("attending_physician", "providers", "provider_id"),
    ),
)

DISCHARGE_SUMMARIES = Dataset(
    name="discharge_summaries",
    columns={
        "discharge_id": pl.Int64(),
        "encounter_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "discharge_diagnosis": pl.String(),
        "discharge_instructions": pl.String(),
        "follow_up_date": pl.Date(),
        "follow_up_physician": pl.Int64(),
        "discharge_disposition": pl.String(),
    },
    primary_key="discharge_id",
    foreign_keys=(
        ForeignKey("encounter_id", "encounters", "encounter_id"),
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("follow_up_physician", "providers", "provider_id"),
    ),
)

IMMUNIZATIONS = Dataset(
    name="immunizations",
    columns={
        "immunization_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "vaccine_name": pl.String(),
        "dose_number": pl.Int64(),
        "administered_at": pl.Date(),
        "administered_by": pl.Int64(),
        "site": pl.String(),
        "lot_number": pl.String(),
    },
    primary_key="immunization_id",
    foreign_keys=(
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("administered_by", "providers", "provider_id"),
    ),
)

REFERRALS = Dataset(
    name="referrals",
    columns={
        "referral_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "encounter_id": pl.Int64(),
        "referring_provider": pl.Int64(),
        "referred_to_provider": pl.Int64(),
        "referral_reason": pl.String(),
        "referral_date": pl.Date(),
        "status": pl.String(),
    },
    primary_key="referral_id",
    foreign_keys=(
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("encounter_id", "encounters", "encounter_id"),
        ForeignKey("referring_provider", "providers", "provider_id"),
        ForeignKey("referred_to_provider", "providers", "provider_id"),
    ),
)

PATIENT_EMERGENCY_CONTACTS = Dataset(
    name="patient_emergency_contacts",
    columns={
        "contact_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "contact_name": pl.String(),
        "relationship": pl.String(),
        "phone_number": pl.String(),
        "email": pl.String(),
        "is_primary": pl.Boolean(),
    },
    primary_key="contact_id",
    foreign_keys=(
        ForeignKey("patient_id", "patients", "patient_id"),
    ),
)

ADDITIONAL_DATASETS: tuple[Dataset, ...] = (
    LAB_RESULTS,
    RADIOLOGY_REPORTS,
    MEDICATION_ADMINISTRATION,
    ADMISSIONS,
    DISCHARGE_SUMMARIES,
    IMMUNIZATIONS,
    REFERRALS,
    PATIENT_EMERGENCY_CONTACTS,
)
