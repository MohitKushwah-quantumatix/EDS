"""Tests for Healthcare provider generation."""

from __future__ import annotations

import polars as pl
import pytest

from eds.domains.healthcare.config import SimulationConfig, load_config
from eds.domains.healthcare.domain.provider.schema import PROVIDER_DATASETS, provider_dataset_names
from eds.domains.healthcare.generators.provider_data import ProviderData, generate_provider_data

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
def provider_data(master_data):
    config = load_config()
    prov_config = config.providers.model_copy(update={"provider_count": 10})
    sim_config = SimulationConfig(
        platform=config.platform,
        master_data=config.master_data,
        providers=prov_config,
    )
    return generate_provider_data(sim_config, master_data.datasets)


def test_provider_data_produces_all_datasets(provider_data: ProviderData) -> None:
    assert set(provider_data.datasets) == set(provider_dataset_names())


def test_providers_have_required_columns(provider_data: ProviderData) -> None:
    providers = provider_data.datasets["providers"]
    assert "provider_id" in providers.columns
    assert "provider_number" in providers.columns
    assert "full_name" in providers.columns


def test_provider_departments_reference_providers(provider_data: ProviderData) -> None:
    pd = provider_data.datasets["provider_departments"]
    provider_ids = set(provider_data.datasets["providers"]["provider_id"].to_list())
    assert set(pd["provider_id"].to_list()).issubset(provider_ids)
