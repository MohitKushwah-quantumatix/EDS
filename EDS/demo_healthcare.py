"""Healthcare domain demo - mirrors demo.py for Retail."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from eds.domains.healthcare.config import load_config
from eds.platform.project.project import create_project
from eds.platform.run.configuration import RunConfiguration
from eds.platform.run.run import create_run
from eds.platform.run.stop import AfterTicks, EndOfPeriod
from eds.platform.scheduler.scheduler import execute
from eds.platform.time.clock import create_clock
from eds.runners.healthcare import HealthcareExecutor

# Configure a small hospital so this finishes quickly
config = load_config()
small = config.model_copy(
    update={
        "master_data": config.master_data.model_copy(
            update={
                "department_count": 5,
                "specialty_count": 5,
                "insurance_plan_count": 5,
                "room_type_count": 5,
                "medication_count": 10,
                "diagnosis_code_count": 5,
                "procedure_code_count": 5,
                "billing_code_count": 5,
                "facility_count": 7,
            }
        ),
        "patients": config.patients.model_copy(update={"patient_count": 40}),
        "providers": config.providers.model_copy(update={"provider_count": 10}),
        "evolution": config.evolution.model_copy(update={"new_patients_per_day": 5, "active_patient_rate": 0.2, "max_daily_encounters": 3}),
    }
)

# Remove existing project if it exists
import shutil
if Path("./my-hospital").exists():
    shutil.rmtree("./my-hospital")

# Create the project folder (mirrors retail's my-shop)
project = create_project(
    Path("./my-hospital"),
    name="My Hospital",
    domain="healthcare",
    seed=42,
)

# Run EVERY day from Jan 1 to Jun 1, 2026. EndOfPeriod advances the clock until
# it reaches the end date, so data is generated for the whole range and spreads
# across it (instead of stopping after a fixed tick count and capping in January).
run = create_run(
    project,
    create_clock(date(2026, 1, 1), end=date(2026, 3, 1)),
    RunConfiguration(stop_condition=EndOfPeriod()),
    run_id="healthcare-demo",
)

report = execute(run, HealthcareExecutor(config=small))

print(f"Run ID: {report.result.run_id}")
print(f"Status: {report.result.status}")
print(f"Completed stages: {report.progress.completed_stages}/{report.progress.total_stages}")
print()
for stage in report.result.stages:
    status_icon = "[OK]" if stage.status.name == "COMPLETED" else "[FAIL]"
    print(f"  {status_icon} {stage.stage_id}: {stage.status.name}")
    if stage.failure:
        print(f"    FAILURE: {stage.failure.message}")
    if stage.rows_by_dataset:
        total_rows = sum(stage.rows_by_dataset.values())
        print(f"    {total_rows:,} rows across {len(stage.rows_by_dataset)} datasets")

# Verify patient count
import polars as pl
patients_df = pl.read_parquet("my-hospital/data/patients.parquet")
print()
print(f"Total patients generated: {len(patients_df)}")
