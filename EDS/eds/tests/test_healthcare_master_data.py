"""Tests for Healthcare master data generation."""

from __future__ import annotations

import polars as pl
import pytest

from eds.domains.healthcare.config import SimulationConfig, load_config
from eds.domains.healthcare.domain.master_data import MASTER_DATA_DATASETS, dataset_names
from eds.domains.healthcare.generators.master_data import MasterData, generate_master_data

TEST_SEED = 20260728


@pytest.fixture(scope="session")
def small_master_data_config():
    config = load_config()
    return config.master_data.model_copy(
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


@pytest.fixture(scope="session")
def master_data(small_master_data_config):
    config = SimulationConfig(
        platform=load_config().platform,
        master_data=small_master_data_config,
    )
    return generate_master_data(config)


def test_master_data_produces_all_datasets(master_data: MasterData) -> None:
    assert set(master_data.datasets) == set(dataset_names())


def test_master_data_datasets_are_ordered(master_data: MasterData) -> None:
    names = tuple(master_data.datasets.keys())
    assert names == dataset_names()


def test_master_data_row_counts_are_positive(master_data: MasterData) -> None:
    for name, frame in master_data.datasets.items():
        assert frame.height > 0, f"{name} has no rows"
