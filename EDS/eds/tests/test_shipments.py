"""Tests for the shipment generator, shipment items, and status history."""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import pytest

from eds.config import (
    ConfigError,
    PlatformConfig,
    ShipmentConfig,
    SimulationConfig,
    load_config,
    load_shipment_config,
)
from eds.domain.commerce.enums import (
    SHIPMENT_LIFECYCLE,
    PaymentStatus,
    ShipmentStatus,
    ShippingMethod,
)
from eds.domain.commerce.schema import (
    ORDER_DATASETS,
    PAYMENT_DATASETS,
    SHIPMENT_DATASETS,
    shipment_dataset_by_name,
    shipment_dataset_names,
)
from eds.generators.commerce.shipment_generator import (
    apply_status_and_timeline,
    generate_shipments,
    iter_shipment_batches,
)
from eds.generators.commerce.shipment_item_generator import generate_shipment_items
from eds.generators.commerce.shipment_status_generator import (
    generate_shipment_status_history,
    shipment_lifecycle_position,
)
from eds.generators.commerce.shipments import (
    REQUIRED_SHIPMENT_DATASETS,
    ShipmentData,
    generate_shipment_data,
)
from eds.validation.shipment_validation import (
    SHIPMENT_NUMBER_PATTERN,
    TRACKING_NUMBER_PATTERN,
    validate_shipment_data,
)

SEED = 4242

#: How many times the payment fixture is repeated to measure outcome shares.
REPLICATION_FACTOR = 40

EXPECTED_OUTPUTS = {"shipments", "shipment_items", "shipment_status_history"}


@pytest.fixture
def config() -> ShipmentConfig:
    """Return a shipment configuration with a small batch size."""
    return ShipmentConfig(batch_size=25)


@pytest.fixture
def shipments(shipment_data: ShipmentData) -> pl.DataFrame:
    """Return the generated shipments frame."""
    return shipment_data["shipments"]


@pytest.fixture
def items(shipment_data: ShipmentData) -> pl.DataFrame:
    """Return the generated shipment items frame."""
    return shipment_data["shipment_items"]


@pytest.fixture
def history(shipment_data: ShipmentData) -> pl.DataFrame:
    """Return the generated shipment status history frame."""
    return shipment_data["shipment_status_history"]


@pytest.fixture
def payments(shipment_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the payments frame."""
    return shipment_upstream["payments"]


@pytest.fixture
def orders(shipment_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the orders frame."""
    return shipment_upstream["orders"]


@pytest.fixture
def order_lines(shipment_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the order lines frame."""
    return shipment_upstream["order_lines"]


@pytest.fixture
def checkouts(shipment_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the checkout frame."""
    return shipment_upstream["checkout"]


@pytest.fixture
def many_payments(payments: pl.DataFrame) -> pl.DataFrame:
    """Return the payments repeated enough times to measure a distribution.

    The test fixture carries a few dozen captured payments, which is far too
    few to distinguish a 3 per cent outcome from a 7 per cent one. Repeating
    them under fresh identifiers keeps every other property intact while giving
    the completion shares a sample they can actually be read from.
    """
    copies = [
        payments.with_columns((pl.col("payment_id") + index * payments.height).alias("payment_id"))
        for index in range(REPLICATION_FACTOR)
    ]
    return pl.concat(copies, how="vertical")


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_shipped_shipment_config_loads() -> None:
    """The committed shipments.yaml matches the documented defaults."""
    config = load_shipment_config()

    assert config.delivered_rate == pytest.approx(0.90)
    assert config.in_transit_rate == pytest.approx(0.07)
    assert config.shipped_rate == pytest.approx(0.03)
    assert config.shipment_number_prefix == "SHP"
    assert config.tracking_number_prefix == "TRK"


def test_shipment_config_is_part_of_the_run_configuration() -> None:
    """`load_config` includes the shipments section."""
    assert load_config().shipments.delivered_rate == pytest.approx(0.90)


def test_shipped_config_covers_every_shipping_method() -> None:
    """Both per-method tables name every F005 shipping method."""
    config = load_shipment_config()
    known = {str(member) for member in ShippingMethod}

    assert set(config.carriers) == known
    assert set(config.delivery_days) == known


def test_shipped_config_carriers_match_the_specification() -> None:
    """The suggested carrier list is what ships."""
    carriers = load_shipment_config().carriers

    assert carriers["STANDARD"] == ("UPS", "FedEx", "DHL")
    assert carriers["EXPRESS"] == ("FedEx Priority", "DHL Express")
    assert carriers["NEXT_DAY"] == ("UPS Next Day",)
    assert carriers["STORE_PICKUP"] == ("Store Pickup",)


def test_shipped_config_delivery_windows_match_the_specification() -> None:
    """The suggested day ranges are what is promised."""
    windows = load_shipment_config().delivery_days

    assert windows["STANDARD"] == (3, 7)
    assert windows["EXPRESS"] == (1, 3)
    assert windows["NEXT_DAY"] == (1, 1)
    assert windows["STORE_PICKUP"] == (0, 0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("delivered_rate", 1.5),
        ("in_transit_rate", -0.1),
        ("shipment_lead_seconds", 0),
        ("min_pack_minutes", 0),
        ("batch_size", 0),
    ],
)
def test_out_of_range_shipment_values_are_rejected(field: str, value: float) -> None:
    """Settings outside their declared bounds fail validation."""
    with pytest.raises(ValueError, match=field):
        ShipmentConfig(**{field: value})  # type: ignore[arg-type]


def test_completion_shares_must_total_one() -> None:
    """The three outcomes partition every shipment, so they sum to 1.0."""
    with pytest.raises(ValueError, match="must sum to 1.0"):
        ShipmentConfig(delivered_rate=0.5, in_transit_rate=0.1, shipped_rate=0.1)


@pytest.mark.parametrize(
    ("low_field", "high_field"),
    [
        ("min_pack_minutes", "max_pack_minutes"),
        ("min_dispatch_minutes", "max_dispatch_minutes"),
        ("min_transit_hours", "max_transit_hours"),
        ("min_delivery_hours", "max_delivery_hours"),
    ],
)
def test_inverted_wait_ranges_are_rejected(low_field: str, high_field: str) -> None:
    """A minimum above its maximum is a configuration error."""
    with pytest.raises(ValueError, match="cannot exceed"):
        ShipmentConfig(**{low_field: 500, high_field: 10})  # type: ignore[arg-type]


def test_an_empty_carrier_list_is_rejected() -> None:
    """A method with no carrier could not ship anything."""
    with pytest.raises(ValueError, match="at least one carrier"):
        ShipmentConfig(carriers={"STANDARD": ()})


def test_an_empty_carrier_table_is_rejected() -> None:
    """A table with no methods at all is a configuration error."""
    with pytest.raises(ValueError, match="at least one shipping method"):
        ShipmentConfig(carriers={})


def test_an_inverted_delivery_window_is_rejected() -> None:
    """A promise of 7 to 3 days is a configuration error."""
    with pytest.raises(ValueError, match="cannot exceed"):
        ShipmentConfig(delivery_days={"STANDARD": (7, 3)})


def test_a_negative_delivery_window_is_rejected() -> None:
    """Delivery cannot be promised before the shipment exists."""
    with pytest.raises(ValueError, match="negative days"):
        ShipmentConfig(delivery_days={"STANDARD": (-1, 3)})


def test_unknown_shipment_key_is_rejected() -> None:
    """A misspelled key is an error, not a silent no-op."""
    with pytest.raises(ValueError, match="delivery_rate"):
        ShipmentConfig(delivery_rate=0.9)  # type: ignore[call-arg]


def test_invalid_shipment_config_file_raises(tmp_path: Path) -> None:
    """An out-of-range value names the offending file."""
    (tmp_path / "shipments.yaml").write_text("delivered_rate: 5.0\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="shipments.yaml"):
        load_shipment_config(tmp_path)


def test_a_method_with_no_carrier_is_reported_at_generation(
    payments: pl.DataFrame, orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """Coverage is checked against the data, not against the enum."""
    partial = ShipmentConfig(carriers={"NEXT_DAY": ("UPS Next Day",)})

    with pytest.raises(KeyError, match="does not cover every shipping method"):
        generate_shipments(partial, payments, orders, checkouts, SEED)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_registry_lists_the_three_documented_outputs() -> None:
    """F008 declares exactly three output datasets."""
    assert len(SHIPMENT_DATASETS) == 3
    assert set(shipment_dataset_names()) == EXPECTED_OUTPUTS


def test_earlier_registries_are_unchanged() -> None:
    """Adding shipments did not disturb the F006 or F007 registries."""
    assert {dataset.name for dataset in ORDER_DATASETS} == {
        "orders",
        "order_lines",
        "order_status_history",
    }
    assert {dataset.name for dataset in PAYMENT_DATASETS} == {
        "payments",
        "payment_status_history",
    }


def test_dataset_file_names_match_the_specification() -> None:
    """Each dataset maps to the documented Parquet file name."""
    assert shipment_dataset_by_name("shipments").file_name == "shipments.parquet"
    assert shipment_dataset_by_name("shipment_items").file_name == "shipment_items.parquet"
    assert (
        shipment_dataset_by_name("shipment_status_history").file_name
        == "shipment_status_history.parquet"
    )


def test_unknown_shipment_dataset_lookup_raises() -> None:
    """Looking up an unregistered dataset fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown shipment dataset"):
        shipment_dataset_by_name("returns")


def test_only_the_five_documented_stages_exist() -> None:
    """RETURNED, LOST and DAMAGED belong to later features."""
    assert [str(member) for member in SHIPMENT_LIFECYCLE] == [
        "CREATED",
        "PACKED",
        "SHIPPED",
        "IN_TRANSIT",
        "DELIVERED",
    ]
    assert {str(member) for member in ShipmentStatus} == {
        str(member) for member in SHIPMENT_LIFECYCLE
    }


def test_lifecycle_position_orders_the_stages() -> None:
    """Positions ascend along the lifecycle."""
    assert shipment_lifecycle_position("CREATED") == 1
    assert shipment_lifecycle_position("PACKED") == 2
    assert shipment_lifecycle_position("SHIPPED") == 3
    assert shipment_lifecycle_position("IN_TRANSIT") == 4
    assert shipment_lifecycle_position("DELIVERED") == 5


def test_unknown_lifecycle_status_raises() -> None:
    """A stage from a future feature is not silently accepted."""
    with pytest.raises(KeyError, match="Lifecycle"):
        shipment_lifecycle_position("RETURNED")


# --------------------------------------------------------------------------
# Shipments
# --------------------------------------------------------------------------


def test_shipments_come_only_from_captured_payments(
    shipments: pl.DataFrame, payments: pl.DataFrame
) -> None:
    """Exactly the CAPTURED payments produce a shipment, one each."""
    captured = set(
        payments.filter(pl.col("payment_status") == str(PaymentStatus.CAPTURED))[
            "payment_id"
        ].to_list()
    )

    assert set(shipments["payment_id"].to_list()) == captured
    assert shipments["payment_id"].n_unique() == shipments.height


def test_failed_and_voided_payments_produce_no_shipment(
    shipments: pl.DataFrame, payments: pl.DataFrame
) -> None:
    """A payment that never took the money ships nothing."""
    unshipped = set(
        payments.filter(pl.col("payment_status") != str(PaymentStatus.CAPTURED))[
            "payment_id"
        ].to_list()
    )

    assert not (set(shipments["payment_id"].to_list()) & unshipped)
    assert unshipped, "the sample should contain failed or voided payments"


def test_shipment_ids_are_unique_and_sequential(shipments: pl.DataFrame) -> None:
    """Shipment ids form a dense sequence starting at one."""
    assert shipments["shipment_id"].to_list() == list(range(1, shipments.height + 1))


def test_shipment_inherits_the_payment_references(
    shipments: pl.DataFrame, payments: pl.DataFrame
) -> None:
    """Order and customer both come from the payment being shipped."""
    joined = shipments.join(payments, on="payment_id", how="inner", suffix="_pay")

    assert joined.height == shipments.height
    for column in ("order_id", "customer_id"):
        assert joined.filter(pl.col(column) != pl.col(f"{column}_pay")).height == 0, column


def test_shipping_method_is_copied_from_the_checkout(
    shipments: pl.DataFrame, orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """The customer chose the method at checkout; the shipment reuses it."""
    joined = shipments.join(orders.select("order_id", "checkout_id"), on="order_id").join(
        checkouts.select("checkout_id", pl.col("shipping_method").alias("chosen")),
        on="checkout_id",
    )

    assert joined.height == shipments.height
    assert joined.filter(pl.col("shipping_method") != pl.col("chosen")).height == 0


def test_carrier_is_one_the_method_offers(shipments: pl.DataFrame) -> None:
    """Carrier selection depends on the shipping method."""
    carriers = load_shipment_config().carriers

    for row in shipments.select("shipping_method", "carrier").unique().to_dicts():
        assert row["carrier"] in carriers[row["shipping_method"]], row


def test_a_method_with_one_carrier_always_uses_it(shipments: pl.DataFrame) -> None:
    """A single-option method leaves nothing to choose."""
    single = shipments.filter(pl.col("shipping_method") == str(ShippingMethod.NEXT_DAY))
    if single.is_empty():
        pytest.skip("no next-day shipment in this sample")

    assert single["carrier"].unique().to_list() == ["UPS Next Day"]


def test_a_method_with_several_carriers_uses_more_than_one(
    many_payments: pl.DataFrame,
    orders: pl.DataFrame,
    checkouts: pl.DataFrame,
    config: ShipmentConfig,
) -> None:
    """The choice is a real draw, not a fixed pick of the first option."""
    generated = generate_shipments(config, many_payments, orders, checkouts, SEED)
    standard = generated.filter(pl.col("shipping_method") == str(ShippingMethod.STANDARD))

    assert set(standard["carrier"].to_list()) == {"UPS", "FedEx", "DHL"}


def test_configured_carriers_reach_the_data(
    payments: pl.DataFrame, orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """Changing the configuration changes who carries the parcel."""
    settings = ShipmentConfig(
        carriers={
            "STANDARD": ("Royal Mail",),
            "EXPRESS": ("Royal Mail",),
            "NEXT_DAY": ("Royal Mail",),
            "STORE_PICKUP": ("Royal Mail",),
        }
    )

    generated = generate_shipments(settings, payments, orders, checkouts, SEED)

    assert generated["carrier"].unique().to_list() == ["Royal Mail"]


# --------------------------------------------------------------------------
# Shipment and tracking numbers
# --------------------------------------------------------------------------


def test_shipment_numbers_are_unique(shipments: pl.DataFrame) -> None:
    """The business identifier is never reused."""
    assert shipments["shipment_number"].n_unique() == shipments.height


def test_shipment_numbers_match_the_documented_format(shipments: pl.DataFrame) -> None:
    """Every number reads as PREFIX-YYYYMMDD-NNNNNN."""
    pattern = re.compile(SHIPMENT_NUMBER_PATTERN)

    for number in shipments["shipment_number"].to_list():
        assert pattern.match(number), number


def test_shipment_number_embeds_its_own_date(shipments: pl.DataFrame) -> None:
    """The date inside the number is the day the shipment was created."""
    mismatched = shipments.filter(
        pl.col("shipment_number").str.slice(-15, 8) != pl.col("created_at").dt.strftime("%Y%m%d")
    )

    assert mismatched.height == 0


def test_shipment_numbers_are_sequential_within_a_date(shipments: pl.DataFrame) -> None:
    """The sequence restarts each day and runs 1..n without gaps."""
    numbered = (
        shipments.with_columns(pl.col("created_at").dt.date().alias("day"))
        .group_by("day")
        .agg(
            pl.col("shipment_number").str.slice(-6).cast(pl.Int64).min().alias("lowest"),
            pl.col("shipment_number").str.slice(-6).cast(pl.Int64).max().alias("highest"),
            pl.len().alias("total"),
        )
    )

    assert numbered.filter(pl.col("lowest") != 1).height == 0
    assert numbered.filter(pl.col("highest") != pl.col("total")).height == 0


def test_tracking_numbers_are_unique(shipments: pl.DataFrame) -> None:
    """The carrier reference is never reused."""
    assert shipments["tracking_number"].n_unique() == shipments.height


def test_tracking_numbers_match_the_documented_format(shipments: pl.DataFrame) -> None:
    """Every tracking number reads as TRK-XXXXXXXXXX."""
    pattern = re.compile(TRACKING_NUMBER_PATTERN)

    for number in shipments["tracking_number"].to_list():
        assert pattern.match(number), number


def test_tracking_numbers_stay_unique_at_scale(
    many_payments: pl.DataFrame,
    orders: pl.DataFrame,
    checkouts: pl.DataFrame,
    config: ShipmentConfig,
) -> None:
    """The scramble is a bijection, so collisions cannot happen."""
    generated = generate_shipments(config, many_payments, orders, checkouts, SEED)

    assert generated.height > 500
    assert generated["tracking_number"].n_unique() == generated.height


def test_tracking_numbers_do_not_depend_on_the_seed(
    payments: pl.DataFrame, orders: pl.DataFrame, checkouts: pl.DataFrame, config: ShipmentConfig
) -> None:
    """They are derived from the shipment identifier, not drawn."""
    first = generate_shipments(config, payments, orders, checkouts, SEED)
    second = generate_shipments(config, payments, orders, checkouts, 999)

    assert first["tracking_number"].to_list() == second["tracking_number"].to_list()


def test_the_prefixes_are_configurable(
    payments: pl.DataFrame, orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """Different prefixes change every identifier."""
    settings = ShipmentConfig(shipment_number_prefix="PKG", tracking_number_prefix="TN")

    custom = generate_shipments(settings, payments, orders, checkouts, SEED)

    assert all(number.startswith("PKG-") for number in custom["shipment_number"].to_list())
    assert all(number.startswith("TN-") for number in custom["tracking_number"].to_list())


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


def test_shipments_are_created_after_their_payment(
    shipments: pl.DataFrame, payments: pl.DataFrame
) -> None:
    """Goods move after the money did."""
    joined = shipments.join(
        payments.select("payment_id", pl.col("captured_at").alias("paid_at")), on="payment_id"
    )

    assert joined.filter(pl.col("created_at") <= pl.col("paid_at")).height == 0


def test_dispatch_follows_creation(shipments: pl.DataFrame) -> None:
    """A shipment is packed and dispatched after it is created."""
    assert shipments.filter(pl.col("shipped_at") <= pl.col("created_at")).height == 0


def test_delivery_follows_dispatch(shipments: pl.DataFrame) -> None:
    """delivered_at must be after shipped_at."""
    delivered = shipments.filter(pl.col("delivered_at").is_not_null())

    assert delivered.height > 0
    assert delivered.filter(pl.col("delivered_at") <= pl.col("shipped_at")).height == 0


def test_delivery_is_recorded_only_for_delivered_shipments(shipments: pl.DataFrame) -> None:
    """A parcel still in transit has not arrived."""
    delivered = shipments.filter(pl.col("current_status") == str(ShipmentStatus.DELIVERED))
    rest = shipments.filter(pl.col("current_status") != str(ShipmentStatus.DELIVERED))

    assert delivered["delivered_at"].null_count() == 0
    assert rest["delivered_at"].null_count() == rest.height


def test_every_shipment_has_been_dispatched(shipments: pl.DataFrame) -> None:
    """The completion shares sum to one from SHIPPED onwards."""
    assert shipments["shipped_at"].null_count() == 0


def test_the_estimate_is_no_earlier_than_creation(shipments: pl.DataFrame) -> None:
    """The promise is made when the shipment is created."""
    assert shipments.filter(pl.col("estimated_delivery_at") < pl.col("created_at")).height == 0


def test_estimated_delivery_stays_inside_the_configured_window(
    shipments: pl.DataFrame,
) -> None:
    """Every method's promise falls in its configured day range."""
    windows = load_shipment_config().delivery_days
    measured = shipments.with_columns(
        (pl.col("estimated_delivery_at") - pl.col("created_at")).dt.total_days().alias("days")
    )

    for row in (
        measured.group_by("shipping_method")
        .agg(pl.col("days").min().alias("lowest"), pl.col("days").max().alias("highest"))
        .to_dicts()
    ):
        lowest, highest = windows[row["shipping_method"]]
        assert row["lowest"] >= lowest, row
        assert row["highest"] <= highest, row


def test_store_pickup_is_promised_the_same_day(
    config: ShipmentConfig,
    payments: pl.DataFrame,
    orders: pl.DataFrame,
    checkouts: pl.DataFrame,
) -> None:
    """A same-day window means the estimate equals the creation moment.

    The fixture may carry no store pickup, so every checkout is switched to it
    rather than skipping the case.
    """
    pickup_only = checkouts.with_columns(
        pl.lit(str(ShippingMethod.STORE_PICKUP)).alias("shipping_method")
    )

    generated = generate_shipments(config, payments, orders, pickup_only, SEED)

    assert generated.height > 0
    assert generated["carrier"].unique().to_list() == ["Store Pickup"]
    assert generated.filter(pl.col("estimated_delivery_at") != pl.col("created_at")).height == 0


# --------------------------------------------------------------------------
# Shipment items
# --------------------------------------------------------------------------


def test_shipment_item_ids_are_unique_and_sequential(items: pl.DataFrame) -> None:
    """Item ids form a dense sequence starting at one."""
    assert items["shipment_item_id"].to_list() == list(range(1, items.height + 1))


def test_items_originate_only_from_order_lines(
    items: pl.DataFrame, order_lines: pl.DataFrame
) -> None:
    """Every item is an order line that moved."""
    assert set(items["order_line_id"].to_list()) <= set(order_lines["order_line_id"].to_list())


def test_items_belong_to_their_shipment_own_order(
    shipments: pl.DataFrame, items: pl.DataFrame, order_lines: pl.DataFrame
) -> None:
    """An item never carries a line from somebody else's order."""
    joined = items.join(
        shipments.select("shipment_id", pl.col("order_id").alias("shipment_order")),
        on="shipment_id",
    ).join(
        order_lines.select("order_line_id", pl.col("order_id").alias("line_order")),
        on="order_line_id",
    )

    assert joined.height == items.height
    assert joined.filter(pl.col("shipment_order") != pl.col("line_order")).height == 0


def test_quantity_and_product_are_copied_from_the_order_line(
    items: pl.DataFrame, order_lines: pl.DataFrame
) -> None:
    """No partial shipments, so the whole line goes out."""
    joined = items.join(order_lines, on="order_line_id", how="inner", suffix="_line")

    assert joined.filter(pl.col("quantity") != pl.col("quantity_line")).height == 0
    assert joined.filter(pl.col("product_id") != pl.col("product_id_line")).height == 0


def test_every_line_of_a_shipped_order_is_shipped(
    shipments: pl.DataFrame, items: pl.DataFrame, order_lines: pl.DataFrame
) -> None:
    """Split shipments and backorders are out of scope."""
    expected = order_lines.join(shipments.select("order_id"), on="order_id", how="semi")

    assert set(items["order_line_id"].to_list()) == set(expected["order_line_id"].to_list())


def test_an_order_line_ships_exactly_once(items: pl.DataFrame) -> None:
    """One shipment per order means one item per line."""
    assert items["order_line_id"].n_unique() == items.height


def test_items_are_stamped_with_their_shipment(
    shipments: pl.DataFrame, items: pl.DataFrame
) -> None:
    """The item exists as soon as the shipment does."""
    joined = items.join(
        shipments.select("shipment_id", pl.col("created_at").alias("shipped_from")),
        on="shipment_id",
    )

    assert joined.filter(pl.col("created_at") != pl.col("shipped_from")).height == 0


def test_a_shipment_whose_order_has_no_lines_carries_no_items(
    shipments: pl.DataFrame, items: pl.DataFrame, order_lines: pl.DataFrame
) -> None:
    """Every item in the cart was removed before checkout, so nothing ships."""
    lined = set(order_lines["order_id"].to_list())
    empty = shipments.filter(~pl.col("order_id").is_in(list(lined)))

    if empty.is_empty():
        pytest.skip("every shipped order in this sample kept at least one line")
    assert not (set(empty["shipment_id"].to_list()) & set(items["shipment_id"].to_list()))


# --------------------------------------------------------------------------
# Status history
# --------------------------------------------------------------------------


def test_history_ids_are_unique_and_sequential(history: pl.DataFrame) -> None:
    """History ids form a dense sequence starting at one."""
    assert history["history_id"].to_list() == list(range(1, history.height + 1))


def test_every_shipment_has_a_created_row(shipments: pl.DataFrame, history: pl.DataFrame) -> None:
    """The lifecycle always begins at CREATED."""
    created = history.filter(pl.col("status") == str(ShipmentStatus.CREATED))

    assert created.height == shipments.height
    assert set(created["sequence"].to_list()) == {1}


def test_every_shipment_reaches_shipped(shipments: pl.DataFrame, history: pl.DataFrame) -> None:
    """The first three stages are unconditional."""
    for status in (ShipmentStatus.CREATED, ShipmentStatus.PACKED, ShipmentStatus.SHIPPED):
        assert history.filter(pl.col("status") == str(status)).height == shipments.height, status


def test_sequences_start_at_one_and_are_contiguous(history: pl.DataFrame) -> None:
    """Numbering restarts per shipment without gaps."""
    grouped = history.group_by("shipment_id").agg(
        pl.col("sequence").min().alias("lowest"),
        pl.col("sequence").max().alias("highest"),
        pl.len().alias("total"),
    )

    assert grouped.filter(pl.col("lowest") != 1).height == 0
    assert grouped.filter(pl.col("highest") != pl.col("total")).height == 0


def test_history_is_chronological(history: pl.DataFrame) -> None:
    """Time moves forwards with the sequence."""
    ordered = history.sort("shipment_id", "sequence").with_columns(
        pl.col("status_timestamp").shift(1).over("shipment_id").alias("previous")
    )

    assert (
        ordered.filter(
            pl.col("previous").is_not_null() & (pl.col("status_timestamp") <= pl.col("previous"))
        ).height
        == 0
    )


def test_history_starts_no_earlier_than_the_shipment(
    shipments: pl.DataFrame, history: pl.DataFrame
) -> None:
    """The first status is recorded when the shipment is created."""
    first = history.filter(pl.col("sequence") == 1).select(
        "shipment_id", pl.col("status_timestamp").alias("at")
    )
    joined = shipments.join(first, on="shipment_id", how="inner")

    assert joined.filter(pl.col("at") < pl.col("created_at")).height == 0


def test_delivery_implies_being_in_transit(history: pl.DataFrame) -> None:
    """A parcel is only delivered after it has been in transit."""
    delivered = set(
        history.filter(pl.col("status") == str(ShipmentStatus.DELIVERED))["shipment_id"].to_list()
    )
    in_transit = set(
        history.filter(pl.col("status") == str(ShipmentStatus.IN_TRANSIT))["shipment_id"].to_list()
    )

    assert delivered <= in_transit


def test_current_status_equals_the_latest_history_row(
    shipments: pl.DataFrame, history: pl.DataFrame
) -> None:
    """ADR-012: the history is the source of truth."""
    latest = (
        history.sort("shipment_id", "sequence")
        .group_by("shipment_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest"))
    )
    joined = shipments.join(latest, on="shipment_id", how="inner")

    assert joined.height == shipments.height
    assert joined.filter(pl.col("current_status") != pl.col("latest")).height == 0


def test_timeline_columns_come_from_the_history(
    shipments: pl.DataFrame, history: pl.DataFrame
) -> None:
    """shipped_at and delivered_at are denormalised, not maintained apart."""
    stamps = history.group_by("shipment_id").agg(
        pl.col("status_timestamp")
        .filter(pl.col("status") == str(ShipmentStatus.SHIPPED))
        .first()
        .alias("from_history_shipped"),
        pl.col("status_timestamp")
        .filter(pl.col("status") == str(ShipmentStatus.DELIVERED))
        .first()
        .alias("from_history_delivered"),
    )
    joined = shipments.join(stamps, on="shipment_id", how="inner")

    assert joined.filter(pl.col("shipped_at") != pl.col("from_history_shipped")).height == 0
    assert (
        joined.filter(
            pl.col("delivered_at").is_null() != pl.col("from_history_delivered").is_null()
        ).height
        == 0
    )
    assert (
        joined.filter(
            pl.col("delivered_at").is_not_null()
            & (pl.col("delivered_at") != pl.col("from_history_delivered"))
        ).height
        == 0
    )


def test_no_future_lifecycle_stage_is_generated(history: pl.DataFrame) -> None:
    """RETURNED, LOST and DAMAGED belong to later features."""
    assert set(history["status"].to_list()) <= {str(member) for member in SHIPMENT_LIFECYCLE}


def test_completion_distribution_is_approximately_as_specified(
    many_payments: pl.DataFrame,
    orders: pl.DataFrame,
    checkouts: pl.DataFrame,
) -> None:
    """Roughly 90 / 7 / 3 per cent deliver, sit in transit, or just ship."""
    settings = ShipmentConfig()
    generated = generate_shipments(settings, many_payments, orders, checkouts, SEED)
    history = generate_shipment_status_history(settings, generated, SEED)
    settled = apply_status_and_timeline(generated, history)

    total = settled.height
    share = {
        row["current_status"]: row["count"] / total
        for row in settled["current_status"].value_counts().to_dicts()
    }

    assert total >= 500, "the replicated sample should be large enough to read"
    assert share[str(ShipmentStatus.DELIVERED)] == pytest.approx(0.90, abs=0.03)
    assert share.get(str(ShipmentStatus.IN_TRANSIT), 0.0) == pytest.approx(0.07, abs=0.03)
    assert share.get(str(ShipmentStatus.SHIPPED), 0.0) == pytest.approx(0.03, abs=0.02)


def test_every_shipment_can_be_delivered(
    payments: pl.DataFrame, orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """With a delivered rate of one, every history runs the full five stages."""
    settings = ShipmentConfig(delivered_rate=1.0, in_transit_rate=0.0, shipped_rate=0.0)

    generated = generate_shipments(settings, payments, orders, checkouts, SEED)
    history = generate_shipment_status_history(settings, generated, SEED)
    settled = apply_status_and_timeline(generated, history)

    assert history.height == generated.height * 5
    assert set(settled["current_status"].to_list()) == {str(ShipmentStatus.DELIVERED)}
    assert settled["delivered_at"].null_count() == 0


def test_every_shipment_can_stop_at_dispatch(
    payments: pl.DataFrame, orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """With a shipped rate of one, nothing has left the depot's records."""
    settings = ShipmentConfig(delivered_rate=0.0, in_transit_rate=0.0, shipped_rate=1.0)

    generated = generate_shipments(settings, payments, orders, checkouts, SEED)
    history = generate_shipment_status_history(settings, generated, SEED)
    settled = apply_status_and_timeline(generated, history)

    assert history.height == generated.height * 3
    assert set(settled["current_status"].to_list()) == {str(ShipmentStatus.SHIPPED)}
    assert settled["delivered_at"].null_count() == settled.height
    assert settled["shipped_at"].null_count() == 0


# --------------------------------------------------------------------------
# Orchestration, batching and determinism
# --------------------------------------------------------------------------


def test_all_documented_datasets_are_generated(shipment_data: ShipmentData) -> None:
    """Every dataset named in the F008 output list is produced."""
    assert set(shipment_data.datasets) == EXPECTED_OUTPUTS


def test_datasets_are_emitted_in_dependency_order(shipment_data: ShipmentData) -> None:
    """Shipments come first, so items and history can reference them."""
    assert list(shipment_data.datasets) == [dataset.name for dataset in SHIPMENT_DATASETS]


def test_no_dataset_is_empty(shipment_data: ShipmentData) -> None:
    """All three shipment datasets carry rows."""
    assert all(count > 0 for count in shipment_data.row_counts().values())


def test_generated_data_passes_validation(
    shipment_data: ShipmentData, shipment_upstream: dict[str, pl.DataFrame]
) -> None:
    """The bundle satisfies the F008 acceptance criteria."""
    issues = validate_shipment_data(
        {**shipment_upstream, **shipment_data.datasets}, ShipmentConfig().carriers
    )

    assert issues == []


def test_batching_does_not_change_the_output(
    payments: pl.DataFrame,
    orders: pl.DataFrame,
    checkouts: pl.DataFrame,
    order_lines: pl.DataFrame,
) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = ShipmentConfig(batch_size=7)
    large = ShipmentConfig(batch_size=1_000_000)

    small_shipments = generate_shipments(small, payments, orders, checkouts, SEED)
    large_shipments = generate_shipments(large, payments, orders, checkouts, SEED)

    assert small_shipments.equals(large_shipments)
    assert generate_shipment_items(small, small_shipments, order_lines).equals(
        generate_shipment_items(large, large_shipments, order_lines)
    )
    assert generate_shipment_status_history(small, small_shipments, SEED).equals(
        generate_shipment_status_history(large, large_shipments, SEED)
    )


def test_batches_are_bounded_by_the_configured_size(
    payments: pl.DataFrame, orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """No batch exceeds the configured size."""
    batches = list(
        iter_shipment_batches(ShipmentConfig(batch_size=40), payments, orders, checkouts, SEED)
    )

    assert batches
    assert all(batch.height <= 40 for batch in batches)


def test_generation_is_deterministic(
    shipment_simulation_config: SimulationConfig, shipment_upstream: dict[str, pl.DataFrame]
) -> None:
    """The same configuration and seed reproduce identical datasets."""
    first = generate_shipment_data(shipment_simulation_config, shipment_upstream)
    second = generate_shipment_data(shipment_simulation_config, shipment_upstream)

    assert first.seed == second.seed
    for name, frame in first:
        assert frame.equals(second[name]), f"{name} differs between runs"


def test_a_different_seed_changes_the_lifecycle(
    shipment_simulation_config: SimulationConfig, shipment_upstream: dict[str, pl.DataFrame]
) -> None:
    """The seed drives how far each shipment progressed."""
    other = SimulationConfig(
        platform=PlatformConfig(seed=97_531),
        master_data=shipment_simulation_config.master_data,
        customers=shipment_simulation_config.customers,
        journey=shipment_simulation_config.journey,
        browsing=shipment_simulation_config.browsing,
        engagement=shipment_simulation_config.engagement,
        commerce=shipment_simulation_config.commerce,
        checkout=shipment_simulation_config.checkout,
        orders=shipment_simulation_config.orders,
        payments=shipment_simulation_config.payments,
        shipments=shipment_simulation_config.shipments,
    )

    baseline = generate_shipment_data(shipment_simulation_config, shipment_upstream)
    varied = generate_shipment_data(other, shipment_upstream)

    assert not baseline["shipment_status_history"].equals(varied["shipment_status_history"])


def test_shipment_items_do_not_depend_on_the_seed(
    shipments: pl.DataFrame, order_lines: pl.DataFrame, config: ShipmentConfig
) -> None:
    """The items are a join, so no seed appears in them."""
    assert generate_shipment_items(config, shipments, order_lines).equals(
        generate_shipment_items(config, shipments, order_lines)
    )


@pytest.mark.parametrize("missing", REQUIRED_SHIPMENT_DATASETS)
def test_missing_upstream_data_is_reported(
    shipment_simulation_config: SimulationConfig,
    shipment_upstream: dict[str, pl.DataFrame],
    missing: str,
) -> None:
    """Each required upstream dataset is checked before generation starts."""
    available = {name: frame for name, frame in shipment_upstream.items() if name != missing}

    with pytest.raises(KeyError, match="Missing upstream data"):
        generate_shipment_data(shipment_simulation_config, available)


def test_missing_upstream_names_the_prerequisite_commands(
    shipment_simulation_config: SimulationConfig,
    shipment_upstream: dict[str, pl.DataFrame],
) -> None:
    """The error tells the user which commands to run first."""
    available = {name: frame for name, frame in shipment_upstream.items() if name != "payments"}

    with pytest.raises(KeyError, match="generate commerce"):
        generate_shipment_data(shipment_simulation_config, available)


def test_no_captured_payments_produces_empty_frames(
    config: ShipmentConfig,
    payments: pl.DataFrame,
    orders: pl.DataFrame,
    checkouts: pl.DataFrame,
    order_lines: pl.DataFrame,
) -> None:
    """A run where nothing was captured yields empty, schema-shaped frames."""
    none_captured = payments.with_columns(pl.lit(str(PaymentStatus.FAILED)).alias("payment_status"))

    shipments = generate_shipments(config, none_captured, orders, checkouts, SEED)
    items = generate_shipment_items(config, shipments, order_lines)
    history = generate_shipment_status_history(config, shipments, SEED)

    assert shipments.height == 0
    assert items.height == 0
    assert history.height == 0
    assert "shipment_id" in shipments.columns
    assert "shipment_item_id" in items.columns


def test_bundle_reports_row_counts(shipment_data: ShipmentData) -> None:
    """The bundle exposes counts for the CLI report."""
    assert shipment_data.total_rows() == sum(shipment_data.row_counts().values())


def test_unknown_dataset_access_raises(shipment_data: ShipmentData) -> None:
    """Requesting a dataset F008 does not produce fails clearly."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        shipment_data["returns"]


def test_shipments_do_not_regenerate_upstream_data(
    shipment_data: ShipmentData, shipment_upstream: dict[str, pl.DataFrame]
) -> None:
    """F008 consumes earlier output; it emits none of those datasets."""
    assert set(shipment_data.datasets).isdisjoint(set(shipment_upstream))
