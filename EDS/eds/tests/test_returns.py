"""Tests for the return generator, return items, and status history."""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import pytest

from eds.config import (
    DEFAULT_REFUND_TYPES,
    ConfigError,
    PlatformConfig,
    ReturnConfig,
    SimulationConfig,
    load_config,
    load_return_config,
)
from eds.domain.commerce.enums import RETURN_LIFECYCLE, ReturnStatus, ShipmentStatus
from eds.domain.commerce.schema import (
    RETURN_DATASETS,
    SHIPMENT_DATASETS,
    return_dataset_by_name,
    return_dataset_names,
)
from eds.domain.commercial.schema import RETURN_REASONS
from eds.generators.commerce.return_generator import (
    apply_status_and_timeline,
    eligible_shipments,
    generate_returns,
    iter_return_batches,
)
from eds.generators.commerce.return_item_generator import generate_return_items
from eds.generators.commerce.return_status_generator import (
    generate_return_status_history,
    return_lifecycle_position,
)
from eds.generators.commerce.returns import (
    REQUIRED_RETURN_DATASETS,
    ReturnData,
    generate_return_data,
)
from eds.generators.commercial.generator import generate_return_reasons
from eds.validation.return_validation import RETURN_NUMBER_PATTERN, validate_return_data

SEED = 4242

#: How many times the shipment fixture is repeated to measure outcome shares.
REPLICATION_FACTOR = 40

EXPECTED_OUTPUTS = {"returns", "return_items", "return_status_history"}


@pytest.fixture
def config() -> ReturnConfig:
    """Return a return configuration with a small batch size."""
    return ReturnConfig(return_rate=0.60, batch_size=25)


@pytest.fixture
def returns(return_data: ReturnData) -> pl.DataFrame:
    """Return the generated returns frame."""
    return return_data["returns"]


@pytest.fixture
def items(return_data: ReturnData) -> pl.DataFrame:
    """Return the generated return items frame."""
    return return_data["return_items"]


@pytest.fixture
def history(return_data: ReturnData) -> pl.DataFrame:
    """Return the generated return status history frame."""
    return return_data["return_status_history"]


@pytest.fixture
def shipments(return_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the shipments frame."""
    return return_upstream["shipments"]


@pytest.fixture
def shipment_items(return_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the shipment items frame."""
    return return_upstream["shipment_items"]


@pytest.fixture
def return_reasons(return_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the F001 return reasons master frame."""
    return return_upstream["return_reasons"]


@pytest.fixture
def many_shipments(shipments: pl.DataFrame) -> pl.DataFrame:
    """Return the shipments repeated enough times to measure a distribution.

    The test fixture carries a few dozen delivered shipments, far too few to
    distinguish a 2 per cent outcome from a 5 per cent one. Repeating them
    under fresh identifiers keeps every other property intact while giving the
    completion shares a sample they can actually be read from.
    """
    copies = [
        shipments.with_columns(
            (pl.col("shipment_id") + index * shipments.height).alias("shipment_id")
        )
        for index in range(REPLICATION_FACTOR)
    ]
    return pl.concat(copies, how="vertical")


@pytest.fixture
def many_shipment_items(shipment_items: pl.DataFrame, shipments: pl.DataFrame) -> pl.DataFrame:
    """Return shipment items aligned with :func:`many_shipments`."""
    copies = [
        shipment_items.with_columns(
            (pl.col("shipment_id") + index * shipments.height).alias("shipment_id"),
            (pl.col("shipment_item_id") + index * shipment_items.height).alias("shipment_item_id"),
        )
        for index in range(REPLICATION_FACTOR)
    ]
    return pl.concat(copies, how="vertical")


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_shipped_return_config_loads() -> None:
    """The committed returns.yaml matches the documented defaults."""
    config = load_return_config()

    assert config.return_rate == pytest.approx(0.12)
    assert config.completed_rate == pytest.approx(0.85)
    assert config.received_rate == pytest.approx(0.08)
    assert config.in_transit_rate == pytest.approx(0.05)
    assert config.approved_rate == pytest.approx(0.02)
    assert config.return_number_prefix == "RET"


def test_return_config_is_part_of_the_run_configuration() -> None:
    """`load_config` includes the returns section."""
    assert load_config().returns.return_rate == pytest.approx(0.12)


def test_shipped_config_offers_the_documented_refund_types() -> None:
    """The suggested settlement types are what the generator draws from."""
    refund_types = load_return_config().refund_types

    assert set(refund_types) == {"FULL_REFUND", "STORE_CREDIT", "REPLACEMENT"}
    assert refund_types["FULL_REFUND"] == pytest.approx(0.70)


def test_the_configuration_holds_no_return_reasons() -> None:
    """Reasons are master data, so they must not leak into configuration."""
    assert not any("reason" in field for field in ReturnConfig.model_fields)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("return_rate", 1.5),
        ("completed_rate", -0.1),
        ("min_approval_hours", 0),
        ("min_request_days", -1),
        ("batch_size", 0),
    ],
)
def test_out_of_range_return_values_are_rejected(field: str, value: float) -> None:
    """Settings outside their declared bounds fail validation."""
    with pytest.raises(ValueError, match=field):
        ReturnConfig(**{field: value})  # type: ignore[arg-type]


def test_lifecycle_shares_must_total_one() -> None:
    """The four outcomes partition every return, so they sum to 1.0."""
    with pytest.raises(ValueError, match="must sum to 1.0"):
        ReturnConfig(completed_rate=0.5, received_rate=0.1, in_transit_rate=0.1, approved_rate=0.1)


def test_refund_shares_must_total_one() -> None:
    """Every return is settled exactly one way."""
    with pytest.raises(ValueError, match="must sum to 1.0"):
        ReturnConfig(refund_types={"FULL_REFUND": 0.5, "STORE_CREDIT": 0.2})


def test_an_empty_refund_table_is_rejected() -> None:
    """A return with no way to settle is a configuration error."""
    with pytest.raises(ValueError, match="at least one settlement type"):
        ReturnConfig(refund_types={})


def test_a_negative_refund_share_is_rejected() -> None:
    """A share below zero is meaningless."""
    with pytest.raises(ValueError, match="cannot be negative"):
        ReturnConfig(refund_types={"FULL_REFUND": 1.5, "STORE_CREDIT": -0.5})


@pytest.mark.parametrize(
    ("low_field", "high_field"),
    [
        ("min_request_days", "max_request_days"),
        ("min_approval_hours", "max_approval_hours"),
        ("min_dispatch_hours", "max_dispatch_hours"),
        ("min_transit_hours", "max_transit_hours"),
        ("min_completion_hours", "max_completion_hours"),
    ],
)
def test_inverted_wait_ranges_are_rejected(low_field: str, high_field: str) -> None:
    """A minimum above its maximum is a configuration error."""
    with pytest.raises(ValueError, match="cannot exceed"):
        ReturnConfig(**{low_field: 500, high_field: 1})  # type: ignore[arg-type]


def test_unknown_return_key_is_rejected() -> None:
    """A misspelled key is an error, not a silent no-op."""
    with pytest.raises(ValueError, match="returns_rate"):
        ReturnConfig(returns_rate=0.9)  # type: ignore[call-arg]


def test_invalid_return_config_file_raises(tmp_path: Path) -> None:
    """An out-of-range value names the offending file."""
    (tmp_path / "returns.yaml").write_text("return_rate: 5.0\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="returns.yaml"):
        load_return_config(tmp_path)


# --------------------------------------------------------------------------
# Return reasons master data
# --------------------------------------------------------------------------


def test_return_reasons_are_master_data() -> None:
    """F001 owns the reason vocabulary; F009 only reads it."""
    reasons = generate_return_reasons()

    assert reasons.height == 5
    assert set(reasons["reason_code"].to_list()) == {
        "DAMAGED",
        "WRONG_ITEM",
        "DEFECTIVE",
        "CHANGED_MIND",
        "LATE_DELIVERY",
    }
    assert reasons["reason_code"].n_unique() == reasons.height
    assert RETURN_REASONS.file_name == "return_reasons.parquet"


def test_return_reasons_classify_fault_and_inspection() -> None:
    """A returns analyst groups by who caused it and what needs checking."""
    reasons = generate_return_reasons()
    fault = dict(zip(reasons["reason_code"], reasons["is_customer_fault"], strict=True))
    inspection = dict(zip(reasons["reason_code"], reasons["requires_inspection"], strict=True))

    assert fault["CHANGED_MIND"] is True
    assert fault["DAMAGED"] is False
    assert inspection["DAMAGED"] is True
    assert inspection["CHANGED_MIND"] is False


def test_reasons_are_read_from_master_data_not_hardcoded(
    config: ReturnConfig, shipments: pl.DataFrame, shipment_items: pl.DataFrame
) -> None:
    """A different master table yields different reasons in the data."""
    custom = pl.DataFrame(
        {
            "return_reason_id": [1],
            "reason_code": ["MISSING_PARTS"],
            "reason_name": ["Missing Parts"],
            "is_customer_fault": [False],
            "requires_inspection": [True],
            "is_active": [True],
        },
        schema=RETURN_REASONS.polars_schema(),
    )

    generated = generate_returns(config, shipments, shipment_items, custom, SEED)

    assert generated["return_reason"].unique().to_list() == ["MISSING_PARTS"]


def test_an_inactive_reason_is_never_chosen(
    config: ReturnConfig, shipments: pl.DataFrame, shipment_items: pl.DataFrame
) -> None:
    """A retired reason stays out of new returns."""
    reasons = generate_return_reasons().with_columns(
        pl.when(pl.col("reason_code") == "DAMAGED")
        .then(pl.lit(True))
        .otherwise(pl.lit(False))
        .alias("is_active")
    )

    generated = generate_returns(config, shipments, shipment_items, reasons, SEED)

    assert generated["return_reason"].unique().to_list() == ["DAMAGED"]


def test_master_data_with_no_active_reason_is_reported(
    config: ReturnConfig, shipments: pl.DataFrame, shipment_items: pl.DataFrame
) -> None:
    """F009 reads the vocabulary and does not substitute a default."""
    reasons = generate_return_reasons().with_columns(pl.lit(False).alias("is_active"))

    with pytest.raises(ValueError, match="no active reason"):
        generate_returns(config, shipments, shipment_items, reasons, SEED)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_registry_lists_the_three_documented_outputs() -> None:
    """F009 declares exactly three output datasets."""
    assert len(RETURN_DATASETS) == 3
    assert set(return_dataset_names()) == EXPECTED_OUTPUTS


def test_earlier_registries_are_unchanged() -> None:
    """Adding returns did not disturb the F008 registry."""
    assert {dataset.name for dataset in SHIPMENT_DATASETS} == {
        "shipments",
        "shipment_items",
        "shipment_status_history",
    }


def test_dataset_file_names_match_the_specification() -> None:
    """Each dataset maps to the documented Parquet file name."""
    assert return_dataset_by_name("returns").file_name == "returns.parquet"
    assert return_dataset_by_name("return_items").file_name == "return_items.parquet"
    assert (
        return_dataset_by_name("return_status_history").file_name == "return_status_history.parquet"
    )


def test_unknown_return_dataset_lookup_raises() -> None:
    """Looking up an unregistered dataset fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown return dataset"):
        return_dataset_by_name("reviews")


def test_only_the_five_documented_stages_exist() -> None:
    """REJECTED, CANCELLED and REFUNDED belong to later features."""
    assert [str(member) for member in RETURN_LIFECYCLE] == [
        "REQUESTED",
        "APPROVED",
        "IN_TRANSIT",
        "RECEIVED",
        "COMPLETED",
    ]
    assert {str(member) for member in ReturnStatus} == {str(member) for member in RETURN_LIFECYCLE}


def test_lifecycle_position_orders_the_stages() -> None:
    """Positions ascend along the lifecycle."""
    assert return_lifecycle_position("REQUESTED") == 1
    assert return_lifecycle_position("APPROVED") == 2
    assert return_lifecycle_position("IN_TRANSIT") == 3
    assert return_lifecycle_position("RECEIVED") == 4
    assert return_lifecycle_position("COMPLETED") == 5


def test_unknown_lifecycle_status_raises() -> None:
    """A stage from a future feature is not silently accepted."""
    with pytest.raises(KeyError, match="Lifecycle"):
        return_lifecycle_position("REFUNDED")


# --------------------------------------------------------------------------
# Returns
# --------------------------------------------------------------------------


def test_returns_come_only_from_delivered_shipments(
    returns: pl.DataFrame, shipments: pl.DataFrame
) -> None:
    """A parcel still travelling has not arrived, so nothing can come back."""
    delivered = set(
        shipments.filter(pl.col("current_status") == str(ShipmentStatus.DELIVERED))[
            "shipment_id"
        ].to_list()
    )

    assert set(returns["shipment_id"].to_list()) <= delivered


def test_undelivered_shipments_produce_no_return(
    returns: pl.DataFrame, shipments: pl.DataFrame
) -> None:
    """Only delivery makes a shipment eligible."""
    undelivered = set(
        shipments.filter(pl.col("current_status") != str(ShipmentStatus.DELIVERED))[
            "shipment_id"
        ].to_list()
    )

    assert not (set(returns["shipment_id"].to_list()) & undelivered)
    assert undelivered, "the sample should contain undelivered shipments"


def test_a_delivered_shipment_with_no_items_is_not_eligible(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame
) -> None:
    """Returns originate from delivered shipment items, so items are required."""
    eligible = eligible_shipments(shipments, shipment_items)
    with_items = set(shipment_items["shipment_id"].to_list())

    assert set(eligible["shipment_id"].to_list()) <= with_items


def test_at_most_one_return_per_shipment(returns: pl.DataFrame) -> None:
    """A shipment is sent back once, not repeatedly."""
    assert returns["shipment_id"].n_unique() == returns.height


def test_return_ids_are_unique_and_sequential(returns: pl.DataFrame) -> None:
    """Return ids form a dense sequence starting at one."""
    assert returns["return_id"].to_list() == list(range(1, returns.height + 1))


def test_customer_comes_from_the_shipment(returns: pl.DataFrame, shipments: pl.DataFrame) -> None:
    """ADR-008: the shipment is the return's single parent."""
    joined = returns.join(shipments, on="shipment_id", how="inner", suffix="_shp")

    assert joined.height == returns.height
    assert joined.filter(pl.col("customer_id") != pl.col("customer_id_shp")).height == 0


def test_refund_type_is_one_the_configuration_offers(returns: pl.DataFrame) -> None:
    """Settlement is configuration driven."""
    assert set(returns["refund_type"].to_list()) <= set(DEFAULT_REFUND_TYPES)


def test_configured_refund_types_reach_the_data(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_reasons: pl.DataFrame
) -> None:
    """Changing the configuration changes how returns are settled."""
    settings = ReturnConfig(return_rate=0.60, refund_types={"GIFT_CARD": 1.0})

    generated = generate_returns(settings, shipments, shipment_items, return_reasons, SEED)

    assert generated["refund_type"].unique().to_list() == ["GIFT_CARD"]


def test_the_return_rate_is_configurable(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_reasons: pl.DataFrame
) -> None:
    """A rate of zero returns nothing; a rate of one returns everything."""
    eligible = eligible_shipments(shipments, shipment_items).height

    none = generate_returns(
        ReturnConfig(return_rate=0.0), shipments, shipment_items, return_reasons, SEED
    )
    every = generate_returns(
        ReturnConfig(return_rate=1.0), shipments, shipment_items, return_reasons, SEED
    )

    assert none.height == 0
    assert every.height == eligible


def test_the_return_rate_is_approximately_honoured(
    many_shipments: pl.DataFrame,
    many_shipment_items: pl.DataFrame,
    return_reasons: pl.DataFrame,
) -> None:
    """Roughly the configured share of eligible shipments comes back."""
    settings = ReturnConfig(return_rate=0.12)
    eligible = eligible_shipments(many_shipments, many_shipment_items).height

    generated = generate_returns(
        settings, many_shipments, many_shipment_items, return_reasons, SEED
    )

    assert eligible >= 500, "the replicated sample should be large enough to read"
    assert generated.height / eligible == pytest.approx(0.12, abs=0.03)


# --------------------------------------------------------------------------
# Return numbers
# --------------------------------------------------------------------------


def test_return_numbers_are_unique(returns: pl.DataFrame) -> None:
    """The business identifier is never reused."""
    assert returns["return_number"].n_unique() == returns.height


def test_return_numbers_match_the_documented_format(returns: pl.DataFrame) -> None:
    """Every number reads as PREFIX-YYYYMMDD-NNNNNN."""
    pattern = re.compile(RETURN_NUMBER_PATTERN)

    for number in returns["return_number"].to_list():
        assert pattern.match(number), number


def test_return_number_embeds_its_own_date(returns: pl.DataFrame) -> None:
    """The date inside the number is the day the return was requested."""
    mismatched = returns.filter(
        pl.col("return_number").str.slice(-15, 8) != pl.col("requested_at").dt.strftime("%Y%m%d")
    )

    assert mismatched.height == 0


def test_return_numbers_are_sequential_within_a_date(returns: pl.DataFrame) -> None:
    """The sequence restarts each day and runs 1..n without gaps."""
    numbered = (
        returns.with_columns(pl.col("requested_at").dt.date().alias("day"))
        .group_by("day")
        .agg(
            pl.col("return_number").str.slice(-6).cast(pl.Int64).min().alias("lowest"),
            pl.col("return_number").str.slice(-6).cast(pl.Int64).max().alias("highest"),
            pl.len().alias("total"),
        )
    )

    assert numbered.filter(pl.col("lowest") != 1).height == 0
    assert numbered.filter(pl.col("highest") != pl.col("total")).height == 0


def test_the_prefix_is_configurable(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_reasons: pl.DataFrame
) -> None:
    """A different prefix changes every number."""
    settings = ReturnConfig(return_rate=0.60, return_number_prefix="RMA")

    custom = generate_returns(settings, shipments, shipment_items, return_reasons, SEED)

    assert all(number.startswith("RMA-") for number in custom["return_number"].to_list())


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


def test_returns_are_requested_after_delivery(
    returns: pl.DataFrame, shipments: pl.DataFrame
) -> None:
    """requested_at must be after shipment.delivered_at."""
    joined = returns.join(
        shipments.select("shipment_id", pl.col("delivered_at").alias("arrived_at")),
        on="shipment_id",
    )

    assert joined.filter(pl.col("requested_at") < pl.col("arrived_at")).height == 0


def test_request_delays_stay_inside_the_configured_window(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_reasons: pl.DataFrame
) -> None:
    """Every request falls in the configured day range after delivery."""
    settings = ReturnConfig(return_rate=1.0, min_request_days=3, max_request_days=5)

    generated = generate_returns(settings, shipments, shipment_items, return_reasons, SEED).join(
        shipments.select("shipment_id", "delivered_at"), on="shipment_id"
    )
    measured = generated.with_columns(
        (pl.col("requested_at") - pl.col("delivered_at")).dt.total_days().alias("days")
    )

    assert measured.height > 0
    assert measured.filter((pl.col("days") < 3) | (pl.col("days") > 5)).height == 0


def test_created_at_is_the_moment_of_request(returns: pl.DataFrame) -> None:
    """The document exists as soon as the customer asks."""
    assert returns.filter(pl.col("created_at") != pl.col("requested_at")).height == 0


def test_the_timeline_runs_forwards(returns: pl.DataFrame) -> None:
    """Request, approval, receipt and completion happen in order."""
    for earlier, later in (
        ("requested_at", "approved_at"),
        ("approved_at", "received_at"),
        ("received_at", "completed_at"),
    ):
        offending = returns.filter(pl.col(later).is_not_null() & (pl.col(later) <= pl.col(earlier)))
        assert offending.height == 0, f"{later} must follow {earlier}"


def test_timestamps_are_populated_only_once_reached(returns: pl.DataFrame) -> None:
    """A return still in transit has not been received."""
    completed = returns.filter(pl.col("current_status") == str(ReturnStatus.COMPLETED))
    approved = returns.filter(pl.col("current_status") == str(ReturnStatus.APPROVED))

    assert completed["completed_at"].null_count() == 0
    assert completed["received_at"].null_count() == 0
    assert approved["completed_at"].null_count() == approved.height
    assert approved["received_at"].null_count() == approved.height
    assert returns["approved_at"].null_count() == 0


# --------------------------------------------------------------------------
# Return items
# --------------------------------------------------------------------------


def test_return_item_ids_are_unique_and_sequential(items: pl.DataFrame) -> None:
    """Item ids form a dense sequence starting at one."""
    assert items["return_item_id"].to_list() == list(range(1, items.height + 1))


def test_items_originate_only_from_shipment_items(
    items: pl.DataFrame, shipment_items: pl.DataFrame
) -> None:
    """Every returned item is a shipment item coming back."""
    assert set(items["shipment_item_id"].to_list()) <= set(
        shipment_items["shipment_item_id"].to_list()
    )


def test_items_belong_to_their_return_own_shipment(
    returns: pl.DataFrame, items: pl.DataFrame, shipment_items: pl.DataFrame
) -> None:
    """An item never comes back from somebody else's shipment."""
    joined = items.join(
        returns.select("return_id", pl.col("shipment_id").alias("return_shipment")),
        on="return_id",
    ).join(
        shipment_items.select("shipment_item_id", pl.col("shipment_id").alias("item_shipment")),
        on="shipment_item_id",
    )

    assert joined.height == items.height
    assert joined.filter(pl.col("return_shipment") != pl.col("item_shipment")).height == 0


def test_lineage_is_preserved_exactly(items: pl.DataFrame, shipment_items: pl.DataFrame) -> None:
    """Order line, product and quantity are carried across untouched."""
    joined = items.join(shipment_items, on="shipment_item_id", how="inner", suffix="_ship")

    for column in ("order_line_id", "product_id", "quantity"):
        assert joined.filter(pl.col(column) != pl.col(f"{column}_ship")).height == 0, column


def test_every_return_carries_at_least_one_item(returns: pl.DataFrame, items: pl.DataFrame) -> None:
    """A return of nothing is not a return."""
    assert set(items["return_id"].to_list()) == set(returns["return_id"].to_list())


def test_a_shipment_item_comes_back_at_most_once(items: pl.DataFrame) -> None:
    """Exchanges and partial-quantity returns are out of scope."""
    assert items["shipment_item_id"].n_unique() == items.height


def test_a_return_never_carries_more_than_its_shipment_sent(
    returns: pl.DataFrame, items: pl.DataFrame, shipment_items: pl.DataFrame
) -> None:
    """The customer cannot send back more than arrived."""
    shipped = shipment_items.group_by("shipment_id").len().rename({"len": "shipped"})
    returned = items.group_by("return_id").len().rename({"len": "returned"})
    joined = (
        returns.select("return_id", "shipment_id")
        .join(returned, on="return_id", how="inner")
        .join(shipped, on="shipment_id", how="inner")
    )

    assert joined.filter(pl.col("returned") > pl.col("shipped")).height == 0


def test_items_are_stamped_with_their_return(returns: pl.DataFrame, items: pl.DataFrame) -> None:
    """The item exists as soon as the return does."""
    joined = items.join(
        returns.select("return_id", pl.col("created_at").alias("requested")), on="return_id"
    )

    assert joined.filter(pl.col("created_at") != pl.col("requested")).height == 0


# --------------------------------------------------------------------------
# Status history
# --------------------------------------------------------------------------


def test_history_ids_are_unique_and_sequential(history: pl.DataFrame) -> None:
    """History ids form a dense sequence starting at one."""
    assert history["history_id"].to_list() == list(range(1, history.height + 1))


def test_every_return_has_a_requested_row(returns: pl.DataFrame, history: pl.DataFrame) -> None:
    """The lifecycle always begins at REQUESTED."""
    requested = history.filter(pl.col("status") == str(ReturnStatus.REQUESTED))

    assert requested.height == returns.height
    assert set(requested["sequence"].to_list()) == {1}


def test_every_return_reaches_approved(returns: pl.DataFrame, history: pl.DataFrame) -> None:
    """The first two stages are unconditional."""
    for status in (ReturnStatus.REQUESTED, ReturnStatus.APPROVED):
        assert history.filter(pl.col("status") == str(status)).height == returns.height, status


def test_sequences_start_at_one_and_are_contiguous(history: pl.DataFrame) -> None:
    """Numbering restarts per return without gaps."""
    grouped = history.group_by("return_id").agg(
        pl.col("sequence").min().alias("lowest"),
        pl.col("sequence").max().alias("highest"),
        pl.len().alias("total"),
    )

    assert grouped.filter(pl.col("lowest") != 1).height == 0
    assert grouped.filter(pl.col("highest") != pl.col("total")).height == 0


def test_history_is_chronological(history: pl.DataFrame) -> None:
    """Time moves forwards with the sequence."""
    ordered = history.sort("return_id", "sequence").with_columns(
        pl.col("status_timestamp").shift(1).over("return_id").alias("previous")
    )

    assert (
        ordered.filter(
            pl.col("previous").is_not_null() & (pl.col("status_timestamp") <= pl.col("previous"))
        ).height
        == 0
    )


def test_completion_implies_receipt(history: pl.DataFrame) -> None:
    """A return is only completed after the warehouse has it."""
    completed = set(
        history.filter(pl.col("status") == str(ReturnStatus.COMPLETED))["return_id"].to_list()
    )
    received = set(
        history.filter(pl.col("status") == str(ReturnStatus.RECEIVED))["return_id"].to_list()
    )

    assert completed <= received


def test_current_status_equals_the_latest_history_row(
    returns: pl.DataFrame, history: pl.DataFrame
) -> None:
    """ADR-012: the history is the source of truth."""
    latest = (
        history.sort("return_id", "sequence")
        .group_by("return_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest"))
    )
    joined = returns.join(latest, on="return_id", how="inner")

    assert joined.height == returns.height
    assert joined.filter(pl.col("current_status") != pl.col("latest")).height == 0


def test_timeline_columns_come_from_the_history(
    returns: pl.DataFrame, history: pl.DataFrame
) -> None:
    """The timestamps are denormalised, not maintained apart."""
    stamps = history.group_by("return_id").agg(
        *[
            pl.col("status_timestamp")
            .filter(pl.col("status") == str(status))
            .first()
            .alias(f"from_history_{column}")
            for status, column in (
                (ReturnStatus.APPROVED, "approved_at"),
                (ReturnStatus.RECEIVED, "received_at"),
                (ReturnStatus.COMPLETED, "completed_at"),
            )
        ]
    )
    joined = returns.join(stamps, on="return_id", how="inner")

    for column in ("approved_at", "received_at", "completed_at"):
        source = f"from_history_{column}"
        assert joined.filter(pl.col(column).is_null() != pl.col(source).is_null()).height == 0
        assert (
            joined.filter(pl.col(column).is_not_null() & (pl.col(column) != pl.col(source))).height
            == 0
        )


def test_no_future_lifecycle_stage_is_generated(history: pl.DataFrame) -> None:
    """REJECTED, CANCELLED and REFUNDED belong to later features."""
    assert set(history["status"].to_list()) <= {str(member) for member in RETURN_LIFECYCLE}


def test_completion_distribution_is_approximately_as_specified(
    many_shipments: pl.DataFrame,
    many_shipment_items: pl.DataFrame,
    return_reasons: pl.DataFrame,
) -> None:
    """Roughly 85 / 8 / 5 / 2 per cent complete, receive, travel or approve."""
    settings = ReturnConfig(return_rate=1.0)
    generated = generate_returns(
        settings, many_shipments, many_shipment_items, return_reasons, SEED
    )
    history = generate_return_status_history(settings, generated, SEED)
    settled = apply_status_and_timeline(generated, history)

    total = settled.height
    share = {
        row["current_status"]: row["count"] / total
        for row in settled["current_status"].value_counts().to_dicts()
    }

    assert total >= 500, "the replicated sample should be large enough to read"
    assert share[str(ReturnStatus.COMPLETED)] == pytest.approx(0.85, abs=0.04)
    assert share.get(str(ReturnStatus.RECEIVED), 0.0) == pytest.approx(0.08, abs=0.03)
    assert share.get(str(ReturnStatus.IN_TRANSIT), 0.0) == pytest.approx(0.05, abs=0.03)
    assert share.get(str(ReturnStatus.APPROVED), 0.0) == pytest.approx(0.02, abs=0.02)


def test_every_return_can_complete(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_reasons: pl.DataFrame
) -> None:
    """With a completed rate of one, every history runs the full five stages."""
    settings = ReturnConfig(
        return_rate=0.60,
        completed_rate=1.0,
        received_rate=0.0,
        in_transit_rate=0.0,
        approved_rate=0.0,
    )

    generated = generate_returns(settings, shipments, shipment_items, return_reasons, SEED)
    history = generate_return_status_history(settings, generated, SEED)
    settled = apply_status_and_timeline(generated, history)

    assert history.height == generated.height * 5
    assert set(settled["current_status"].to_list()) == {str(ReturnStatus.COMPLETED)}
    assert settled["completed_at"].null_count() == 0


def test_every_return_can_stop_at_approval(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_reasons: pl.DataFrame
) -> None:
    """With an approved rate of one, nothing has been sent back yet."""
    settings = ReturnConfig(
        return_rate=0.60,
        completed_rate=0.0,
        received_rate=0.0,
        in_transit_rate=0.0,
        approved_rate=1.0,
    )

    generated = generate_returns(settings, shipments, shipment_items, return_reasons, SEED)
    history = generate_return_status_history(settings, generated, SEED)
    settled = apply_status_and_timeline(generated, history)

    assert history.height == generated.height * 2
    assert set(settled["current_status"].to_list()) == {str(ReturnStatus.APPROVED)}
    assert settled["received_at"].null_count() == settled.height
    assert settled["approved_at"].null_count() == 0


# --------------------------------------------------------------------------
# Orchestration, batching and determinism
# --------------------------------------------------------------------------


def test_all_documented_datasets_are_generated(return_data: ReturnData) -> None:
    """Every dataset named in the F009 output list is produced."""
    assert set(return_data.datasets) == EXPECTED_OUTPUTS


def test_datasets_are_emitted_in_dependency_order(return_data: ReturnData) -> None:
    """Returns come first, so items and history can reference them."""
    assert list(return_data.datasets) == [dataset.name for dataset in RETURN_DATASETS]


def test_no_dataset_is_empty(return_data: ReturnData) -> None:
    """All three return datasets carry rows."""
    assert all(count > 0 for count in return_data.row_counts().values())


def test_generated_data_passes_validation(
    return_data: ReturnData, return_upstream: dict[str, pl.DataFrame]
) -> None:
    """The bundle satisfies the F009 acceptance criteria."""
    issues = validate_return_data({**return_upstream, **return_data.datasets}, DEFAULT_REFUND_TYPES)

    assert issues == []


def test_batching_does_not_change_the_output(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_reasons: pl.DataFrame
) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = ReturnConfig(return_rate=0.60, batch_size=7)
    large = ReturnConfig(return_rate=0.60, batch_size=1_000_000)

    small_returns = generate_returns(small, shipments, shipment_items, return_reasons, SEED)
    large_returns = generate_returns(large, shipments, shipment_items, return_reasons, SEED)

    assert small_returns.equals(large_returns)
    assert generate_return_items(small, small_returns, shipment_items, SEED).equals(
        generate_return_items(large, large_returns, shipment_items, SEED)
    )
    assert generate_return_status_history(small, small_returns, SEED).equals(
        generate_return_status_history(large, large_returns, SEED)
    )


def test_batches_are_bounded_by_the_configured_size(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_reasons: pl.DataFrame
) -> None:
    """No batch exceeds the configured size."""
    settings = ReturnConfig(return_rate=1.0, batch_size=10)

    batches = list(iter_return_batches(settings, shipments, shipment_items, return_reasons, SEED))

    assert batches
    assert all(batch.height <= 10 for batch in batches)


def test_generation_is_deterministic(
    return_simulation_config: SimulationConfig, return_upstream: dict[str, pl.DataFrame]
) -> None:
    """The same configuration and seed reproduce identical datasets."""
    first = generate_return_data(return_simulation_config, return_upstream)
    second = generate_return_data(return_simulation_config, return_upstream)

    assert first.seed == second.seed
    for name, frame in first:
        assert frame.equals(second[name]), f"{name} differs between runs"


def test_a_different_seed_changes_the_returns(
    return_simulation_config: SimulationConfig, return_upstream: dict[str, pl.DataFrame]
) -> None:
    """The seed drives who returns, why, and how far it got."""
    other = SimulationConfig(
        platform=PlatformConfig(seed=97_531),
        master_data=return_simulation_config.master_data,
        customers=return_simulation_config.customers,
        journey=return_simulation_config.journey,
        browsing=return_simulation_config.browsing,
        engagement=return_simulation_config.engagement,
        commerce=return_simulation_config.commerce,
        checkout=return_simulation_config.checkout,
        orders=return_simulation_config.orders,
        payments=return_simulation_config.payments,
        shipments=return_simulation_config.shipments,
        returns=return_simulation_config.returns,
    )

    baseline = generate_return_data(return_simulation_config, return_upstream)
    varied = generate_return_data(other, return_upstream)

    assert not baseline["returns"].equals(varied["returns"])


@pytest.mark.parametrize("missing", REQUIRED_RETURN_DATASETS)
def test_missing_upstream_data_is_reported(
    return_simulation_config: SimulationConfig,
    return_upstream: dict[str, pl.DataFrame],
    missing: str,
) -> None:
    """Each required upstream dataset is checked before generation starts."""
    available = {name: frame for name, frame in return_upstream.items() if name != missing}

    with pytest.raises(KeyError, match="Missing upstream data"):
        generate_return_data(return_simulation_config, available)


def test_missing_return_reasons_is_reported(
    return_simulation_config: SimulationConfig,
    return_upstream: dict[str, pl.DataFrame],
) -> None:
    """The reason vocabulary is a hard dependency, not an optional one."""
    available = {name: frame for name, frame in return_upstream.items() if name != "return_reasons"}

    with pytest.raises(KeyError, match="return_reasons"):
        generate_return_data(return_simulation_config, available)


def test_missing_upstream_names_the_prerequisite_commands(
    return_simulation_config: SimulationConfig,
    return_upstream: dict[str, pl.DataFrame],
) -> None:
    """The error tells the user which commands to run first."""
    available = {name: frame for name, frame in return_upstream.items() if name != "shipments"}

    with pytest.raises(KeyError, match="generate commerce"):
        generate_return_data(return_simulation_config, available)


def test_no_delivered_shipments_produces_empty_frames(
    config: ReturnConfig,
    shipments: pl.DataFrame,
    shipment_items: pl.DataFrame,
    return_reasons: pl.DataFrame,
) -> None:
    """A run where nothing arrived yields empty, schema-shaped frames."""
    none_delivered = shipments.with_columns(
        pl.lit(str(ShipmentStatus.IN_TRANSIT)).alias("current_status")
    )

    returns = generate_returns(config, none_delivered, shipment_items, return_reasons, SEED)
    items = generate_return_items(config, returns, shipment_items, SEED)
    history = generate_return_status_history(config, returns, SEED)

    assert returns.height == 0
    assert items.height == 0
    assert history.height == 0
    assert "return_id" in returns.columns
    assert "return_item_id" in items.columns


def test_bundle_reports_row_counts(return_data: ReturnData) -> None:
    """The bundle exposes counts for the CLI report."""
    assert return_data.total_rows() == sum(return_data.row_counts().values())


def test_unknown_dataset_access_raises(return_data: ReturnData) -> None:
    """Requesting a dataset F009 does not produce fails clearly."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        return_data["reviews"]


def test_returns_do_not_regenerate_upstream_data(
    return_data: ReturnData, return_upstream: dict[str, pl.DataFrame]
) -> None:
    """F009 consumes earlier output; it emits none of those datasets."""
    assert set(return_data.datasets).isdisjoint(set(return_upstream))
