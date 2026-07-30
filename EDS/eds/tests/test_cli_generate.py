"""Tests for the ``eds generate master-data`` command."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from eds.cli.main import app

CONFIG_DIR = Path(__file__).parent.parent.parent / "configs"

SMALL_RUN = ["--products", "20", "--warehouses", "3", "--suppliers", "3"]


@pytest.fixture
def runner() -> CliRunner:
    """Return a Typer CLI runner."""
    return CliRunner()


def test_generate_group_is_listed_in_help(runner: CliRunner) -> None:
    """The generate group is reachable from the root command."""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "generate" in result.output


def test_master_data_help_exits_cleanly(runner: CliRunner) -> None:
    """The command documents its options."""
    result = runner.invoke(app, ["generate", "master-data", "--help"])

    assert result.exit_code == 0
    assert "--seed" in result.output


def test_generate_writes_every_dataset(runner: CliRunner, tmp_path: Path) -> None:
    """A successful run writes fourteen Parquet files."""
    result = runner.invoke(
        app,
        ["generate", "master-data", "--output", str(tmp_path), "--seed", "7", *SMALL_RUN],
    )

    assert result.exit_code == 0, result.output
    assert len(list(tmp_path.glob("*.parquet"))) == 14
    assert (tmp_path / "products.parquet").is_file()


def test_generate_reports_counts_and_seed(runner: CliRunner, tmp_path: Path) -> None:
    """The summary names the seed and the row counts."""
    result = runner.invoke(
        app,
        ["generate", "master-data", "--output", str(tmp_path), "--seed", "7", *SMALL_RUN],
    )

    assert "Seed: 7" in result.output
    assert "products" in result.output
    assert "Validation passed." in result.output


def test_product_override_is_applied(runner: CliRunner, tmp_path: Path) -> None:
    """The --products option overrides the configuration file."""
    runner.invoke(
        app,
        ["generate", "master-data", "--output", str(tmp_path), "--seed", "7", *SMALL_RUN],
    )

    assert pl.read_parquet(tmp_path / "products.parquet").height == 20


def test_dry_run_writes_nothing(runner: CliRunner, tmp_path: Path) -> None:
    """A dry run validates but leaves the output directory empty."""
    result = runner.invoke(
        app,
        [
            "generate",
            "master-data",
            "--output",
            str(tmp_path),
            "--seed",
            "7",
            "--dry-run",
            *SMALL_RUN,
        ],
    )

    assert result.exit_code == 0
    assert list(tmp_path.glob("*.parquet")) == []
    assert "no files written" in result.output


def test_generation_is_deterministic_across_invocations(runner: CliRunner, tmp_path: Path) -> None:
    """Two runs with the same seed produce identical files."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    for destination in (first, second):
        runner.invoke(
            app,
            [
                "generate",
                "master-data",
                "--output",
                str(destination),
                "--seed",
                "123",
                *SMALL_RUN,
            ],
        )

    left = pl.read_parquet(first / "products.parquet")
    right = pl.read_parquet(second / "products.parquet")

    assert left.equals(right)


def test_no_validate_skips_the_check(runner: CliRunner, tmp_path: Path) -> None:
    """Validation can be skipped for speed."""
    result = runner.invoke(
        app,
        [
            "generate",
            "master-data",
            "--output",
            str(tmp_path),
            "--seed",
            "7",
            "--no-validate",
            *SMALL_RUN,
        ],
    )

    assert result.exit_code == 0
    assert "Validation passed." not in result.output


def test_missing_config_directory_exits_with_code_two(runner: CliRunner, tmp_path: Path) -> None:
    """A bad --config-dir is a configuration error."""
    result = runner.invoke(
        app, ["generate", "master-data", "--config-dir", str(tmp_path / "absent")]
    )

    assert result.exit_code == 2
    assert "Configuration error" in result.output


def test_invalid_override_exits_with_code_two(runner: CliRunner, tmp_path: Path) -> None:
    """Stocking more warehouses than exist is refused before generating."""
    result = runner.invoke(
        app,
        ["generate", "master-data", "--output", str(tmp_path), "--warehouses", "1"],
    )

    assert result.exit_code == 2
    assert "Configuration error" in result.output


def test_non_positive_product_count_is_rejected(runner: CliRunner, tmp_path: Path) -> None:
    """Typer enforces the documented minimum before the command runs."""
    result = runner.invoke(
        app, ["generate", "master-data", "--output", str(tmp_path), "--products", "0"]
    )

    assert result.exit_code != 0


def test_shipped_config_directory_is_usable(runner: CliRunner, tmp_path: Path) -> None:
    """The committed configs drive a real run."""
    result = runner.invoke(
        app,
        [
            "generate",
            "master-data",
            "--config-dir",
            str(CONFIG_DIR),
            "--output",
            str(tmp_path),
            "--dry-run",
            *SMALL_RUN,
        ],
    )

    assert result.exit_code == 0, result.output
