"""Tests for the checkout dataset produced by ``eds generate commerce``.

F005 introduces no new command: the existing commerce command now writes the
checkout dataset alongside the carts and cart items.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from eds.cli.main import app

SEED = ["--seed", "36"]
SMALL_MASTER = ["--products", "40", "--warehouses", "3", "--suppliers", "3"]
SMALL_CUSTOMERS = ["--customers", "60"]

COMMERCE_OUTPUTS = ("shopping_carts", "cart_items", "checkout")


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
    """Checkout is produced by the existing commerce command."""
    listing = runner.invoke(app, ["generate", "--help"])
    assert listing.exit_code == 0
    assert "commerce" in listing.output

    assert runner.invoke(app, ["generate", "checkout", "--help"]).exit_code != 0


def test_commerce_writes_all_three_datasets(runner: CliRunner, warehouse: Path) -> None:
    """The command now produces the F004 and F005 outputs together."""
    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert result.exit_code == 0, result.output
    for name in COMMERCE_OUTPUTS:
        assert (warehouse / f"{name}.parquet").is_file(), name


def test_report_lists_the_checkout_dataset(runner: CliRunner, warehouse: Path) -> None:
    """The summary covers all three datasets and validation passes."""
    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert "checkout" in result.output
    # The command also produces every later commerce feature's datasets. The
    # total is asserted by the pipeline test rather than here, so adding a
    # feature does not break this one.
    assert "Validation passed." in result.output


def test_written_checkouts_reference_written_carts(runner: CliRunner, warehouse: Path) -> None:
    """The files on disk are referentially consistent."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    checkouts = pl.read_parquet(warehouse / "checkout.parquet")
    carts = pl.read_parquet(warehouse / "shopping_carts.parquet")
    addresses = pl.read_parquet(warehouse / "customer_addresses.parquet")

    eligible = set(carts.filter(pl.col("cart_status") == "CHECKED_OUT")["cart_id"].to_list())

    assert set(checkouts["cart_id"].to_list()) == eligible
    assert set(checkouts["shipping_address_id"].to_list()) <= set(addresses["address_id"].to_list())


def test_written_totals_reconcile(runner: CliRunner, warehouse: Path) -> None:
    """Money adds up in the exported files."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    checkouts = pl.read_parquet(warehouse / "checkout.parquet")
    items = pl.read_parquet(warehouse / "cart_items.parquet")

    # Items removed before checkout are not paid for.
    expected = (
        items.filter(pl.col("removed_at").is_null())
        .with_columns((pl.col("quantity") * pl.col("unit_price")).alias("line"))
        .group_by("cart_id")
        .agg(pl.col("line").sum().alias("expected"))
    )
    joined = checkouts.join(expected, on="cart_id", how="left").with_columns(
        pl.col("expected").fill_null(0.0)
    )

    assert joined.filter((pl.col("subtotal") - pl.col("expected")).abs() > 0.011).height == 0
    assert (
        checkouts.filter(
            (
                pl.col("total_amount")
                - (
                    pl.col("subtotal")
                    + pl.col("shipping_cost")
                    + pl.col("tax_amount")
                    - pl.col("discount_amount")
                )
            ).abs()
            > 0.011
        ).height
        == 0
    )


def test_previous_datasets_are_not_regenerated(runner: CliRunner, warehouse: Path) -> None:
    """Running commerce leaves the journey and master files byte-identical."""
    before = {path.name: path.read_bytes() for path in sorted(warehouse.glob("*.parquet"))}

    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    for name, content in before.items():
        assert (warehouse / name).read_bytes() == content, name


def test_missing_addresses_exits_with_code_two(runner: CliRunner, warehouse: Path) -> None:
    """The command needs the F002 customer addresses dataset."""
    (warehouse / "customer_addresses.parquet").unlink()

    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert result.exit_code == 2
    assert "customer_addresses" in result.output


def test_dry_run_writes_nothing(runner: CliRunner, warehouse: Path, tmp_path: Path) -> None:
    """A dry run validates all three datasets but writes none."""
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
    assert "checkout" in result.output
    assert not destination.exists() or list(destination.glob("*.parquet")) == []


def test_generation_is_deterministic_across_invocations(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """Two runs with the same seed produce identical checkout files."""
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

    left = pl.read_parquet(outputs[0] / "checkout.parquet")
    right = pl.read_parquet(outputs[1] / "checkout.parquet")

    assert left.equals(right)


def test_configuration_is_carried_through_overrides(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """A command-line seed override does not reset the checkout settings."""
    # Copy the whole shipped directory so this stays correct as later
    # features add configuration files, then override the one under test.
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    for source in Path("configs").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    for source in Path("configs/retail").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "checkout.yaml").write_text(
        "min_tax_rate: 0.10\nmax_tax_rate: 0.10\nsame_address_rate: 1.0\n",
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
            str(tmp_path / "fixed"),
            *SEED,
        ],
    )

    assert result.exit_code == 0, result.output
    checkouts = pl.read_parquet(tmp_path / "fixed" / "checkout.parquet")

    assert (
        checkouts.filter(pl.col("shipping_address_id") != pl.col("billing_address_id")).height == 0
    )
    priced = checkouts.filter(pl.col("subtotal") > 0)
    rates = [
        tax / subtotal
        for tax, subtotal in zip(
            priced["tax_amount"].to_list(), priced["subtotal"].to_list(), strict=True
        )
    ]
    assert max(rates) - min(rates) < 0.01
