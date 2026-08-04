"""Tests for Healthcare patient generation."""

from __future__ import annotations

import polars as pl
import pytest

from eds.domains.healthcare.config import SimulationConfig, load_config
from eds.domains.healthcare.domain.patient.schema import PATIENT_DATASETS, patient_dataset_names
from eds.domains.healthcare.generators.patient_data import PatientData, generate_patient_data

TEST_SEED = 20260728


@pytest.fixture(scope="session")
def master_data():
    config = load_config()
    md_config = config.master_data.model_copy(
        update={
            "department_count": 3,
            "specialty_count": 3,
            "insurance_plan_count": 3,
            "room_type_count": 3,
            "medication_count": 10,
            "diagnosis_code_count": 5,
            "procedure_code_count": 5,
            "billing_code_count": 5,
            "facility_count": 2,
        }
    )
    from eds.domains.healthcare.generators.master_data import generate_master_data
    return generate_master_data(SimulationConfig(platform=config.platform, master_data=md_config))


@pytest.fixture(scope="session")
def patient_data(master_data):
    config = load_config()
    pt_config = config.patients.model_copy(update={"patient_count": 40})
    sim_config = SimulationConfig(
        platform=config.platform,
        master_data=config.master_data,
        patients=pt_config,
    )
    return generate_patient_data(sim_config, master_data.datasets)


def test_patient_data_produces_all_datasets(patient_data: PatientData) -> None:
    assert set(patient_data.datasets) == set(patient_dataset_names())


def test_patients_have_required_columns(patient_data: PatientData) -> None:
    patients = patient_data.datasets["patients"]
    assert "patient_id" in patients.columns
    assert "patient_number" in patients.columns
    assert "full_name" in patients.columns


def test_patient_addresses_reference_patients(patient_data: PatientData) -> None:
    addresses = patient_data.datasets["patient_addresses"]
    patient_ids = set(patient_data.datasets["patients"]["patient_id"].to_list())
    assert set(addresses["patient_id"].to_list()).issubset(patient_ids)
