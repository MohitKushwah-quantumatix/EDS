"""Tests for the ``eds generate journey`` command."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from eds.cli.main import app

SEED = ["--seed", "77"]
SMALL_MASTER = ["--products", "15", "--warehouses", "3", "--suppliers", "3"]
SMALL_CUSTOMERS = ["--customers", "30"]


@pytest.fixture
def runner() -> CliRunner:
    """Return a Typer CLI runner."""
    return CliRunner()


@pytest.fixture
def warehouse(runner: CliRunner, tmp_path: Path) -> Path:
    """Generate F001 and F002 output into a directory and return it."""
    destination = tmp_path / "warehouse"
    master = runner.invoke(
        app, ["generate", "master-data", "--output", str(destination), *SEED, *SMALL_MASTER]
    )
    assert master.exit_code == 0, master.output

    customers = runner.invoke(
        app, ["generate", "customers", "--output", str(destination), *SEED, *SMALL_CUSTOMERS]
    )
    assert customers.exit_code == 0, customers.output
    return destination


def test_journey_command_is_listed(runner: CliRunner) -> None:
    """The command appears in the generate group's help."""
    result = runner.invoke(app, ["generate", "--help"])

    assert result.exit_code == 0
    assert "journey" in result.output


def test_journey_help_documents_its_options(runner: CliRunner) -> None:
    """The documented options are present."""
    result = runner.invoke(app, ["generate", "journey", "--help"])

    assert result.exit_code == 0
    assert "--seed" in result.output


def test_generate_writes_both_datasets(runner: CliRunner, warehouse: Path) -> None:
    """A successful run writes the two documented files."""
    result = runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    assert result.exit_code == 0, result.output
    assert (warehouse / "customer_personas.parquet").is_file()
    assert (warehouse / "sessions.parquet").is_file()


def test_generate_reports_counts_and_validates(runner: CliRunner, warehouse: Path) -> None:
    """The summary names the seed and confirms validation."""
    result = runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    assert "Seed: 77" in result.output
    assert "Validation passed." in result.output
    assert "sessions" in result.output


def test_every_customer_receives_exactly_one_persona(runner: CliRunner, warehouse: Path) -> None:
    """The written personas cover the written customers one-to-one."""
    runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    personas = pl.read_parquet(warehouse / "customer_personas.parquet")
    customers = pl.read_parquet(warehouse / "customers.parquet")

    assert personas.height == customers.height
    assert set(personas["customer_id"].to_list()) == set(customers["customer_id"].to_list())


def test_written_sessions_reference_written_customers(runner: CliRunner, warehouse: Path) -> None:
    """The files on disk are referentially consistent."""
    runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    sessions = pl.read_parquet(warehouse / "sessions.parquet")
    customers = pl.read_parquet(warehouse / "customers.parquet")
    cities = pl.read_parquet(warehouse / "cities.parquet")

    assert set(sessions["customer_id"].to_list()) <= set(customers["customer_id"].to_list())
    assert set(sessions["city_id"].to_list()) <= set(cities["city_id"].to_list())


def test_source_directory_can_be_separate(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """--source reads upstream data from a different directory."""
    destination = tmp_path / "journey-only"

    result = runner.invoke(
        app,
        [
            "generate",
            "journey",
            "--source",
            str(warehouse),
            "--output",
            str(destination),
            *SEED,
        ],
    )

    assert result.exit_code == 0, result.output
    assert (destination / "sessions.parquet").is_file()
    assert not (destination / "customers.parquet").exists()


def test_missing_upstream_data_exits_with_code_two(runner: CliRunner, tmp_path: Path) -> None:
    """Running before F001 and F002 reports what to do next."""
    result = runner.invoke(app, ["generate", "journey", "--output", str(tmp_path / "empty"), *SEED])

    assert result.exit_code == 2
    assert "Upstream data not found" in result.output


def test_missing_customers_alone_exits_with_code_two(runner: CliRunner, tmp_path: Path) -> None:
    """Master data without customers is still incomplete."""
    destination = tmp_path / "master-only"
    runner.invoke(
        app, ["generate", "master-data", "--output", str(destination), *SEED, *SMALL_MASTER]
    )

    result = runner.invoke(app, ["generate", "journey", "--output", str(destination), *SEED])

    assert result.exit_code == 2
    assert "customers" in result.output


def test_dry_run_writes_nothing(runner: CliRunner, warehouse: Path, tmp_path: Path) -> None:
    """A dry run validates but writes no journey files."""
    destination = tmp_path / "dry"

    result = runner.invoke(
        app,
        [
            "generate",
            "journey",
            "--source",
            str(warehouse),
            "--output",
            str(destination),
            "--dry-run",
            *SEED,
        ],
    )

    assert result.exit_code == 0
    assert not destination.exists() or list(destination.glob("*.parquet")) == []
    assert "no files written" in result.output


def test_generation_is_deterministic_across_invocations(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """Two runs with the same seed produce identical files."""
    outputs = [tmp_path / "first", tmp_path / "second"]
    for destination in outputs:
        result = runner.invoke(
            app,
            [
                "generate",
                "journey",
                "--source",
                str(warehouse),
                "--output",
                str(destination),
                *SEED,
            ],
        )
        assert result.exit_code == 0, result.output

    left = pl.read_parquet(outputs[0] / "sessions.parquet")
    right = pl.read_parquet(outputs[1] / "sessions.parquet")

    assert left.equals(right)


def test_no_validate_skips_the_check(runner: CliRunner, warehouse: Path) -> None:
    """Validation can be skipped."""
    result = runner.invoke(
        app, ["generate", "journey", "--output", str(warehouse), "--no-validate", *SEED]
    )

    assert result.exit_code == 0
    assert "Validation passed." not in result.output


def test_bad_config_directory_exits_with_code_two(runner: CliRunner, tmp_path: Path) -> None:
    """A missing config directory is a configuration error."""
    result = runner.invoke(app, ["generate", "journey", "--config-dir", str(tmp_path / "absent")])

    assert result.exit_code == 2
    assert "Configuration error" in result.output


def test_full_pipeline_produces_every_dataset(runner: CliRunner, warehouse: Path) -> None:
    """Running all three commands leaves twenty-four datasets on disk.

    Fourteen from F001, four from F002, and six from the journey command,
    which produces the F003.1, F003.2 and F003.3 datasets.
    """
    runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    assert len(list(warehouse.glob("*.parquet"))) == 24
