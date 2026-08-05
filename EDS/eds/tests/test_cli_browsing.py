"""Tests for the browsing datasets produced by ``eds generate journey``.

F003.2 introduces no new command: the existing journey command now writes the
category view and search datasets alongside the personas and sessions.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from eds.cli.main import app

SEED = ["--seed", "91"]
SMALL_MASTER = ["--products", "15", "--warehouses", "3", "--suppliers", "3"]
SMALL_CUSTOMERS = ["--customers", "30"]

JOURNEY_OUTPUTS = (
    "customer_personas",
    "sessions",
    "category_views",
    "search_history",
)


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


def test_no_new_command_was_introduced(runner: CliRunner) -> None:
    """Browsing is produced by the existing journey command."""
    listing = runner.invoke(app, ["generate", "--help"])
    assert listing.exit_code == 0
    assert "journey" in listing.output

    # There is no `eds generate browsing`; the journey command covers it.
    result = runner.invoke(app, ["generate", "browsing", "--help"])

    assert result.exit_code != 0


def test_journey_writes_all_four_datasets(runner: CliRunner, warehouse: Path) -> None:
    """The command now produces the F003.1 and F003.2 outputs together."""
    result = runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    assert result.exit_code == 0, result.output
    for name in JOURNEY_OUTPUTS:
        assert (warehouse / f"{name}.parquet").is_file(), name


def test_report_lists_the_browsing_datasets(runner: CliRunner, warehouse: Path) -> None:
    """The summary covers all four datasets and validation passes."""
    result = runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    assert "category_views" in result.output
    assert "search_history" in result.output
    assert "6 datasets" in result.output
    assert "Validation passed." in result.output


def test_written_views_reference_written_sessions(runner: CliRunner, warehouse: Path) -> None:
    """The files on disk are referentially consistent."""
    runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    views = pl.read_parquet(warehouse / "category_views.parquet")
    sessions = pl.read_parquet(warehouse / "sessions.parquet")
    categories = pl.read_parquet(warehouse / "categories.parquet")

    assert set(views["session_id"].to_list()) <= set(sessions["session_id"].to_list())
    assert set(views["category_id"].to_list()) <= set(categories["category_id"].to_list())


def test_written_searches_match_their_category_views(runner: CliRunner, warehouse: Path) -> None:
    """Search and view categories agree in the exported files."""
    runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    searches = pl.read_parquet(warehouse / "search_history.parquet")
    views = pl.read_parquet(warehouse / "category_views.parquet")

    joined = searches.join(
        views.select("category_view_id", pl.col("category_id").alias("view_category")),
        on="category_view_id",
        how="inner",
    )

    assert joined.height == searches.height
    assert joined.filter(pl.col("category_id") != pl.col("view_category")).height == 0


def test_every_session_has_a_category_view(runner: CliRunner, warehouse: Path) -> None:
    """No exported session is left without browsing activity."""
    runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    views = pl.read_parquet(warehouse / "category_views.parquet")
    sessions = pl.read_parquet(warehouse / "sessions.parquet")

    assert views["session_id"].n_unique() == sessions.height


def test_missing_categories_exits_with_code_two(runner: CliRunner, warehouse: Path) -> None:
    """The command needs the F001 categories dataset."""
    (warehouse / "categories.parquet").unlink()

    result = runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    assert result.exit_code == 2
    assert "categories" in result.output


def test_dry_run_writes_no_browsing_files(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """A dry run validates all four datasets but writes none."""
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
    assert "category_views" in result.output
    assert not destination.exists() or list(destination.glob("*.parquet")) == []


def test_generation_is_deterministic_across_invocations(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """Two runs with the same seed produce identical browsing files."""
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

    for name in ("category_views", "search_history"):
        left = pl.read_parquet(outputs[0] / f"{name}.parquet")
        right = pl.read_parquet(outputs[1] / f"{name}.parquet")
        assert left.equals(right), name


def test_configuration_is_carried_through_overrides(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """A command-line seed override does not reset the browsing settings."""
    # Copy the whole shipped directory so this stays correct as later
    # features add configuration files, then override the one under test.
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    for source in Path("configs").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    for source in Path("configs/retail").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "browsing.yaml").write_text(
        "max_category_views: 3\nmax_view_seconds: 60\n", encoding="utf-8"
    )

    result = runner.invoke(
        app,
        [
            "generate",
            "journey",
            "--config-dir",
            str(config_dir),
            "--source",
            str(warehouse),
            "--output",
            str(tmp_path / "capped"),
            *SEED,
        ],
    )

    assert result.exit_code == 0, result.output
    views = pl.read_parquet(tmp_path / "capped" / "category_views.parquet")
    counts = views.group_by("session_id").len()["len"].to_list()

    assert max(counts) <= 3
    assert max(views["duration_seconds"].to_list()) <= 60
