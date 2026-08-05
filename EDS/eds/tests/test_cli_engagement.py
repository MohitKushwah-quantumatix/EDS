"""Tests for the engagement datasets produced by ``eds generate journey``.

F003.3 introduces no new command: the existing journey command now writes the
product view and wishlist datasets alongside the earlier journey output.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from eds.cli.main import app

SEED = ["--seed", "64"]
SMALL_MASTER = ["--products", "40", "--warehouses", "3", "--suppliers", "3"]
SMALL_CUSTOMERS = ["--customers", "30"]

JOURNEY_OUTPUTS = (
    "customer_personas",
    "sessions",
    "category_views",
    "search_history",
    "product_views",
    "wishlists",
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
    """Engagement is produced by the existing journey command."""
    result = runner.invoke(app, ["generate", "engagement", "--help"])

    assert result.exit_code != 0


def test_journey_writes_all_six_datasets(runner: CliRunner, warehouse: Path) -> None:
    """The command now produces every journey dataset together."""
    result = runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    assert result.exit_code == 0, result.output
    for name in JOURNEY_OUTPUTS:
        assert (warehouse / f"{name}.parquet").is_file(), name


def test_report_lists_the_engagement_datasets(runner: CliRunner, warehouse: Path) -> None:
    """The summary covers all six datasets and validation passes."""
    result = runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    assert "product_views" in result.output
    assert "wishlists" in result.output
    assert "6 datasets" in result.output
    assert "Validation passed." in result.output


def test_written_product_views_reference_written_data(runner: CliRunner, warehouse: Path) -> None:
    """The files on disk are referentially consistent."""
    runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    views = pl.read_parquet(warehouse / "product_views.parquet")
    sessions = pl.read_parquet(warehouse / "sessions.parquet")
    category_views = pl.read_parquet(warehouse / "category_views.parquet")
    products = pl.read_parquet(warehouse / "products.parquet")

    assert set(views["session_id"].to_list()) <= set(sessions["session_id"].to_list())
    assert set(views["category_view_id"].to_list()) <= set(
        category_views["category_view_id"].to_list()
    )
    assert set(views["product_id"].to_list()) <= set(products["product_id"].to_list())


def test_written_wishlists_originate_from_written_views(runner: CliRunner, warehouse: Path) -> None:
    """Wishlist entries trace back to a product view in the exported files."""
    runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    wishlists = pl.read_parquet(warehouse / "wishlists.parquet")
    views = pl.read_parquet(warehouse / "product_views.parquet")

    joined = wishlists.join(
        views.select("product_view_id", pl.col("product_id").alias("viewed")),
        on="product_view_id",
        how="inner",
    )

    assert joined.height == wishlists.height
    assert joined.filter(pl.col("product_id") != pl.col("viewed")).height == 0


def test_missing_products_exits_with_code_two(runner: CliRunner, warehouse: Path) -> None:
    """The command needs the F001 products dataset."""
    (warehouse / "products.parquet").unlink()

    result = runner.invoke(app, ["generate", "journey", "--output", str(warehouse), *SEED])

    assert result.exit_code == 2
    assert "products" in result.output


def test_dry_run_writes_no_engagement_files(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """A dry run validates all six datasets but writes none."""
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
    assert "product_views" in result.output
    assert not destination.exists() or list(destination.glob("*.parquet")) == []


def test_generation_is_deterministic_across_invocations(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """Two runs with the same seed produce identical engagement files."""
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

    for name in ("product_views", "wishlists"):
        left = pl.read_parquet(outputs[0] / f"{name}.parquet")
        right = pl.read_parquet(outputs[1] / f"{name}.parquet")
        assert left.equals(right), name


def test_configuration_is_carried_through_overrides(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """A command-line seed override does not reset the engagement settings."""
    # Copy the whole shipped directory so this stays correct as later
    # features add configuration files, then override the one under test.
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    for source in Path("configs").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    for source in Path("configs/retail").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "engagement.yaml").write_text(
        "max_product_views: 2\nmax_view_seconds: 90\n", encoding="utf-8"
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
    views = pl.read_parquet(tmp_path / "capped" / "product_views.parquet")
    counts = views.group_by("category_view_id").len()["len"].to_list()

    assert max(counts) <= 2
    assert max(views["view_duration_seconds"].to_list()) <= 90
