"""Tests for Healthcare billing generation."""

from __future__ import annotations

import polars as pl
import pytest

from eds.domains.healthcare.config import SimulationConfig, load_config
from eds.domains.healthcare.domain.billing.schema import BILLING_DATASETS, billing_dataset_names
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
    bill_config = config.billing.model_copy(update={"billing_rate": 0.7, "claim_rate": 0.8})
    sim_config = SimulationConfig(
        platform=config.platform,
        master_data=config.master_data,
        patients=config.patients,
        providers=config.providers,
        encounters=enc_config,
        billing=bill_config,
    )
    return generate_encounter_data(sim_config, upstream)


def test_billing_data_produces_all_datasets(encounter_data: EncounterData) -> None:
    expected = {d.name for d in BILLING_DATASETS}
    actual = {name for name in encounter_data.datasets if name in expected}
    assert actual == expected


def test_billing_has_required_columns(encounter_data: EncounterData) -> None:
    billing = encounter_data.datasets["billing"]
    assert "billing_id" in billing.columns
    assert "encounter_id" in billing.columns
    assert "total_amount" in billing.columns
