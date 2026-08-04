"""End-to-end tests for the Healthcare runtime integration."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from eds.adapters.parquet.adapter import ParquetAdapter
from eds.domains.healthcare.config import SimulationConfig, load_config
from eds.domains.healthcare.registry import HealthcareDomain
from eds.platform.execution import plan_domain
from eds.platform.project import Project, create_project, open_project
from eds.platform.run import (
    AfterStage,
    AfterTicks,
    RunConfiguration,
    RunMode,
    SimulationRun,
    create_run,
)
from eds.platform.runtime import ExecutionStatus, RunCompleted, StageCompleted, StageStarted, in_sequence
from eds.platform.scheduler import ExecutionReport, StageExecutor, StageOutput, StageRequest, execute
from eds.platform.time import create_clock
from eds.runners.healthcare import HealthcareExecutor

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DAY = date(2026, 1, 1)

HEALTHCARE_STAGE_IDS = (
    "healthcare:master-data",
    "healthcare:patients",
    "healthcare:providers",
    "healthcare:encounters",
)


@pytest.fixture(scope="module")
def small_config() -> SimulationConfig:
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


@pytest.fixture
def executor(small_config: SimulationConfig) -> HealthcareExecutor:
    return HealthcareExecutor(config=small_config)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return create_project(tmp_path / "hospital", name="Hospital", domain="healthcare", seed=42)


@pytest.fixture
def clock():
    return create_clock(DAY, end=DAY)


@pytest.fixture
def one_tick():
    return RunConfiguration(stop_condition=AfterTicks(1))


def test_a_full_healthcare_simulation_runs_through_the_platform(
    tmp_path: Path, small_config: SimulationConfig
) -> None:
    shop = create_project(tmp_path / "hospital", name="Hospital", domain="healthcare", seed=42)
    run = create_run(
        shop,
        create_clock(DAY, end=DAY),
        RunConfiguration(stop_condition=AfterTicks(1)),
        run_id="r1",
    )
    report = execute(run, HealthcareExecutor(config=small_config))
    assert report.succeeded
    assert report.result.status is ExecutionStatus.COMPLETED


def test_every_declared_dataset_is_produced(
    tmp_path: Path, small_config: SimulationConfig
) -> None:
    shop = create_project(tmp_path / "hospital", name="Hospital", domain="healthcare", seed=42)
    run = create_run(
        shop,
        create_clock(DAY, end=DAY),
        RunConfiguration(stop_condition=AfterTicks(1)),
        run_id="r1",
    )
    report = execute(run, HealthcareExecutor(config=small_config))
    assert set(report.result.rows_by_dataset) == set(HealthcareDomain().dataset_names)


def test_the_platform_does_not_know_healthcare_exists() -> None:
    for source in (PACKAGE_ROOT / "platform").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "eds.domains.healthcare" not in text, f"{source.name} imports healthcare"


def test_healthcare_runner_modules_are_importable() -> None:
    import importlib
    for name in [
        "eds.runners.healthcare",
        "eds.runners.healthcare.executor",
        "eds.runners.healthcare.stages",
    ]:
        module = importlib.import_module(name)
        assert module.__doc__ is not None
        assert module.__doc__.strip()
