"""Tests for Healthcare encounter generation."""

from __future__ import annotations

import polars as pl
import pytest

from eds.domains.healthcare.config import SimulationConfig, load_config
from eds.domains.healthcare.domain.encounter.schema import ENCOUNTER_DATASETS
from eds.domains.healthcare.domain.billing.schema import BILLING_DATASETS
from eds.domains.healthcare.generators.encounter_data import EncounterData, generate_encounter_data

TEST_SEED = 20260728


@pytest.fixture(scope="session")
def upstream():
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
    pt_config = config.patients.model_copy(update={"patient_count": 40})
    prov_config = config.providers.model_copy(update={"provider_count": 10})
    sim_config = SimulationConfig(
        platform=config.platform,
        master_data=md_config,
        patients=pt_config,
        providers=prov_config,
    )
    from eds.domains.healthcare.generators.master_data import generate_master_data
    from eds.domains.healthcare.generators.patient_data import generate_patient_data
    from eds.domains.healthcare.generators.provider_data import generate_provider_data
    master_data = generate_master_data(sim_config)
    patient_data = generate_patient_data(sim_config, master_data.datasets)
    provider_data = generate_provider_data(sim_config, master_data.datasets)
    return {**master_data.datasets, **patient_data.datasets, **provider_data.datasets}


@pytest.fixture(scope="session")
def encounter_data(upstream):
    config = load_config()
    enc_config = config.encounters.model_copy(update={"daily_encounter_rate": 0.5})
    sim_config = SimulationConfig(
        platform=config.platform,
        master_data=config.master_data,
        patients=config.patients,
        providers=config.providers,
        encounters=enc_config,
        billing=config.billing,
    )
    return generate_encounter_data(sim_config, upstream)


def test_encounter_data_produces_all_datasets(encounter_data: EncounterData) -> None:
    expected = {d.name for d in (*ENCOUNTER_DATASETS, *BILLING_DATASETS)}
    assert set(encounter_data.datasets) == expected


def test_encounters_have_required_columns(encounter_data: EncounterData) -> None:
    encounters = encounter_data.datasets["encounters"]
    assert "encounter_id" in encounters.columns
    assert "patient_id" in encounters.columns
    assert "provider_id" in encounters.columns
