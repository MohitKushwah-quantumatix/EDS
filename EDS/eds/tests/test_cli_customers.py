"""Tests for the ``eds generate customers`` command."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from eds.cli.main import app

SEED = ["--seed", "31"]
SMALL_MASTER = ["--products", "20", "--warehouses", "3", "--suppliers", "3"]
SMALL_CUSTOMERS = ["--customers", "40"]


@pytest.fixture
def runner() -> CliRunner:
    """Return a Typer CLI runner."""
    return CliRunner()


@pytest.fixture
def master_output(runner: CliRunner, tmp_path: Path) -> Path:
    """Generate F001 master data into a directory and return it."""
    destination = tmp_path / "warehouse"
    result = runner.invoke(
        app,
        ["generate", "master-data", "--output", str(destination), *SEED, *SMALL_MASTER],
    )
    assert result.exit_code == 0, result.output
    return destination


def test_customers_command_is_listed(runner: CliRunner) -> None:
    """The command appears in the generate group's help."""
    result = runner.invoke(app, ["generate", "--help"])

    assert result.exit_code == 0
    assert "customers" in result.output


def test_customers_help_documents_its_options(runner: CliRunner) -> None:
    """The documented options are present."""
    result = runner.invoke(app, ["generate", "customers", "--help"])

    assert result.exit_code == 0
    assert "--customers" in result.output
    assert "--seed" in result.output


def test_generate_writes_every_customer_dataset(runner: CliRunner, master_output: Path) -> None:
    """A successful run writes the four documented files."""
    result = runner.invoke(
        app,
        ["generate", "customers", "--output", str(master_output), *SEED, *SMALL_CUSTOMERS],
    )

    assert result.exit_code == 0, result.output
    for name in (
        "customers",
        "customer_addresses",
        "customer_preferences",
        "customer_loyalty",
    ):
        assert (master_output / f"{name}.parquet").is_file(), name


def test_generate_reports_counts_and_validates(runner: CliRunner, master_output: Path) -> None:
    """The summary names the seed and confirms validation."""
    result = runner.invoke(
        app,
        ["generate", "customers", "--output", str(master_output), *SEED, *SMALL_CUSTOMERS],
    )

    assert "Seed: 31" in result.output
    assert "Validation passed." in result.output
    assert "customer_loyalty" in result.output


def test_customer_override_is_applied(runner: CliRunner, master_output: Path) -> None:
    """The --customers option overrides the configuration file."""
    runner.invoke(
        app,
        ["generate", "customers", "--output", str(master_output), *SEED, *SMALL_CUSTOMERS],
    )

    assert pl.read_parquet(master_output / "customers.parquet").height == 40


def test_master_data_directory_can_be_separate(
    runner: CliRunner, master_output: Path, tmp_path: Path
) -> None:
    """--master-data reads geography from a different directory."""
    destination = tmp_path / "customers-only"

    result = runner.invoke(
        app,
        [
            "generate",
            "customers",
            "--master-data",
            str(master_output),
            "--output",
            str(destination),
            *SEED,
            *SMALL_CUSTOMERS,
        ],
    )

    assert result.exit_code == 0, result.output
    assert (destination / "customers.parquet").is_file()
    assert not (destination / "products.parquet").exists()


def test_missing_master_data_exits_with_code_two(runner: CliRunner, tmp_path: Path) -> None:
    """Running before F001 reports what to do next."""
    result = runner.invoke(
        app, ["generate", "customers", "--output", str(tmp_path / "empty"), *SEED]
    )

    assert result.exit_code == 2
    assert "Master data not found" in result.output
    assert "generate master-data" in result.output


def test_dry_run_writes_nothing(runner: CliRunner, master_output: Path, tmp_path: Path) -> None:
    """A dry run validates but writes no customer files."""
    destination = tmp_path / "dry"

    result = runner.invoke(
        app,
        [
            "generate",
            "customers",
            "--master-data",
            str(master_output),
            "--output",
            str(destination),
            "--dry-run",
            *SEED,
            *SMALL_CUSTOMERS,
        ],
    )

    assert result.exit_code == 0
    assert not destination.exists() or list(destination.glob("*.parquet")) == []
    assert "no files written" in result.output


def test_generation_is_deterministic_across_invocations(
    runner: CliRunner, master_output: Path, tmp_path: Path
) -> None:
    """Two runs with the same seed produce identical files."""
    outputs = [tmp_path / "first", tmp_path / "second"]
    for destination in outputs:
        result = runner.invoke(
            app,
            [
                "generate",
                "customers",
                "--master-data",
                str(master_output),
                "--output",
                str(destination),
                *SEED,
                *SMALL_CUSTOMERS,
            ],
        )
        assert result.exit_code == 0, result.output

    left = pl.read_parquet(outputs[0] / "customers.parquet")
    right = pl.read_parquet(outputs[1] / "customers.parquet")

    assert left.equals(right)


def test_no_validate_skips_the_check(runner: CliRunner, master_output: Path) -> None:
    """Validation can be skipped."""
    result = runner.invoke(
        app,
        [
            "generate",
            "customers",
            "--output",
            str(master_output),
            "--no-validate",
            *SEED,
            *SMALL_CUSTOMERS,
        ],
    )

    assert result.exit_code == 0
    assert "Validation passed." not in result.output


def test_non_positive_customer_count_is_rejected(runner: CliRunner, master_output: Path) -> None:
    """Typer enforces the documented minimum before the command runs."""
    result = runner.invoke(
        app, ["generate", "customers", "--output", str(master_output), "--customers", "0"]
    )

    assert result.exit_code != 0


def test_bad_config_directory_exits_with_code_two(runner: CliRunner, tmp_path: Path) -> None:
    """A missing config directory is a configuration error."""
    result = runner.invoke(app, ["generate", "customers", "--config-dir", str(tmp_path / "absent")])

    assert result.exit_code == 2
    assert "Configuration error" in result.output


def test_exported_customers_reference_exported_geography(
    runner: CliRunner, master_output: Path
) -> None:
    """The written files are referentially consistent on disk."""
    runner.invoke(
        app,
        ["generate", "customers", "--output", str(master_output), *SEED, *SMALL_CUSTOMERS],
    )

    addresses = pl.read_parquet(master_output / "customer_addresses.parquet")
    cities = pl.read_parquet(master_output / "cities.parquet")

    assert set(addresses["city_id"].to_list()) <= set(cities["city_id"].to_list())
