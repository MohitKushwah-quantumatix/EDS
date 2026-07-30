"""Tests for the order datasets produced by ``eds generate commerce``.

F006 introduces no new command: the existing commerce command now writes the
three order datasets alongside the carts, cart items, and checkouts.
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

COMMERCE_OUTPUTS = (
    "shopping_carts",
    "cart_items",
    "checkout",
    "orders",
    "order_lines",
    "order_status_history",
)


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
    """Orders are produced by the existing commerce command."""
    listing = runner.invoke(app, ["generate", "--help"])
    assert listing.exit_code == 0
    assert "commerce" in listing.output

    assert runner.invoke(app, ["generate", "orders", "--help"]).exit_code != 0


def test_commerce_writes_the_order_datasets(runner: CliRunner, warehouse: Path) -> None:
    """The command now produces the F004, F005 and F006 outputs together."""
    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert result.exit_code == 0, result.output
    for name in COMMERCE_OUTPUTS:
        assert (warehouse / f"{name}.parquet").is_file(), name


def test_report_lists_the_order_datasets(runner: CliRunner, warehouse: Path) -> None:
    """The summary covers the order datasets and validation passes."""
    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert "orders" in result.output
    assert "order_lines" in result.output
    assert "order_status_history" in result.output
    assert "Validation passed." in result.output


def test_written_orders_come_from_successful_checkouts(runner: CliRunner, warehouse: Path) -> None:
    """The files on disk honour the eligibility rule."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    orders = pl.read_parquet(warehouse / "orders.parquet")
    checkouts = pl.read_parquet(warehouse / "checkout.parquet")

    successful = set(
        checkouts.filter(pl.col("checkout_status") == "SUCCESS")["checkout_id"].to_list()
    )

    assert set(orders["checkout_id"].to_list()) == successful


def test_written_financials_are_copied_from_the_checkout(
    runner: CliRunner, warehouse: Path
) -> None:
    """ADR-007 holds in the exported files."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    orders = pl.read_parquet(warehouse / "orders.parquet")
    checkouts = pl.read_parquet(warehouse / "checkout.parquet")
    joined = orders.join(checkouts, on="checkout_id", how="inner", suffix="_ck")

    for column in ("subtotal", "shipping_cost", "tax_amount", "total_amount"):
        assert joined.filter(pl.col(column) != pl.col(f"{column}_ck")).height == 0, column


def test_written_lines_reconcile_with_their_orders(runner: CliRunner, warehouse: Path) -> None:
    """Money adds up in the exported files."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    orders = pl.read_parquet(warehouse / "orders.parquet")
    lines = pl.read_parquet(warehouse / "order_lines.parquet")

    summed = lines.group_by("order_id").agg(pl.col("line_total").sum().alias("total"))
    joined = orders.join(summed, on="order_id", how="left").with_columns(
        pl.col("total").fill_null(0.0)
    )

    assert joined.filter((pl.col("subtotal") - pl.col("total")).abs() > 0.011).height == 0


def test_written_order_numbers_are_well_formed(runner: CliRunner, warehouse: Path) -> None:
    """The business identifier survives the round trip."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    orders = pl.read_parquet(warehouse / "orders.parquet")
    pattern = re.compile(r"^ORD-\d{8}-\d{6}$")

    assert orders["order_number"].n_unique() == orders.height
    assert all(pattern.match(number) for number in orders["order_number"].to_list())


def test_written_current_status_matches_the_history(runner: CliRunner, warehouse: Path) -> None:
    """The denormalised status agrees with the history on disk."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    orders = pl.read_parquet(warehouse / "orders.parquet")
    history = pl.read_parquet(warehouse / "order_status_history.parquet")

    latest = (
        history.sort("order_id", "sequence")
        .group_by("order_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest"))
    )
    joined = orders.join(latest, on="order_id", how="inner")

    assert joined.height == orders.height
    assert joined.filter(pl.col("current_status") != pl.col("latest")).height == 0


def test_previous_datasets_are_not_regenerated(runner: CliRunner, warehouse: Path) -> None:
    """Running commerce leaves the journey and master files byte-identical."""
    before = {path.name: path.read_bytes() for path in sorted(warehouse.glob("*.parquet"))}

    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    for name, content in before.items():
        assert (warehouse / name).read_bytes() == content, name


def test_missing_products_exits_with_code_two(runner: CliRunner, warehouse: Path) -> None:
    """The command needs the F001 products dataset."""
    (warehouse / "products.parquet").unlink()

    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert result.exit_code == 2
    assert "products" in result.output


def test_dry_run_writes_nothing(runner: CliRunner, warehouse: Path, tmp_path: Path) -> None:
    """A dry run validates the commerce datasets but writes none."""
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
    assert "orders" in result.output
    assert not destination.exists() or list(destination.glob("*.parquet")) == []


def test_generation_is_deterministic_across_invocations(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """Two runs with the same seed produce identical order files."""
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

    for name in ("orders", "order_lines", "order_status_history"):
        left = pl.read_parquet(outputs[0] / f"{name}.parquet")
        right = pl.read_parquet(outputs[1] / f"{name}.parquet")
        assert left.equals(right), name


def test_configuration_is_carried_through_overrides(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """A command-line seed override does not reset the order settings."""
    # Copy the whole shipped directory so this stays correct as later
    # features add configuration files, then override the one under test.
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    for source in Path("configs").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "orders.yaml").write_text(
        "confirmed_rate: 1.0\nprocessing_rate: 1.0\norder_number_prefix: PO\n",
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
    orders = pl.read_parquet(tmp_path / "custom" / "orders.parquet")
    history = pl.read_parquet(tmp_path / "custom" / "order_status_history.parquet")

    assert all(number.startswith("PO-") for number in orders["order_number"].to_list())
    assert set(orders["current_status"].to_list()) == {"PROCESSING"}
    assert history.height == orders.height * 3


def test_full_pipeline_produces_every_dataset(runner: CliRunner, warehouse: Path) -> None:
    """Running all four commands leaves thirty-nine datasets on disk.

    Fourteen from F001, four from F002, six from the journey command, and
    fifteen from the commerce command, which produces the F004 through F010
    datasets.
    """
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert len(list(warehouse.glob("*.parquet"))) == 39
