"""Tests for the ``eds generate commerce`` command."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from eds.cli.main import app

SEED = ["--seed", "58"]
SMALL_MASTER = ["--products", "40", "--warehouses", "3", "--suppliers", "3"]
SMALL_CUSTOMERS = ["--customers", "60"]


@pytest.fixture
def runner() -> CliRunner:
    """Return a Typer CLI runner."""
    return CliRunner()


@pytest.fixture
def warehouse(runner: CliRunner, tmp_path: Path) -> Path:
    """Generate every earlier feature's output and return the directory."""
    destination = tmp_path / "warehouse"
    for command in (
        ["generate", "master-data", "--output", str(destination), *SEED, *SMALL_MASTER],
        ["generate", "customers", "--output", str(destination), *SEED, *SMALL_CUSTOMERS],
        ["generate", "journey", "--output", str(destination), *SEED],
    ):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output
    return destination


def test_commerce_command_is_listed(runner: CliRunner) -> None:
    """The command appears in the generate group's help."""
    result = runner.invoke(app, ["generate", "--help"])

    assert result.exit_code == 0
    assert "commerce" in result.output


def test_commerce_help_documents_its_options(runner: CliRunner) -> None:
    """The documented options are present."""
    result = runner.invoke(app, ["generate", "commerce", "--help"])

    assert result.exit_code == 0
    assert "--seed" in result.output


def test_only_one_command_was_added(runner: CliRunner) -> None:
    """F004 adds `commerce` and nothing else."""
    result = runner.invoke(app, ["generate", "--help"])

    for name in ("master-data", "customers", "journey", "commerce"):
        assert name in result.output
    assert runner.invoke(app, ["generate", "carts", "--help"]).exit_code != 0


def test_generate_writes_both_datasets(runner: CliRunner, warehouse: Path) -> None:
    """A successful run writes the two documented files."""
    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert result.exit_code == 0, result.output
    assert (warehouse / "shopping_carts.parquet").is_file()
    assert (warehouse / "cart_items.parquet").is_file()


def test_generate_reports_counts_and_validates(runner: CliRunner, warehouse: Path) -> None:
    """The summary names the seed and confirms validation."""
    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert "Seed: 58" in result.output
    assert "Validation passed." in result.output
    assert "shopping_carts" in result.output
    assert "cart_items" in result.output


def test_previous_datasets_are_not_regenerated(runner: CliRunner, warehouse: Path) -> None:
    """Running commerce leaves the earlier files byte-identical."""
    before = {path.name: path.read_bytes() for path in sorted(warehouse.glob("*.parquet"))}

    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    for name, content in before.items():
        assert (warehouse / name).read_bytes() == content, name


def test_written_items_reference_written_carts(runner: CliRunner, warehouse: Path) -> None:
    """The files on disk are referentially consistent."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    carts = pl.read_parquet(warehouse / "shopping_carts.parquet")
    items = pl.read_parquet(warehouse / "cart_items.parquet")
    views = pl.read_parquet(warehouse / "product_views.parquet")

    assert set(items["cart_id"].to_list()) <= set(carts["cart_id"].to_list())
    assert set(items["product_view_id"].to_list()) <= set(views["product_view_id"].to_list())


def test_written_item_counts_agree_with_the_items(runner: CliRunner, warehouse: Path) -> None:
    """`item_count` is correct in the exported files."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    carts = pl.read_parquet(warehouse / "shopping_carts.parquet")
    items = pl.read_parquet(warehouse / "cart_items.parquet")

    actual = items.group_by("cart_id").len().rename({"len": "actual"})
    joined = carts.join(actual, on="cart_id", how="left").with_columns(
        pl.col("actual").fill_null(0)
    )

    assert joined.filter(pl.col("item_count") != pl.col("actual")).height == 0


def test_missing_upstream_data_exits_with_code_two(runner: CliRunner, tmp_path: Path) -> None:
    """Running before the journey command reports what to do next."""
    result = runner.invoke(
        app, ["generate", "commerce", "--output", str(tmp_path / "empty"), *SEED]
    )

    assert result.exit_code == 2
    assert "Upstream data not found" in result.output


def test_missing_product_views_exits_with_code_two(runner: CliRunner, warehouse: Path) -> None:
    """The command needs the F003.3 product views dataset."""
    (warehouse / "product_views.parquet").unlink()

    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert result.exit_code == 2
    assert "product_views" in result.output


def test_dry_run_writes_nothing(runner: CliRunner, warehouse: Path, tmp_path: Path) -> None:
    """A dry run validates but writes no commerce files."""
    destination = tmp_path / "dry"

    result = runner.invoke(
        app,
        [
            "generate",
            "commerce",
            "--source",
            str(warehouse),
            "--output",
            str(destination),
            "--dry-run",
            *SEED,
        ],
    )

    assert result.exit_code == 0
    assert "no files written" in result.output
    assert not destination.exists() or list(destination.glob("*.parquet")) == []


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
                "commerce",
                "--source",
                str(warehouse),
                "--output",
                str(destination),
                *SEED,
            ],
        )
        assert result.exit_code == 0, result.output

    for name in ("shopping_carts", "cart_items"):
        left = pl.read_parquet(outputs[0] / f"{name}.parquet")
        right = pl.read_parquet(outputs[1] / f"{name}.parquet")
        assert left.equals(right), name


def test_no_validate_skips_the_check(runner: CliRunner, warehouse: Path) -> None:
    """Validation can be skipped."""
    result = runner.invoke(
        app,
        ["generate", "commerce", "--output", str(warehouse), "--no-validate", *SEED],
    )

    assert result.exit_code == 0
    assert "Validation passed." not in result.output


def test_bad_config_directory_exits_with_code_two(runner: CliRunner, tmp_path: Path) -> None:
    """A missing config directory is a configuration error."""
    result = runner.invoke(app, ["generate", "commerce", "--config-dir", str(tmp_path / "absent")])

    assert result.exit_code == 2
    assert "Configuration error" in result.output


def test_configuration_is_carried_through_overrides(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """A command-line seed override does not reset the commerce settings."""
    # Copy the whole shipped directory so this stays correct as later
    # features add configuration files, then override the one under test.
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    for source in Path("configs").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "commerce.yaml").write_text(
        "max_quantity: 2\nmax_cart_items: 2\n", encoding="utf-8"
    )

    result = runner.invoke(
        app,
        [
            "generate",
            "commerce",
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
    items = pl.read_parquet(tmp_path / "capped" / "cart_items.parquet")
    carts = pl.read_parquet(tmp_path / "capped" / "shopping_carts.parquet")

    assert max(items["quantity"].to_list()) <= 2
    assert max(carts["item_count"].to_list()) <= 2


def test_full_pipeline_produces_every_dataset(runner: CliRunner, warehouse: Path) -> None:
    """Running all four commands leaves thirty-nine datasets on disk.

    Fourteen from F001, four from F002, six from the journey command, and
    fifteen from the commerce command, which produces the F004 through F010
    datasets.
    """
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert len(list(warehouse.glob("*.parquet"))) == 39
