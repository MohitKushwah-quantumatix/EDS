"""Tests for the additional Healthcare datasets."""

from __future__ import annotations

import polars as pl
import pytest

from eds.domains.healthcare.config import SimulationConfig
from eds.domains.healthcare.generators.additional.lab_results import generate_lab_results
from eds.domains.healthcare.generators.additional.radiology_reports import generate_radiology_reports
from eds.domains.healthcare.generators.additional.medication_administration import generate_medication_administration
from eds.domains.healthcare.generators.additional.admissions import generate_admissions
from eds.domains.healthcare.generators.additional.discharge_summaries import generate_discharge_summaries
from eds.domains.healthcare.generators.additional.immunizations import generate_immunizations
from eds.domains.healthcare.generators.additional.referrals import generate_referrals
from eds.domains.healthcare.generators.additional.patient_emergency_contacts import generate_patient_emergency_contacts
from eds.domains.healthcare.temporal.datasets import HEALTHCARE_DATASETS
from eds.domains.healthcare.temporal.temporality import DATASET_TEMPORALITY

ADDITIONAL_DATASET_NAMES = (
    "lab_results",
    "radiology_reports",
    "medication_administration",
    "admissions",
    "discharge_summaries",
    "immunizations",
    "referrals",
    "patient_emergency_contacts",
)


def test_additional_datasets_are_registered():
    registered = {ds.name for ds in HEALTHCARE_DATASETS}
    for name in ADDITIONAL_DATASET_NAMES:
        assert name in registered, f"{name} is not registered in HEALTHCARE_DATASETS"


def test_additional_datasets_have_temporality():
    for name in ADDITIONAL_DATASET_NAMES:
        assert name in DATASET_TEMPORALITY, f"{name} has no temporality declaration"


def test_lab_results_generator():
    config = SimulationConfig()
    upstream = {
        "encounters": pl.DataFrame({
            "encounter_id": [1, 2],
            "patient_id": [1, 2],
            "admission_date": ["2025-01-15", "2025-01-16"],
        }),
    }
    df = generate_lab_results(config, upstream)
    assert "lab_result_id" in df.columns
    assert "test_name" in df.columns
    assert "reported_at" in df.columns


def test_radiology_reports_generator():
    config = SimulationConfig()
    upstream = {
        "encounters": pl.DataFrame({
            "encounter_id": [1, 2],
            "patient_id": [1, 2],
            "admission_date": ["2025-01-15", "2025-01-16"],
            "provider_id": [1, 2],
        }),
        "providers": pl.DataFrame({
            "provider_id": [1, 2],
        }),
    }
    df = generate_radiology_reports(config, upstream)
    assert "radiology_id" in df.columns
    assert "modality" in df.columns
    assert "performed_at" in df.columns


def test_medication_administration_generator():
    config = SimulationConfig()
    upstream = {
        "encounters": pl.DataFrame({
            "encounter_id": [1, 2],
            "patient_id": [1, 2],
            "admission_date": ["2025-01-15", "2025-01-16"],
        }),
        "medications": pl.DataFrame({
            "medication_id": [1, 2],
        }),
        "providers": pl.DataFrame({
            "provider_id": [1, 2],
        }),
    }
    df = generate_medication_administration(config, upstream)
    assert "administration_id" in df.columns
    assert "dose" in df.columns
    assert "route" in df.columns


def test_admissions_generator():
    config = SimulationConfig()
    upstream = {
        "encounters": pl.DataFrame({
            "encounter_id": [1, 2],
            "patient_id": [1, 2],
            "admission_date": ["2025-01-15", "2025-01-16"],
            "discharge_date": ["2025-01-20", "2025-01-25"],
        }),
        "providers": pl.DataFrame({
            "provider_id": [1, 2],
        }),
    }
    df = generate_admissions(config, upstream)
    assert "admission_id" in df.columns
    assert "ward" in df.columns
    assert "bed_number" in df.columns


def test_discharge_summaries_generator():
    config = SimulationConfig()
    upstream = {
        "encounters": pl.DataFrame({
            "encounter_id": [1, 2],
            "patient_id": [1, 2],
            "admission_date": ["2025-01-15", "2025-01-16"],
            "discharge_date": ["2025-01-20", "2025-01-25"],
        }),
        "providers": pl.DataFrame({
            "provider_id": [1, 2],
        }),
    }
    df = generate_discharge_summaries(config, upstream)
    assert "discharge_id" in df.columns
    assert "discharge_diagnosis" in df.columns
    assert "follow_up_date" in df.columns


def test_immunizations_generator():
    config = SimulationConfig()
    upstream = {
        "patients": pl.DataFrame({
            "patient_id": [1, 2],
            "registration_date": ["2025-01-15", "2025-01-16"],
        }),
        "providers": pl.DataFrame({
            "provider_id": [1, 2],
        }),
    }
    df = generate_immunizations(config, upstream)
    assert "immunization_id" in df.columns
    assert "vaccine_name" in df.columns
    assert "site" in df.columns


def test_referrals_generator():
    config = SimulationConfig()
    upstream = {
        "encounters": pl.DataFrame({
            "encounter_id": [1, 2],
            "patient_id": [1, 2],
            "admission_date": ["2025-01-15", "2025-01-16"],
            "provider_id": [1, 2],
        }),
        "providers": pl.DataFrame({
            "provider_id": [1, 2],
        }),
    }
    df = generate_referrals(config, upstream)
    assert "referral_id" in df.columns
    assert "referral_reason" in df.columns
    assert "status" in df.columns


def test_patient_emergency_contacts_generator():
    config = SimulationConfig()
    upstream = {
        "patients": pl.DataFrame({
            "patient_id": [1, 2],
        }),
    }
    df = generate_patient_emergency_contacts(config, upstream)
    assert "contact_id" in df.columns
    assert "relationship" in df.columns
    assert "is_primary" in df.columns


def test_additional_datasets_produce_valid_schemas():
    config = SimulationConfig()
    upstream = {
        "encounters": pl.DataFrame({
            "encounter_id": [1, 2],
            "patient_id": [1, 2],
            "admission_date": ["2025-01-15", "2025-01-16"],
            "discharge_date": ["2025-01-20", "2025-01-25"],
            "provider_id": [1, 2],
        }),
        "patients": pl.DataFrame({
            "patient_id": [1, 2],
            "registration_date": ["2025-01-15", "2025-01-16"],
        }),
        "providers": pl.DataFrame({
            "provider_id": [1, 2],
        }),
        "medications": pl.DataFrame({
            "medication_id": [1, 2],
        }),
    }

    generators = {
        "lab_results": generate_lab_results,
        "radiology_reports": generate_radiology_reports,
        "medication_administration": generate_medication_administration,
        "admissions": generate_admissions,
        "discharge_summaries": generate_discharge_summaries,
        "immunizations": generate_immunizations,
        "referrals": generate_referrals,
        "patient_emergency_contacts": generate_patient_emergency_contacts,
    }

    expected_schemas = {ds.name: set(ds.columns.keys()) for ds in HEALTHCARE_DATASETS}

    for name, generator in generators.items():
        df = generator(config, upstream)
        assert not df.is_empty(), f"{name} produced empty DataFrame"
        expected_cols = expected_schemas.get(name, set())
        assert set(df.columns) == expected_cols, f"{name} columns mismatch: {set(df.columns)} != {expected_cols}"
