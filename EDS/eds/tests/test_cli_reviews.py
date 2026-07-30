"""Tests for the review dataset produced by ``eds generate commerce``.

F010 introduces no new command: the existing commerce command now writes
``reviews.parquet`` alongside everything F004 to F009 produce. This is the last
feature of Enterprise Data Simulator v1.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from eds.cli.main import app

SEED = ["--seed", "24"]
SMALL_MASTER = ["--products", "40", "--warehouses", "3", "--suppliers", "3"]
SMALL_CUSTOMERS = ["--customers", "80"]

#: Every dataset the commerce command writes, in the order it produces them.
COMMERCE_OUTPUTS = (
    "shopping_carts",
    "cart_items",
    "checkout",
    "orders",
    "order_lines",
    "order_status_history",
    "payments",
    "payment_status_history",
    "shipments",
    "shipment_items",
    "shipment_status_history",
    "returns",
    "return_items",
    "return_status_history",
    "reviews",
)


@pytest.fixture
def runner() -> CliRunner:
    """Return a Typer CLI runner."""
    return CliRunner()


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Return a config directory whose review rate suits a small fixture.

    The shipped 18 per cent would leave a handful of reviews at CLI-test scale,
    which is too few to assert anything useful about.
    """
    destination = tmp_path / "configs"
    destination.mkdir()
    for source in Path("configs").glob("*.yaml"):
        (destination / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    reviews = destination / "reviews.yaml"
    reviews.write_text(
        reviews.read_text(encoding="utf-8").replace("review_rate: 0.18", "review_rate: 0.8"),
        encoding="utf-8",
    )
    return destination


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


def _run(runner: CliRunner, warehouse: Path, config_dir: Path) -> None:
    """Run the commerce command against the prepared warehouse."""
    result = runner.invoke(
        app,
        [
            "generate",
            "commerce",
            "--config-dir",
            str(config_dir),
            "--output",
            str(warehouse),
            *SEED,
        ],
    )
    assert result.exit_code == 0, result.output


def test_no_new_command_was_introduced(runner: CliRunner) -> None:
    """Reviews are produced by the existing commerce command."""
    listing = runner.invoke(app, ["generate", "--help"])
    assert listing.exit_code == 0
    assert "commerce" in listing.output

    assert runner.invoke(app, ["generate", "reviews", "--help"]).exit_code != 0


def test_the_command_set_is_unchanged(runner: CliRunner) -> None:
    """v1 ships exactly four generate commands."""
    listing = runner.invoke(app, ["generate", "--help"])

    for command in ("master-data", "customers", "journey", "commerce"):
        assert command in listing.output, command


def test_commerce_writes_the_review_dataset(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """The command now produces the F010 output alongside the earlier ones."""
    _run(runner, warehouse, config_dir)

    assert (warehouse / "reviews.parquet").is_file()


def test_commerce_writes_every_documented_dataset(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """All fifteen commerce datasets land on disk."""
    _run(runner, warehouse, config_dir)

    for name in COMMERCE_OUTPUTS:
        assert (warehouse / f"{name}.parquet").is_file(), name


def test_report_lists_the_review_dataset(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """The summary covers all fifteen datasets and validation passes."""
    result = runner.invoke(
        app,
        [
            "generate",
            "commerce",
            "--config-dir",
            str(config_dir),
            "--output",
            str(warehouse),
            *SEED,
        ],
    )

    assert "reviews" in result.output
    assert "15 datasets" in result.output
    assert "Validation passed." in result.output


def test_written_reviews_come_from_delivered_unreturned_items(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """The files on disk honour both halves of the eligibility rule."""
    _run(runner, warehouse, config_dir)

    reviews = pl.read_parquet(warehouse / "reviews.parquet")
    shipments = pl.read_parquet(warehouse / "shipments.parquet")
    return_items = pl.read_parquet(warehouse / "return_items.parquet")

    delivered = set(
        shipments.filter(pl.col("current_status") == "DELIVERED")["shipment_id"].to_list()
    )
    returned = set(return_items["shipment_item_id"].to_list())

    assert reviews.height > 0
    assert set(reviews["shipment_id"].to_list()) <= delivered
    assert not (set(reviews["shipment_item_id"].to_list()) & returned)
    assert reviews["shipment_item_id"].n_unique() == reviews.height


def test_written_reviews_are_all_verified(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """verified_purchase survives the round trip as a constant true."""
    _run(runner, warehouse, config_dir)

    reviews = pl.read_parquet(warehouse / "reviews.parquet")

    assert reviews["verified_purchase"].all()


def test_written_ratings_are_in_range(runner: CliRunner, warehouse: Path, config_dir: Path) -> None:
    """Stars run from one to five on disk."""
    _run(runner, warehouse, config_dir)

    reviews = pl.read_parquet(warehouse / "reviews.parquet")

    assert reviews.filter((pl.col("rating") < 1) | (pl.col("rating") > 5)).height == 0


def test_written_wording_comes_from_configuration(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """Titles and bodies on disk are ones the config file offered."""
    _run(runner, warehouse, config_dir)

    reviews = pl.read_parquet(warehouse / "reviews.parquet")
    shipped = (config_dir / "reviews.yaml").read_text(encoding="utf-8")

    for title in reviews["review_title"].unique().to_list():
        assert title in shipped, title
    for text in reviews["review_text"].unique().to_list():
        assert text in shipped, text


def test_written_review_numbers_are_well_formed(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """The business identifier survives the round trip."""
    _run(runner, warehouse, config_dir)

    reviews = pl.read_parquet(warehouse / "reviews.parquet")
    pattern = re.compile(r"^REV-\d{8}-\d{6}$")

    assert reviews["review_number"].n_unique() == reviews.height
    assert all(pattern.match(number) for number in reviews["review_number"].to_list())


def test_written_reviews_follow_delivery(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """created_at is after delivered_at on disk."""
    _run(runner, warehouse, config_dir)

    reviews = pl.read_parquet(warehouse / "reviews.parquet")
    shipments = pl.read_parquet(warehouse / "shipments.parquet")

    joined = reviews.join(
        shipments.select("shipment_id", pl.col("delivered_at").alias("arrived_at")),
        on="shipment_id",
    )

    assert joined.filter(pl.col("created_at") < pl.col("arrived_at")).height == 0


def test_previous_datasets_are_not_regenerated(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """Running commerce leaves the journey and master files byte-identical."""
    before = {path.name: path.read_bytes() for path in sorted(warehouse.glob("*.parquet"))}

    _run(runner, warehouse, config_dir)

    for name, content in before.items():
        assert (warehouse / name).read_bytes() == content, name


def test_dry_run_writes_nothing(
    runner: CliRunner, warehouse: Path, config_dir: Path, tmp_path: Path
) -> None:
    """A dry run validates the reviews but writes none of them."""
    destination = tmp_path / "dry"

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
            str(destination),
            "--dry-run",
            *SEED,
        ],
    )

    assert result.exit_code == 0
    assert "reviews" in result.output
    assert not destination.exists() or list(destination.glob("*.parquet")) == []


def test_generation_is_deterministic_across_invocations(
    runner: CliRunner, warehouse: Path, config_dir: Path, tmp_path: Path
) -> None:
    """Two runs with the same seed produce an identical review file."""
    outputs = [tmp_path / "first", tmp_path / "second"]
    for destination in outputs:
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
                str(destination),
                *SEED,
            ],
        )
        assert result.exit_code == 0, result.output

    left = pl.read_parquet(outputs[0] / "reviews.parquet")
    right = pl.read_parquet(outputs[1] / "reviews.parquet")

    assert left.equals(right)


def test_configuration_is_carried_through_overrides(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """A command-line seed override does not reset the review settings."""
    # Copy the whole shipped directory so this stays correct as later
    # features add configuration files, then override the one under test.
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    for source in Path("configs").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "reviews.yaml").write_text(
        "review_rate: 1.0\n"
        "rating_weights:\n"
        "  1: 1.0\n"
        "titles:\n"
        "  1:\n"
        "    - Utterly Awful\n"
        "texts:\n"
        "  1:\n"
        "    - It broke on the first day.\n"
        "review_number_prefix: RVW\n",
        encoding="utf-8",
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
            str(tmp_path / "custom"),
            *SEED,
        ],
    )

    assert result.exit_code == 0, result.output
    reviews = pl.read_parquet(tmp_path / "custom" / "reviews.parquet")

    assert reviews["rating"].unique().to_list() == [1]
    assert reviews["review_title"].unique().to_list() == ["Utterly Awful"]
    assert reviews["review_text"].unique().to_list() == ["It broke on the first day."]
    assert all(number.startswith("RVW-") for number in reviews["review_number"].to_list())


def test_full_pipeline_produces_every_dataset(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """Running all four commands leaves thirty-nine datasets on disk.

    Fourteen from F001, four from F002, six from the journey command, and
    fifteen from the commerce command, which produces the F004 through F010
    datasets. That is the complete Enterprise Data Simulator v1 output.
    """
    _run(runner, warehouse, config_dir)

    assert len(list(warehouse.glob("*.parquet"))) == 39
