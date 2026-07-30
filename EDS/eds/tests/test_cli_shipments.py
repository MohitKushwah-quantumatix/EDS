"""Tests for the shipment datasets produced by ``eds generate commerce``.

F008 introduces no new command: the existing commerce command now writes the
three shipment datasets alongside the carts, checkouts, orders, and payments.
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

SHIPMENT_OUTPUTS = ("shipments", "shipment_items", "shipment_status_history")


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


def test_no_new_command_was_introduced(runner: CliRunner) -> None:
    """Shipments are produced by the existing commerce command."""
    listing = runner.invoke(app, ["generate", "--help"])
    assert listing.exit_code == 0
    assert "commerce" in listing.output

    assert runner.invoke(app, ["generate", "shipments", "--help"]).exit_code != 0


def test_commerce_writes_the_shipment_datasets(runner: CliRunner, warehouse: Path) -> None:
    """The command now produces the F008 outputs alongside the earlier ones."""
    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert result.exit_code == 0, result.output
    for name in SHIPMENT_OUTPUTS:
        assert (warehouse / f"{name}.parquet").is_file(), name


def test_report_lists_the_shipment_datasets(runner: CliRunner, warehouse: Path) -> None:
    """The summary covers the shipment datasets and validation passes."""
    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    for name in SHIPMENT_OUTPUTS:
        assert name in result.output, name
    assert "Validation passed." in result.output


def test_written_shipments_come_from_captured_payments(runner: CliRunner, warehouse: Path) -> None:
    """The files on disk honour the eligibility rule."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    shipments = pl.read_parquet(warehouse / "shipments.parquet")
    payments = pl.read_parquet(warehouse / "payments.parquet")

    captured = set(payments.filter(pl.col("payment_status") == "CAPTURED")["payment_id"].to_list())

    assert set(shipments["payment_id"].to_list()) == captured
    assert shipments["payment_id"].n_unique() == shipments.height


def test_written_carriers_match_their_shipping_method(runner: CliRunner, warehouse: Path) -> None:
    """Carrier selection depends on the shipping method."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    shipments = pl.read_parquet(warehouse / "shipments.parquet")
    expected = {
        "STANDARD": {"UPS", "FedEx", "DHL"},
        "EXPRESS": {"FedEx Priority", "DHL Express"},
        "NEXT_DAY": {"UPS Next Day"},
        "STORE_PICKUP": {"Store Pickup"},
    }

    for row in shipments.select("shipping_method", "carrier").unique().to_dicts():
        assert row["carrier"] in expected[row["shipping_method"]], row


def test_written_tracking_numbers_are_well_formed(runner: CliRunner, warehouse: Path) -> None:
    """The carrier reference survives the round trip."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    shipments = pl.read_parquet(warehouse / "shipments.parquet")
    pattern = re.compile(r"^TRK-\d{10}$")

    assert shipments["tracking_number"].n_unique() == shipments.height
    assert all(pattern.match(number) for number in shipments["tracking_number"].to_list())


def test_written_shipment_numbers_are_well_formed(runner: CliRunner, warehouse: Path) -> None:
    """The business identifier survives the round trip."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    shipments = pl.read_parquet(warehouse / "shipments.parquet")
    pattern = re.compile(r"^SHP-\d{8}-\d{6}$")

    assert shipments["shipment_number"].n_unique() == shipments.height
    assert all(pattern.match(number) for number in shipments["shipment_number"].to_list())


def test_written_items_reconcile_with_their_order_lines(runner: CliRunner, warehouse: Path) -> None:
    """Every line of a shipped order goes out, at its own quantity."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    shipments = pl.read_parquet(warehouse / "shipments.parquet")
    items = pl.read_parquet(warehouse / "shipment_items.parquet")
    lines = pl.read_parquet(warehouse / "order_lines.parquet")

    expected = lines.join(shipments.select("order_id"), on="order_id", how="semi")
    assert set(items["order_line_id"].to_list()) == set(expected["order_line_id"].to_list())

    joined = items.join(lines, on="order_line_id", how="inner", suffix="_line")
    assert joined.filter(pl.col("quantity") != pl.col("quantity_line")).height == 0


def test_written_current_status_matches_the_history(runner: CliRunner, warehouse: Path) -> None:
    """The denormalised status agrees with the history on disk."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    shipments = pl.read_parquet(warehouse / "shipments.parquet")
    history = pl.read_parquet(warehouse / "shipment_status_history.parquet")

    latest = (
        history.sort("shipment_id", "sequence")
        .group_by("shipment_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest"))
    )
    joined = shipments.join(latest, on="shipment_id", how="inner")

    assert joined.height == shipments.height
    assert joined.filter(pl.col("current_status") != pl.col("latest")).height == 0


def test_written_timeline_is_chronological(runner: CliRunner, warehouse: Path) -> None:
    """Payment, creation, dispatch and delivery run in order on disk."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    shipments = pl.read_parquet(warehouse / "shipments.parquet")
    payments = pl.read_parquet(warehouse / "payments.parquet")

    joined = shipments.join(
        payments.select("payment_id", pl.col("captured_at").alias("paid_at")), on="payment_id"
    )

    assert joined.filter(pl.col("created_at") <= pl.col("paid_at")).height == 0
    assert shipments.filter(pl.col("shipped_at") <= pl.col("created_at")).height == 0
    delivered = shipments.filter(pl.col("delivered_at").is_not_null())
    assert delivered.filter(pl.col("delivered_at") <= pl.col("shipped_at")).height == 0


def test_previous_datasets_are_not_regenerated(runner: CliRunner, warehouse: Path) -> None:
    """Running commerce leaves the journey and master files byte-identical."""
    before = {path.name: path.read_bytes() for path in sorted(warehouse.glob("*.parquet"))}

    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    for name, content in before.items():
        assert (warehouse / name).read_bytes() == content, name


def test_dry_run_writes_nothing(runner: CliRunner, warehouse: Path, tmp_path: Path) -> None:
    """A dry run validates the shipments but writes none of them."""
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
    assert "shipments" in result.output
    assert not destination.exists() or list(destination.glob("*.parquet")) == []


def test_generation_is_deterministic_across_invocations(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """Two runs with the same seed produce identical shipment files."""
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

    for name in SHIPMENT_OUTPUTS:
        left = pl.read_parquet(outputs[0] / f"{name}.parquet")
        right = pl.read_parquet(outputs[1] / f"{name}.parquet")
        assert left.equals(right), name


def test_configuration_is_carried_through_overrides(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """A command-line seed override does not reset the shipment settings."""
    # Copy the whole shipped directory so this stays correct as later
    # features add configuration files, then override the one under test.
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    for source in Path("configs").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "shipments.yaml").write_text(
        "carriers:\n"
        "  STANDARD: [Royal Mail]\n"
        "  EXPRESS: [Royal Mail]\n"
        "  NEXT_DAY: [Royal Mail]\n"
        "  STORE_PICKUP: [Royal Mail]\n"
        "delivery_days:\n"
        "  STANDARD: [2, 2]\n"
        "  EXPRESS: [2, 2]\n"
        "  NEXT_DAY: [2, 2]\n"
        "  STORE_PICKUP: [2, 2]\n"
        "delivered_rate: 1.0\n"
        "in_transit_rate: 0.0\n"
        "shipped_rate: 0.0\n"
        "shipment_number_prefix: PKG\n"
        "tracking_number_prefix: TN\n",
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
    shipments = pl.read_parquet(tmp_path / "custom" / "shipments.parquet")
    history = pl.read_parquet(tmp_path / "custom" / "shipment_status_history.parquet")

    assert shipments["carrier"].unique().to_list() == ["Royal Mail"]
    assert all(number.startswith("PKG-") for number in shipments["shipment_number"].to_list())
    assert all(number.startswith("TN-") for number in shipments["tracking_number"].to_list())
    assert set(shipments["current_status"].to_list()) == {"DELIVERED"}
    assert history.height == shipments.height * 5


def test_full_pipeline_produces_every_dataset(runner: CliRunner, warehouse: Path) -> None:
    """Running all four commands leaves thirty-nine datasets on disk.

    Fourteen from F001, four from F002, six from the journey command, and
    fifteen from the commerce command, which produces the F004 through F010
    datasets.
    """
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert len(list(warehouse.glob("*.parquet"))) == 39
