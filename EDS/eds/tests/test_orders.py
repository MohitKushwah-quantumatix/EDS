"""Tests for the order generator, order lines, and status history."""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import pytest

from eds.config import (
    ConfigError,
    OrderConfig,
    PlatformConfig,
    SimulationConfig,
    load_config,
    load_order_config,
)
from eds.domain.commerce.enums import (
    ORDER_LIFECYCLE,
    CheckoutStatus,
    OrderStatus,
)
from eds.domain.commerce.schema import (
    CHECKOUT_DATASETS,
    COMMERCE_DATASETS,
    ORDER_DATASETS,
    order_dataset_by_name,
    order_dataset_names,
)
from eds.generators.commerce.order_generator import (
    apply_current_status,
    generate_orders,
    iter_order_batches,
)
from eds.generators.commerce.order_line_generator import (
    active_cart_items,
    generate_order_lines,
)
from eds.generators.commerce.order_status_generator import (
    generate_order_status_history,
    lifecycle_position,
)
from eds.generators.commerce.orders import (
    REQUIRED_ORDER_DATASETS,
    OrderData,
    generate_order_data,
)
from eds.validation.order_validation import ORDER_NUMBER_PATTERN, validate_order_data

SEED = 4242
MONEY_TOLERANCE = 0.011

EXPECTED_OUTPUTS = {"orders", "order_lines", "order_status_history"}
FINANCIAL_COLUMNS = (
    "subtotal",
    "shipping_cost",
    "tax_amount",
    "discount_amount",
    "total_amount",
)


@pytest.fixture
def config() -> OrderConfig:
    """Return an order configuration with a small batch size."""
    return OrderConfig(batch_size=25)


@pytest.fixture
def orders(order_data: OrderData) -> pl.DataFrame:
    """Return the generated orders frame."""
    return order_data["orders"]


@pytest.fixture
def lines(order_data: OrderData) -> pl.DataFrame:
    """Return the generated order lines frame."""
    return order_data["order_lines"]


@pytest.fixture
def history(order_data: OrderData) -> pl.DataFrame:
    """Return the generated order status history frame."""
    return order_data["order_status_history"]


@pytest.fixture
def checkouts(order_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the checkout frame."""
    return order_upstream["checkout"]


@pytest.fixture
def cart_items(order_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the cart items frame."""
    return order_upstream["cart_items"]


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_shipped_order_config_loads() -> None:
    """The committed orders.yaml matches the documented defaults."""
    config = load_order_config()

    assert config.confirmed_rate == pytest.approx(0.95)
    assert config.processing_rate == pytest.approx(0.90)
    assert config.order_number_prefix == "ORD"


def test_order_config_is_part_of_the_run_configuration() -> None:
    """`load_config` includes the orders section."""
    assert load_config().orders.confirmed_rate == pytest.approx(0.95)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confirmed_rate", 1.5),
        ("processing_rate", -0.1),
        ("order_lead_seconds", 0),
        ("min_confirm_minutes", 0),
        ("batch_size", 0),
    ],
)
def test_out_of_range_order_values_are_rejected(field: str, value: float) -> None:
    """Settings outside their declared bounds fail validation."""
    with pytest.raises(ValueError, match=field):
        OrderConfig(**{field: value})  # type: ignore[arg-type]


def test_processing_rate_cannot_exceed_confirmed_rate() -> None:
    """An order is only processed after it has been confirmed."""
    with pytest.raises(ValueError, match="cannot exceed"):
        OrderConfig(confirmed_rate=0.5, processing_rate=0.9)


@pytest.mark.parametrize(
    ("low_field", "high_field"),
    [
        ("min_confirm_minutes", "max_confirm_minutes"),
        ("min_processing_minutes", "max_processing_minutes"),
    ],
)
def test_inverted_wait_ranges_are_rejected(low_field: str, high_field: str) -> None:
    """A minimum above its maximum is a configuration error."""
    with pytest.raises(ValueError, match="cannot exceed"):
        OrderConfig(**{low_field: 500, high_field: 10})  # type: ignore[arg-type]


def test_unknown_order_key_is_rejected() -> None:
    """A misspelled key is an error, not a silent no-op."""
    with pytest.raises(ValueError, match="confirm_rate"):
        OrderConfig(confirm_rate=0.9)  # type: ignore[call-arg]


def test_invalid_order_config_file_raises(tmp_path: Path) -> None:
    """An out-of-range value names the offending file."""
    (tmp_path / "orders.yaml").write_text("confirmed_rate: 5.0\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="orders.yaml"):
        load_order_config(tmp_path)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_registry_lists_the_three_documented_outputs() -> None:
    """F006 declares exactly three output datasets."""
    assert len(ORDER_DATASETS) == 3
    assert set(order_dataset_names()) == EXPECTED_OUTPUTS


def test_earlier_registries_are_unchanged() -> None:
    """Adding orders did not disturb the F004 or F005 registries."""
    assert {dataset.name for dataset in COMMERCE_DATASETS} == {
        "shopping_carts",
        "cart_items",
    }
    assert {dataset.name for dataset in CHECKOUT_DATASETS} == {"checkout"}


def test_dataset_file_names_match_the_specification() -> None:
    """Each dataset maps to the documented Parquet file name."""
    assert order_dataset_by_name("orders").file_name == "orders.parquet"
    assert order_dataset_by_name("order_lines").file_name == "order_lines.parquet"
    assert order_dataset_by_name("order_status_history").file_name == "order_status_history.parquet"


def test_unknown_order_dataset_lookup_raises() -> None:
    """Looking up an unregistered dataset fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown order dataset"):
        order_dataset_by_name("payments")


def test_only_the_first_three_lifecycle_stages_exist() -> None:
    """PACKED, SHIPPED and DELIVERED belong to later features."""
    assert [str(member) for member in ORDER_LIFECYCLE] == [
        "CREATED",
        "CONFIRMED",
        "PROCESSING",
    ]
    assert {str(member) for member in OrderStatus} == {str(member) for member in ORDER_LIFECYCLE}


def test_lifecycle_position_orders_the_stages() -> None:
    """Positions ascend along the lifecycle."""
    assert lifecycle_position("CREATED") == 1
    assert lifecycle_position("CONFIRMED") == 2
    assert lifecycle_position("PROCESSING") == 3


def test_unknown_lifecycle_status_raises() -> None:
    """A stage from a future feature is not silently accepted."""
    with pytest.raises(KeyError, match="Lifecycle"):
        lifecycle_position("DELIVERED")


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------


def test_orders_come_only_from_successful_checkouts(
    orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """Exactly the SUCCESS checkouts produce an order, one each."""
    successful = set(
        checkouts.filter(pl.col("checkout_status") == str(CheckoutStatus.SUCCESS))[
            "checkout_id"
        ].to_list()
    )

    assert set(orders["checkout_id"].to_list()) == successful
    assert orders["checkout_id"].n_unique() == orders.height


def test_failed_and_abandoned_checkouts_produce_no_order(
    orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """Ineligible checkouts never appear."""
    ineligible = set(
        checkouts.filter(pl.col("checkout_status") != str(CheckoutStatus.SUCCESS))[
            "checkout_id"
        ].to_list()
    )

    assert not (set(orders["checkout_id"].to_list()) & ineligible)
    assert ineligible, "the sample should contain failed or abandoned checkouts"


def test_order_ids_are_unique_and_sequential(orders: pl.DataFrame) -> None:
    """Order ids form a dense sequence starting at one."""
    assert orders["order_id"].to_list() == list(range(1, orders.height + 1))


def test_financial_values_are_copied_from_the_checkout(
    orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """ADR-007: money is copied verbatim, never recalculated."""
    joined = orders.join(checkouts, on="checkout_id", how="inner", suffix="_ck")

    assert joined.height == orders.height
    for column in FINANCIAL_COLUMNS:
        assert joined.filter(pl.col(column) != pl.col(f"{column}_ck")).height == 0, column


def test_order_inherits_the_checkout_references(
    orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """Cart, customer, session and addresses all come from the checkout."""
    joined = orders.join(checkouts, on="checkout_id", how="inner", suffix="_ck")

    for column in (
        "cart_id",
        "customer_id",
        "session_id",
        "shipping_address_id",
        "billing_address_id",
    ):
        assert joined.filter(pl.col(column) != pl.col(f"{column}_ck")).height == 0, column


def test_orders_are_created_after_their_checkout(
    orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """The order document follows the checkout that produced it."""
    joined = orders.join(
        checkouts.select("checkout_id", pl.col("completed_at").alias("done")),
        on="checkout_id",
    )

    assert joined.filter(pl.col("created_at") <= pl.col("done")).height == 0


def test_order_date_is_the_date_of_created_at(orders: pl.DataFrame) -> None:
    """The two never disagree, which is what keeps the order number right."""
    assert orders.filter(pl.col("order_date") != pl.col("created_at").dt.date()).height == 0


# --------------------------------------------------------------------------
# Order numbers
# --------------------------------------------------------------------------


def test_order_numbers_are_unique(orders: pl.DataFrame) -> None:
    """The business identifier is never reused."""
    assert orders["order_number"].n_unique() == orders.height


def test_order_numbers_match_the_documented_format(orders: pl.DataFrame) -> None:
    """Every number reads as PREFIX-YYYYMMDD-NNNNNN."""
    pattern = re.compile(ORDER_NUMBER_PATTERN)

    for number in orders["order_number"].to_list():
        assert pattern.match(number), number


def test_order_number_embeds_its_own_order_date(orders: pl.DataFrame) -> None:
    """The date inside the number is the order's date."""
    mismatched = orders.filter(
        pl.col("order_number").str.slice(-15, 8) != pl.col("order_date").dt.strftime("%Y%m%d")
    )

    assert mismatched.height == 0


def test_order_numbers_are_sequential_within_a_date(orders: pl.DataFrame) -> None:
    """The sequence restarts each day and runs 1..n without gaps."""
    numbered = orders.group_by("order_date").agg(
        pl.col("order_number").str.slice(-6).cast(pl.Int64).min().alias("lowest"),
        pl.col("order_number").str.slice(-6).cast(pl.Int64).max().alias("highest"),
        pl.len().alias("total"),
    )

    assert numbered.filter(pl.col("lowest") != 1).height == 0
    assert numbered.filter(pl.col("highest") != pl.col("total")).height == 0


def test_a_day_with_several_orders_numbers_them_in_order(
    orders: pl.DataFrame,
) -> None:
    """Where a date carries more than one order the sequence is used."""
    busiest = orders.group_by("order_date").len().sort("len", descending=True).row(0, named=True)
    if busiest["len"] < 2:
        pytest.skip("no date carries more than one order in this sample")

    same_day = orders.filter(pl.col("order_date") == busiest["order_date"]).sort(
        "created_at", "order_id"
    )
    sequences = [int(number[-6:]) for number in same_day["order_number"].to_list()]

    assert sequences == sorted(sequences)


def test_the_prefix_is_configurable(config: OrderConfig, checkouts: pl.DataFrame) -> None:
    """A different prefix changes every number."""
    custom = generate_orders(
        OrderConfig(order_number_prefix="INV", batch_size=config.batch_size), checkouts
    )

    assert all(number.startswith("INV-") for number in custom["order_number"].to_list())


# --------------------------------------------------------------------------
# Order lines
# --------------------------------------------------------------------------


def test_order_line_ids_are_unique_and_sequential(lines: pl.DataFrame) -> None:
    """Line ids form a dense sequence starting at one."""
    assert lines["order_line_id"].to_list() == list(range(1, lines.height + 1))


def test_line_total_is_quantity_times_unit_price(lines: pl.DataFrame) -> None:
    """The arithmetic holds on every line."""
    mismatched = lines.filter(
        (pl.col("line_total") - pl.col("quantity") * pl.col("unit_price")).abs() > MONEY_TOLERANCE
    )

    assert mismatched.height == 0


def test_lines_reconcile_with_the_order_subtotal(orders: pl.DataFrame, lines: pl.DataFrame) -> None:
    """The sum of the lines equals the subtotal copied from the checkout."""
    summed = lines.group_by("order_id").agg(pl.col("line_total").sum().alias("total"))
    joined = orders.join(summed, on="order_id", how="left").with_columns(
        pl.col("total").fill_null(0.0)
    )

    assert joined.filter((pl.col("subtotal") - pl.col("total")).abs() > MONEY_TOLERANCE).height == 0


def test_lines_come_from_active_cart_items_only(
    orders: pl.DataFrame, lines: pl.DataFrame, cart_items: pl.DataFrame
) -> None:
    """Every line matches an item still in the order's cart."""
    active = active_cart_items(cart_items).select("cart_id", "product_id", "quantity", "unit_price")
    matched = lines.join(orders.select("order_id", "cart_id"), on="order_id", how="inner").join(
        active.with_columns(pl.lit(True).alias("found")),
        on=["cart_id", "product_id", "quantity", "unit_price"],
        how="left",
    )

    assert matched.filter(pl.col("found").is_null()).height == 0


def test_removed_cart_items_never_become_lines(
    orders: pl.DataFrame, lines: pl.DataFrame, cart_items: pl.DataFrame
) -> None:
    """An item the customer took back out is not ordered."""
    removed = cart_items.filter(pl.col("removed_at").is_not_null()).select("cart_id", "product_id")
    assert removed.height > 0, "the sample should contain removed items"

    leaked = (
        lines.join(orders.select("order_id", "cart_id"), on="order_id", how="inner")
        .join(
            removed.with_columns(pl.lit(True).alias("gone")),
            on=["cart_id", "product_id"],
            how="left",
        )
        .filter(pl.col("gone").is_not_null())
    )

    assert leaked.height == 0


def test_every_line_belongs_to_a_real_order(orders: pl.DataFrame, lines: pl.DataFrame) -> None:
    """No line is orphaned."""
    assert set(lines["order_id"].to_list()) <= set(orders["order_id"].to_list())


def test_an_order_whose_items_were_all_removed_has_no_lines(
    orders: pl.DataFrame, lines: pl.DataFrame
) -> None:
    """A zero-subtotal order carries no lines, and still reconciles."""
    with_lines = set(lines["order_id"].to_list())
    empty = orders.filter(~pl.col("order_id").is_in(list(with_lines)))

    if empty.is_empty():
        pytest.skip("every order in this sample kept at least one item")
    assert set(empty["subtotal"].to_list()) == {0.0}


# --------------------------------------------------------------------------
# Status history
# --------------------------------------------------------------------------


def test_history_ids_are_unique_and_sequential(history: pl.DataFrame) -> None:
    """History ids form a dense sequence starting at one."""
    assert history["history_id"].to_list() == list(range(1, history.height + 1))


def test_every_order_has_a_created_row(orders: pl.DataFrame, history: pl.DataFrame) -> None:
    """The lifecycle always begins at CREATED."""
    created = history.filter(pl.col("status") == str(OrderStatus.CREATED))

    assert created.height == orders.height
    assert set(created["sequence"].to_list()) == {1}


def test_sequences_start_at_one_and_are_contiguous(history: pl.DataFrame) -> None:
    """Numbering restarts per order without gaps."""
    grouped = history.group_by("order_id").agg(
        pl.col("sequence").min().alias("lowest"),
        pl.col("sequence").max().alias("highest"),
        pl.len().alias("total"),
    )

    assert grouped.filter(pl.col("lowest") != 1).height == 0
    assert grouped.filter(pl.col("highest") != pl.col("total")).height == 0


def test_history_is_chronological(history: pl.DataFrame) -> None:
    """Time moves forwards with the sequence."""
    ordered = history.sort("order_id", "sequence").with_columns(
        pl.col("status_timestamp").shift(1).over("order_id").alias("previous")
    )

    assert (
        ordered.filter(
            pl.col("previous").is_not_null() & (pl.col("status_timestamp") <= pl.col("previous"))
        ).height
        == 0
    )


def test_history_starts_no_earlier_than_the_order(
    orders: pl.DataFrame, history: pl.DataFrame
) -> None:
    """The first status is recorded when the order is created."""
    first = history.filter(pl.col("sequence") == 1).select(
        "order_id", pl.col("status_timestamp").alias("at")
    )
    joined = orders.join(first, on="order_id", how="inner")

    assert joined.filter(pl.col("at") < pl.col("created_at")).height == 0


def test_current_status_equals_the_latest_history_row(
    orders: pl.DataFrame, history: pl.DataFrame
) -> None:
    """ADR-012: the history is the source of truth."""
    latest = (
        history.sort("order_id", "sequence")
        .group_by("order_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest"))
    )
    joined = orders.join(latest, on="order_id", how="inner")

    assert joined.height == orders.height
    assert joined.filter(pl.col("current_status") != pl.col("latest")).height == 0


def test_lifecycle_distribution_is_approximately_as_specified(
    orders: pl.DataFrame, history: pl.DataFrame
) -> None:
    """Roughly 100 / 95 / 90 per cent reach each stage."""
    total = orders.height
    reached = {
        row["status"]: row["count"] / total for row in history["status"].value_counts().to_dicts()
    }

    assert reached[str(OrderStatus.CREATED)] == pytest.approx(1.00, abs=0.001)
    assert reached[str(OrderStatus.CONFIRMED)] == pytest.approx(0.95, abs=0.07)
    assert reached[str(OrderStatus.PROCESSING)] == pytest.approx(0.90, abs=0.08)


def test_processing_implies_confirmed(history: pl.DataFrame) -> None:
    """An order is only processed after it has been confirmed."""
    processing = set(
        history.filter(pl.col("status") == str(OrderStatus.PROCESSING))["order_id"].to_list()
    )
    confirmed = set(
        history.filter(pl.col("status") == str(OrderStatus.CONFIRMED))["order_id"].to_list()
    )

    assert processing <= confirmed


def test_no_future_lifecycle_stage_is_generated(history: pl.DataFrame) -> None:
    """PACKED, SHIPPED and DELIVERED belong to later features."""
    assert set(history["status"].to_list()) <= {str(member) for member in ORDER_LIFECYCLE}


def test_a_zero_confirmation_rate_leaves_every_order_created(
    orders: pl.DataFrame,
) -> None:
    """Turning the lifecycle off still records the CREATED row."""
    config = OrderConfig(confirmed_rate=0.0, processing_rate=0.0)

    history = generate_order_status_history(config, orders, SEED)
    updated = apply_current_status(orders, history)

    assert history.height == orders.height
    assert set(history["status"].to_list()) == {str(OrderStatus.CREATED)}
    assert set(updated["current_status"].to_list()) == {str(OrderStatus.CREATED)}


def test_a_full_rate_advances_every_order(orders: pl.DataFrame) -> None:
    """With both rates at one, every order reaches PROCESSING."""
    config = OrderConfig(confirmed_rate=1.0, processing_rate=1.0)

    history = generate_order_status_history(config, orders, SEED)
    updated = apply_current_status(orders, history)

    assert history.height == orders.height * 3
    assert set(updated["current_status"].to_list()) == {str(OrderStatus.PROCESSING)}


# --------------------------------------------------------------------------
# Orchestration, batching and determinism
# --------------------------------------------------------------------------


def test_all_documented_datasets_are_generated(order_data: OrderData) -> None:
    """Every dataset named in the F006 output list is produced."""
    assert set(order_data.datasets) == EXPECTED_OUTPUTS


def test_datasets_are_emitted_in_dependency_order(order_data: OrderData) -> None:
    """Orders come first, so lines and history can reference them."""
    assert list(order_data.datasets) == [dataset.name for dataset in ORDER_DATASETS]


def test_no_dataset_is_empty(order_data: OrderData) -> None:
    """All three order datasets carry rows."""
    assert all(count > 0 for count in order_data.row_counts().values())


def test_generated_data_passes_validation(
    order_data: OrderData, order_upstream: dict[str, pl.DataFrame]
) -> None:
    """The bundle satisfies the F006 acceptance criteria."""
    assert validate_order_data({**order_upstream, **order_data.datasets}) == []


def test_batching_does_not_change_the_output(
    checkouts: pl.DataFrame, cart_items: pl.DataFrame
) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = OrderConfig(batch_size=7)
    large = OrderConfig(batch_size=1_000_000)

    small_orders = generate_orders(small, checkouts)
    large_orders = generate_orders(large, checkouts)

    assert small_orders.equals(large_orders)
    assert generate_order_lines(small, small_orders, cart_items).equals(
        generate_order_lines(large, large_orders, cart_items)
    )
    assert generate_order_status_history(small, small_orders, SEED).equals(
        generate_order_status_history(large, large_orders, SEED)
    )


def test_batches_are_bounded_by_the_configured_size(
    checkouts: pl.DataFrame,
) -> None:
    """No batch exceeds the configured size."""
    batches = list(iter_order_batches(OrderConfig(batch_size=40), checkouts))

    assert batches
    assert all(batch.height <= 40 for batch in batches)


def test_generation_is_deterministic(
    order_simulation_config: SimulationConfig, order_upstream: dict[str, pl.DataFrame]
) -> None:
    """The same configuration and seed reproduce identical datasets."""
    first = generate_order_data(order_simulation_config, order_upstream)
    second = generate_order_data(order_simulation_config, order_upstream)

    assert first.seed == second.seed
    for name, frame in first:
        assert frame.equals(second[name]), f"{name} differs between runs"


def test_a_different_seed_changes_the_lifecycle(
    order_simulation_config: SimulationConfig, order_upstream: dict[str, pl.DataFrame]
) -> None:
    """The seed drives how far each order progresses."""
    other = SimulationConfig(
        platform=PlatformConfig(seed=97_531),
        master_data=order_simulation_config.master_data,
        customers=order_simulation_config.customers,
        journey=order_simulation_config.journey,
        browsing=order_simulation_config.browsing,
        engagement=order_simulation_config.engagement,
        commerce=order_simulation_config.commerce,
        checkout=order_simulation_config.checkout,
        orders=order_simulation_config.orders,
    )

    baseline = generate_order_data(order_simulation_config, order_upstream)
    varied = generate_order_data(other, order_upstream)

    assert not baseline["order_status_history"].equals(varied["order_status_history"])


def test_orders_themselves_do_not_depend_on_the_seed(
    checkouts: pl.DataFrame, config: OrderConfig
) -> None:
    """The order document is fully derived, so no seed appears in it."""
    assert generate_orders(config, checkouts).equals(generate_orders(config, checkouts))


@pytest.mark.parametrize("missing", REQUIRED_ORDER_DATASETS)
def test_missing_upstream_data_is_reported(
    order_simulation_config: SimulationConfig,
    order_upstream: dict[str, pl.DataFrame],
    missing: str,
) -> None:
    """Each required upstream dataset is checked before generation starts."""
    available = {name: frame for name, frame in order_upstream.items() if name != missing}

    with pytest.raises(KeyError, match="Missing upstream data"):
        generate_order_data(order_simulation_config, available)


def test_missing_upstream_names_the_prerequisite_commands(
    order_simulation_config: SimulationConfig,
    order_upstream: dict[str, pl.DataFrame],
) -> None:
    """The error tells the user which commands to run first."""
    available = {name: frame for name, frame in order_upstream.items() if name != "checkout"}

    with pytest.raises(KeyError, match="generate commerce"):
        generate_order_data(order_simulation_config, available)


def test_no_successful_checkouts_produces_empty_frames(
    config: OrderConfig, checkouts: pl.DataFrame, cart_items: pl.DataFrame
) -> None:
    """A run where nothing succeeded yields empty, schema-shaped frames."""
    none_successful = checkouts.with_columns(
        pl.lit(str(CheckoutStatus.ABANDONED)).alias("checkout_status")
    )

    orders = generate_orders(config, none_successful)
    lines = generate_order_lines(config, orders, cart_items)
    history = generate_order_status_history(config, orders, SEED)

    assert orders.height == 0
    assert lines.height == 0
    assert history.height == 0
    assert "order_id" in orders.columns


def test_bundle_reports_row_counts(order_data: OrderData) -> None:
    """The bundle exposes counts for the CLI report."""
    assert order_data.total_rows() == sum(order_data.row_counts().values())


def test_unknown_dataset_access_raises(order_data: OrderData) -> None:
    """Requesting a dataset F006 does not produce fails clearly."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        order_data["payments"]


def test_orders_do_not_regenerate_upstream_data(
    order_data: OrderData, order_upstream: dict[str, pl.DataFrame]
) -> None:
    """F006 consumes earlier output; it emits none of those datasets."""
    assert set(order_data.datasets).isdisjoint(set(order_upstream))
