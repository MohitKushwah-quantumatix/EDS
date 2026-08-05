"""Tests for the return datasets produced by ``eds generate commerce``.

F009 introduces no new command: the existing commerce command now writes the
three return datasets alongside everything F004 to F008 produce.
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

RETURN_OUTPUTS = ("returns", "return_items", "return_status_history")


@pytest.fixture
def runner() -> CliRunner:
    """Return a Typer CLI runner."""
    return CliRunner()


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Return a config directory whose return rate suits a small fixture.

    The shipped 12 per cent would leave a handful of returns at CLI-test scale,
    which is too few to assert anything useful about.
    """
    destination = tmp_path / "configs"
    destination.mkdir()
    for source in Path("configs").glob("*.yaml"):
        (destination / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    returns = destination / "returns.yaml"
    returns.write_text(
        returns.read_text(encoding="utf-8").replace("return_rate: 0.12", "return_rate: 0.8"),
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
    """Returns are produced by the existing commerce command."""
    listing = runner.invoke(app, ["generate", "--help"])
    assert listing.exit_code == 0
    assert "commerce" in listing.output

    assert runner.invoke(app, ["generate", "returns", "--help"]).exit_code != 0


def test_master_data_writes_the_return_reasons(warehouse: Path) -> None:
    """F009 reads its reason vocabulary from an F001 master file."""
    reasons = pl.read_parquet(warehouse / "return_reasons.parquet")

    assert reasons.height == 5
    assert set(reasons["reason_code"].to_list()) == {
        "DAMAGED",
        "WRONG_ITEM",
        "DEFECTIVE",
        "CHANGED_MIND",
        "LATE_DELIVERY",
    }


def test_commerce_writes_the_return_datasets(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """The command now produces the F009 outputs alongside the earlier ones."""
    _run(runner, warehouse, config_dir)

    for name in RETURN_OUTPUTS:
        assert (warehouse / f"{name}.parquet").is_file(), name


def test_report_lists_the_return_datasets(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """The summary covers the return datasets and validation passes."""
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

    for name in RETURN_OUTPUTS:
        assert name in result.output, name
    assert "Validation passed." in result.output


def test_written_returns_come_from_delivered_shipments(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """The files on disk honour the eligibility rule."""
    _run(runner, warehouse, config_dir)

    returns = pl.read_parquet(warehouse / "returns.parquet")
    shipments = pl.read_parquet(warehouse / "shipments.parquet")

    delivered = set(
        shipments.filter(pl.col("current_status") == "DELIVERED")["shipment_id"].to_list()
    )

    assert returns.height > 0
    assert set(returns["shipment_id"].to_list()) <= delivered
    assert returns["shipment_id"].n_unique() == returns.height


def test_written_reasons_come_from_master_data(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """The reason vocabulary is read, never invented."""
    _run(runner, warehouse, config_dir)

    returns = pl.read_parquet(warehouse / "returns.parquet")
    reasons = pl.read_parquet(warehouse / "return_reasons.parquet")

    assert set(returns["return_reason"].to_list()) <= set(reasons["reason_code"].to_list())


def test_written_refund_types_come_from_configuration(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """Settlement is configuration driven."""
    _run(runner, warehouse, config_dir)

    returns = pl.read_parquet(warehouse / "returns.parquet")

    assert set(returns["refund_type"].to_list()) <= {
        "FULL_REFUND",
        "STORE_CREDIT",
        "REPLACEMENT",
    }


def test_written_return_numbers_are_well_formed(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """The business identifier survives the round trip."""
    _run(runner, warehouse, config_dir)

    returns = pl.read_parquet(warehouse / "returns.parquet")
    pattern = re.compile(r"^RET-\d{8}-\d{6}$")

    assert returns["return_number"].n_unique() == returns.height
    assert all(pattern.match(number) for number in returns["return_number"].to_list())


def test_written_items_preserve_their_lineage(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """Order line, product and quantity match the shipment item on disk."""
    _run(runner, warehouse, config_dir)

    items = pl.read_parquet(warehouse / "return_items.parquet")
    shipment_items = pl.read_parquet(warehouse / "shipment_items.parquet")
    joined = items.join(shipment_items, on="shipment_item_id", how="inner", suffix="_ship")

    assert joined.height == items.height
    for column in ("order_line_id", "product_id", "quantity"):
        assert joined.filter(pl.col(column) != pl.col(f"{column}_ship")).height == 0, column


def test_written_current_status_matches_the_history(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """The denormalised status agrees with the history on disk."""
    _run(runner, warehouse, config_dir)

    returns = pl.read_parquet(warehouse / "returns.parquet")
    history = pl.read_parquet(warehouse / "return_status_history.parquet")

    latest = (
        history.sort("return_id", "sequence")
        .group_by("return_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest"))
    )
    joined = returns.join(latest, on="return_id", how="inner")

    assert joined.height == returns.height
    assert joined.filter(pl.col("current_status") != pl.col("latest")).height == 0


def test_written_timeline_is_chronological(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """Delivery, request, approval and completion run in order on disk."""
    _run(runner, warehouse, config_dir)

    returns = pl.read_parquet(warehouse / "returns.parquet")
    shipments = pl.read_parquet(warehouse / "shipments.parquet")

    joined = returns.join(
        shipments.select("shipment_id", pl.col("delivered_at").alias("arrived_at")),
        on="shipment_id",
    )

    assert joined.filter(pl.col("requested_at") < pl.col("arrived_at")).height == 0
    assert returns.filter(pl.col("approved_at") <= pl.col("requested_at")).height == 0
    completed = returns.filter(pl.col("completed_at").is_not_null())
    assert completed.filter(pl.col("completed_at") <= pl.col("received_at")).height == 0


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
    """A dry run validates the returns but writes none of them."""
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
    assert "returns" in result.output
    assert not destination.exists() or list(destination.glob("*.parquet")) == []


def test_generation_is_deterministic_across_invocations(
    runner: CliRunner, warehouse: Path, config_dir: Path, tmp_path: Path
) -> None:
    """Two runs with the same seed produce identical return files."""
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

    for name in RETURN_OUTPUTS:
        left = pl.read_parquet(outputs[0] / f"{name}.parquet")
        right = pl.read_parquet(outputs[1] / f"{name}.parquet")
        assert left.equals(right), name


def test_configuration_is_carried_through_overrides(
    runner: CliRunner, warehouse: Path, tmp_path: Path
) -> None:
    """A command-line seed override does not reset the return settings."""
    # Copy the whole shipped directory so this stays correct as later
    # features add configuration files, then override the one under test.
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    for source in Path("configs").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    for source in Path("configs/retail").glob("*.yaml"):
        (config_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "returns.yaml").write_text(
        "return_rate: 1.0\n"
        "refund_types:\n"
        "  STORE_CREDIT: 1.0\n"
        "completed_rate: 1.0\n"
        "received_rate: 0.0\n"
        "in_transit_rate: 0.0\n"
        "approved_rate: 0.0\n"
        "return_number_prefix: RMA\n",
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
    returns = pl.read_parquet(tmp_path / "custom" / "returns.parquet")
    history = pl.read_parquet(tmp_path / "custom" / "return_status_history.parquet")

    assert returns["refund_type"].unique().to_list() == ["STORE_CREDIT"]
    assert all(number.startswith("RMA-") for number in returns["return_number"].to_list())
    assert set(returns["current_status"].to_list()) == {"COMPLETED"}
    assert history.height == returns.height * 5


def test_full_pipeline_produces_every_dataset(
    runner: CliRunner, warehouse: Path, config_dir: Path
) -> None:
    """Running all four commands leaves thirty-nine datasets on disk.

    Fourteen from F001, four from F002, six from the journey command, and
    fifteen from the commerce command, which produces the F004 through F010
    datasets.
    """
    _run(runner, warehouse, config_dir)

    assert len(list(warehouse.glob("*.parquet"))) == 39
