"""Tests for Healthcare over simulated time."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from eds.domains.healthcare.config import SimulationConfig, load_config
from eds.domains.healthcare.registry import HealthcareDomain
from eds.domains.healthcare.temporal.context import BusinessContext
from eds.domains.healthcare.temporal.datasets import HEALTHCARE_DATASETS
from eds.domains.healthcare.temporal.day import advance_day
from eds.domains.healthcare.temporal.temporality import (
    Temporality,
    DATASET_TEMPORALITY,
)
from eds.platform.project.project import Project, create_project
from eds.platform.run.configuration import RunConfiguration
from eds.platform.run.mode import RunMode
from eds.platform.run.run import create_run
from eds.platform.run.stop import AfterStage, AfterTicks
from eds.platform.scheduler.scheduler import execute
from eds.platform.time.clock import create_clock
from eds.runners.healthcare import HealthcareExecutor

DAY = date(2026, 1, 1)


def _configured():
    config = load_config()
    return config.model_copy(
        update={
            "master_data": config.master_data.model_copy(update={
                "department_count": 3,
                "specialty_count": 3,
                "insurance_plan_count": 3,
                "room_type_count": 3,
                "medication_count": 10,
                "diagnosis_code_count": 5,
                "procedure_code_count": 5,
                "billing_code_count": 5,
                "facility_count": 2,
            }),
            "patients": config.patients.model_copy(update={"patient_count": 40}),
            "providers": config.providers.model_copy(update={"provider_count": 10}),
        }
    )


def test_every_dataset_declares_how_it_behaves_in_time() -> None:
    expected = set(HealthcareDomain().dataset_names)
    actual = set(DATASET_TEMPORALITY.keys())
    assert actual == expected, f"Missing temporality declarations: {expected - actual}"


def test_an_unclassified_dataset_is_refused() -> None:
    from eds.domains.healthcare.temporal.temporality import temporality_of
    with pytest.raises(KeyError):
        temporality_of("nonexistent_dataset")


def test_a_founding_day_founds_an_enterprise(tmp_path: Path) -> None:
    config = _configured()
    shop = create_project(tmp_path, name="Hospital", domain="healthcare", seed=42)
    run = create_run(
        shop,
        create_clock(DAY, end=DAY),
        RunConfiguration(stop_condition=AfterTicks(1)),
    )
    report = execute(run, HealthcareExecutor(config=config))
    assert report.succeeded
