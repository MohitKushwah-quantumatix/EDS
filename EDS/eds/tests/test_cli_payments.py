"""Tests for the payment datasets produced by ``eds generate commerce``.

F007 introduces no new command: the existing commerce command now writes the
two payment datasets alongside the carts, cart items, checkouts, and orders.
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

PAYMENT_OUTPUTS = ("payments", "payment_status_history")


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
    """Payments are produced by the existing commerce command."""
    listing = runner.invoke(app, ["generate", "--help"])
    assert listing.exit_code == 0
    assert "commerce" in listing.output

    assert runner.invoke(app, ["generate", "payments", "--help"]).exit_code != 0


def test_commerce_writes_the_payment_datasets(runner: CliRunner, warehouse: Path) -> None:
    """The command now produces the F007 outputs alongside the earlier ones."""
    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert result.exit_code == 0, result.output
    for name in PAYMENT_OUTPUTS:
        assert (warehouse / f"{name}.parquet").is_file(), name


def test_report_lists_the_payment_datasets(runner: CliRunner, warehouse: Path) -> None:
    """The summary covers the payment datasets and validation passes."""
    result = runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert "payments" in result.output
    assert "payment_status_history" in result.output
    assert "Validation passed." in result.output


def test_written_payments_come_from_payable_orders(runner: CliRunner, warehouse: Path) -> None:
    """The files on disk honour the one-payment-per-payable-order rule."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    payments = pl.read_parquet(warehouse / "payments.parquet")
    orders = pl.read_parquet(warehouse / "orders.parquet")

    payable = set(orders.filter(pl.col("total_amount") > 0.0)["order_id"].to_list())

    assert set(payments["order_id"].to_list()) == payable
    assert payments["order_id"].n_unique() == payments.height


def test_written_amounts_are_copied_from_the_order(runner: CliRunner, warehouse: Path) -> None:
    """ADR-007 holds in the exported files."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    payments = pl.read_parquet(warehouse / "payments.parquet")
    orders = pl.read_parquet(warehouse / "orders.parquet")
    joined = payments.join(orders, on="order_id", how="inner", suffix="_ord")

    assert joined.height == payments.height
    assert joined.filter(pl.col("payment_amount") != pl.col("total_amount")).height == 0


def test_written_methods_are_copied_from_the_checkout(runner: CliRunner, warehouse: Path) -> None:
    """The method the customer chose is the one that gets charged."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    payments = pl.read_parquet(warehouse / "payments.parquet")
    orders = pl.read_parquet(warehouse / "orders.parquet")
    checkouts = pl.read_parquet(warehouse / "checkout.parquet")

    joined = payments.join(orders.select("order_id", "checkout_id"), on="order_id").join(
        checkouts.select("checkout_id", pl.col("payment_method").alias("chosen")),
        on="checkout_id",
    )

    assert joined.filter(pl.col("payment_method") != pl.col("chosen")).height == 0


def test_written_payment_references_are_well_formed(runner: CliRunner, warehouse: Path) -> None:
    """The business identifier survives the round trip."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    payments = pl.read_parquet(warehouse / "payments.parquet")
    pattern = re.compile(r"^PAY-\d{8}-\d{6}$")

    assert payments["payment_reference"].n_unique() == payments.height
    assert all(pattern.match(reference) for reference in payments["payment_reference"].to_list())


def test_written_payment_status_matches_the_history(runner: CliRunner, warehouse: Path) -> None:
    """The denormalised status agrees with the history on disk."""
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    payments = pl.read_parquet(warehouse / "payments.parquet")
    history = pl.read_parquet(warehouse / "payment_status_history.parquet")

    latest = (
        history.sort("payment_id", "sequence")
        .group_by("payment_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest"))
    )
    joined = payments.join(latest, on="payment_id", how="inner")

    assert joined.height == payments.height
    assert joined.filter(pl.col("payment_status") != pl.col("latest")).height == 0


def test_previous_datasets_are_not_regenerated(runner: CliRunner, warehouse: Path) -> None:
    """Running commerce leaves the journey and master files byte-identical."""
    before = {path.name: path.read_bytes() for path in sorted(warehouse.glob("*.parquet"))}

    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    for name, content in before.items():
        assert (warehouse / name).read_bytes() == content, name


def test_dry_run_writes_nothing(runner: CliRunner, warehouse: Path, tmp_path: Path) -> None:
    """A dry run validates the payments but writes none of them."""
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
    assert "payments" in result.output
    assert not destination.exists() or list(destination.glob("*.parquet")) == []


def test_generation_is_deterministic_across_invocations(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """Two runs with the same seed produce identical payment files."""
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

    for name in PAYMENT_OUTPUTS:
        left = pl.read_parquet(outputs[0] / f"{name}.parquet")
        right = pl.read_parquet(outputs[1] / f"{name}.parquet")
        assert left.equals(right), name


def test_configuration_is_carried_through_overrides(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """A command-line seed override does not reset the payment settings."""
    # Copy the whole shipped directory so this stays correct as later
    # features add configuration files, then override the one under test.
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    for source in Path("configs").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    for source in Path("configs/retail").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "payments.yaml").write_text(
        "currency: GBP\n"
        "capture_rate: 1.0\n"
        "void_rate: 0.0\n"
        "failure_rate: 0.0\n"
        "payment_reference_prefix: TXN\n",
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
    payments = pl.read_parquet(tmp_path / "custom" / "payments.parquet")
    history = pl.read_parquet(tmp_path / "custom" / "payment_status_history.parquet")

    assert payments["currency"].unique().to_list() == ["GBP"]
    assert all(
        reference.startswith("TXN-") for reference in payments["payment_reference"].to_list()
    )
    assert set(payments["payment_status"].to_list()) == {"CAPTURED"}
    assert history.height == payments.height * 2


def test_full_pipeline_produces_every_dataset(runner: CliRunner, warehouse: Path) -> None:
    """Running all four commands leaves thirty-nine datasets on disk.

    Fourteen from F001, four from F002, six from the journey command, and
    fifteen from the commerce command, which produces the F004 through F010
    datasets.
    """
    runner.invoke(app, ["generate", "commerce", "--output", str(warehouse), *SEED])

    assert len(list(warehouse.glob("*.parquet"))) == 39
