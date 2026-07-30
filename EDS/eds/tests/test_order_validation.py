"""Tests for order validation.

Every failure path corrupts a valid bundle and asserts the specific rule
fires, covering each check the F006 specification lists.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from eds.domain.commerce.enums import CheckoutStatus, OrderStatus
from eds.generators.commerce.orders import OrderData
from eds.validation.issues import ValidationError, ValidationIssue
from eds.validation.order_validation import (
    assert_valid_order_data,
    validate_checkout_eligibility,
    validate_financial_copy,
    validate_line_reconciliation,
    validate_order_data,
    validate_order_numbers,
    validate_order_timeline,
    validate_status_history,
)


@pytest.fixture
def datasets(
    order_data: OrderData, order_upstream: dict[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Return a mutable bundle of the order datasets plus upstream data."""
    return {**order_upstream, **order_data.datasets}


def rules(issues: list[ValidationIssue]) -> set[str]:
    """Return the rule identifiers present in a list of issues.

    Args:
        issues: Issues to summarise.

    Returns:
        The set of rule names.
    """
    return {issue.rule for issue in issues}


def test_clean_data_produces_no_issues(datasets: dict[str, pl.DataFrame]) -> None:
    """A freshly generated bundle validates cleanly."""
    assert validate_order_data(datasets) == []


def test_assert_valid_passes_on_clean_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper does not raise for valid data."""
    assert_valid_order_data(datasets)


# --------------------------------------------------------------------------
# Duplicates and references
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dataset", "column"),
    [
        ("orders", "order_id"),
        ("order_lines", "order_line_id"),
        ("order_status_history", "history_id"),
    ],
)
def test_duplicate_primary_keys_are_detected(
    datasets: dict[str, pl.DataFrame], dataset: str, column: str
) -> None:
    """Each dataset's identifier is a primary key."""
    datasets[dataset] = datasets[dataset].with_columns(pl.lit(1).cast(pl.Int64).alias(column))

    assert "duplicate_primary_key" in rules(validate_order_data(datasets))


def test_duplicate_order_number_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The business identifier is never reused."""
    datasets["orders"] = datasets["orders"].with_columns(
        pl.lit("ORD-20250101-000001").alias("order_number")
    )

    assert "duplicate_unique_column" in rules(validate_order_data(datasets))


@pytest.mark.parametrize(
    ("dataset", "column", "target"),
    [
        ("orders", "checkout_id", "checkout.checkout_id"),
        ("orders", "cart_id", "shopping_carts.cart_id"),
        ("orders", "customer_id", "customers.customer_id"),
        ("orders", "session_id", "sessions.session_id"),
        ("orders", "shipping_address_id", "customer_addresses.address_id"),
        ("orders", "billing_address_id", "customer_addresses.address_id"),
        ("order_lines", "order_id", "orders.order_id"),
        ("order_lines", "product_id", "products.product_id"),
        ("order_status_history", "order_id", "orders.order_id"),
    ],
)
def test_invalid_references_are_detected(
    datasets: dict[str, pl.DataFrame], dataset: str, column: str, target: str
) -> None:
    """Every declared foreign key is checked against its target."""
    datasets[dataset] = datasets[dataset].with_columns(pl.lit(999_999).cast(pl.Int64).alias(column))

    issues = validate_order_data(datasets)

    assert "orphan_reference" in rules(issues)
    assert any(target in issue.detail for issue in issues)


# --------------------------------------------------------------------------
# Checkout eligibility
# --------------------------------------------------------------------------


def test_an_order_from_a_failed_checkout_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Only SUCCESS checkouts produce orders."""
    checkouts = datasets["checkout"].with_columns(
        pl.lit(str(CheckoutStatus.FAILED)).alias("checkout_status")
    )

    issues = validate_checkout_eligibility(datasets["orders"], checkouts)

    assert "invalid_checkout_status" in rules(issues)


def test_a_successful_checkout_without_an_order_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Every successful checkout must produce an order."""
    issues = validate_checkout_eligibility(datasets["orders"].head(5), datasets["checkout"])

    assert "successful_checkout_without_order" in rules(issues)


def test_multiple_orders_per_checkout_are_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A checkout may produce only one order."""
    datasets["orders"] = datasets["orders"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("checkout_id")
    )

    issues = validate_order_data(datasets)

    assert "duplicate_unique_column" in rules(issues)
    assert "multiple_orders_per_checkout" in rules(issues)


def test_a_field_disagreeing_with_the_checkout_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Cart, customer, session and addresses come from the checkout."""
    orders = datasets["orders"].with_columns((pl.col("cart_id") + 1).alias("cart_id"))

    issues = validate_checkout_eligibility(orders, datasets["checkout"])

    assert "checkout_field_mismatch" in rules(issues)


# --------------------------------------------------------------------------
# Financial copy and reconciliation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column",
    ["subtotal", "shipping_cost", "tax_amount", "discount_amount", "total_amount"],
)
def test_a_recalculated_financial_value_is_detected(
    datasets: dict[str, pl.DataFrame], column: str
) -> None:
    """ADR-007: money is copied, so even a cent of drift is a defect."""
    orders = datasets["orders"].with_columns((pl.col(column) + 0.01).alias(column))

    assert "financial_value_not_copied" in rules(
        validate_financial_copy(orders, datasets["checkout"])
    )


def test_line_total_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A line total must equal quantity times unit price."""
    lines = datasets["order_lines"].with_columns((pl.col("line_total") + 5.0).alias("line_total"))

    issues = validate_line_reconciliation(datasets["orders"], lines, datasets["cart_items"])

    assert "line_total_mismatch" in rules(issues)


def test_subtotal_not_matching_the_lines_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The lines must add up to the order's subtotal."""
    orders = datasets["orders"].with_columns((pl.col("subtotal") + 10.0).alias("subtotal"))

    issues = validate_line_reconciliation(orders, datasets["order_lines"], datasets["cart_items"])

    assert "subtotal_mismatch" in rules(issues)


def test_a_line_from_a_removed_cart_item_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Ordering something the customer took out of the cart is a defect."""
    cart_items = datasets["cart_items"].with_columns(pl.col("added_at").alias("removed_at"))

    issues = validate_line_reconciliation(datasets["orders"], datasets["order_lines"], cart_items)

    assert "removed_cart_item_ordered" in rules(issues)
    assert "line_not_from_active_cart_item" in rules(issues)


def test_a_non_positive_quantity_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A line cannot order zero or fewer units."""
    lines = datasets["order_lines"].with_columns(pl.lit(0).cast(pl.Int64).alias("quantity"))

    issues = validate_line_reconciliation(datasets["orders"], lines, datasets["cart_items"])

    assert "non_positive_quantity" in rules(issues)


# --------------------------------------------------------------------------
# Order numbers
# --------------------------------------------------------------------------


def test_a_malformed_order_number_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The number must read as PREFIX-YYYYMMDD-NNNNNN."""
    orders = datasets["orders"].with_columns(pl.lit("not-a-number").alias("order_number"))

    assert "malformed_order_number" in rules(validate_order_numbers(orders))


def test_an_order_number_with_the_wrong_date_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The embedded date must be the order's own date."""
    orders = datasets["orders"].with_columns(pl.lit("ORD-19990101-000001").alias("order_number"))

    assert "order_number_date_mismatch" in rules(validate_order_numbers(orders))


def test_a_gapped_order_number_sequence_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The daily sequence must run 1..n without gaps."""
    orders = datasets["orders"].with_columns(
        pl.concat_str(
            [
                pl.lit("ORD"),
                pl.col("order_date").dt.strftime("%Y%m%d"),
                pl.lit("000009"),
            ],
            separator="-",
        ).alias("order_number")
    )

    assert "order_number_not_sequential" in rules(validate_order_numbers(orders))


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


def test_an_order_before_its_checkout_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """An order cannot predate the checkout that produced it."""
    orders = datasets["orders"].with_columns(pl.lit(datetime(1999, 1, 1)).alias("created_at"))

    issues = validate_order_timeline(orders, datasets["checkout"])

    assert "order_before_checkout" in rules(issues)


def test_an_order_date_disagreeing_with_created_at_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The two must always agree."""
    orders = datasets["orders"].with_columns(pl.col("order_date") - pl.duration(days=1))

    issues = validate_order_timeline(orders, datasets["checkout"])

    assert "order_date_mismatch" in rules(issues)


# --------------------------------------------------------------------------
# Status history
# --------------------------------------------------------------------------


def test_an_unknown_status_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A stage from a later feature is not silently accepted."""
    history = datasets["order_status_history"].with_columns(pl.lit("DELIVERED").alias("status"))

    assert "unknown_status" in rules(validate_status_history(datasets["orders"], history))


def test_an_invalid_sequence_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Sequences must start at one."""
    history = datasets["order_status_history"].with_columns(
        pl.lit(0).cast(pl.Int64).alias("sequence")
    )

    assert "invalid_sequence" in rules(validate_status_history(datasets["orders"], history))


def test_a_gapped_sequence_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A sequence with gaps is reported even when every value is positive."""
    history = datasets["order_status_history"].with_columns(
        (pl.col("sequence") * 2).alias("sequence")
    )

    assert "invalid_sequence" in rules(validate_status_history(datasets["orders"], history))


def test_history_out_of_time_order_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Time must move forwards with the sequence."""
    history = datasets["order_status_history"].with_columns(
        pl.lit(datetime(2000, 1, 1)).alias("status_timestamp")
    )

    issues = validate_status_history(datasets["orders"], history)

    assert "history_out_of_order" in rules(issues)


def test_a_history_not_starting_at_created_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Every lifecycle begins at CREATED."""
    history = datasets["order_status_history"].with_columns(
        pl.when(pl.col("sequence") == 1)
        .then(pl.lit(str(OrderStatus.CONFIRMED)))
        .otherwise(pl.col("status"))
        .alias("status")
    )

    issues = validate_status_history(datasets["orders"], history)

    assert "lifecycle_does_not_start_at_created" in rules(issues)


def test_an_order_without_history_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Every order must have at least a CREATED row."""
    history = datasets["order_status_history"].filter(pl.col("order_id") != 1)

    issues = validate_status_history(datasets["orders"], history)

    assert "order_without_history" in rules(issues)


def test_a_current_status_disagreeing_with_history_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """ADR-012: current_status is derived from the history."""
    orders = datasets["orders"].with_columns(
        pl.lit(str(OrderStatus.CREATED)).alias("current_status")
    )

    issues = validate_status_history(orders, datasets["order_status_history"])

    assert "current_status_mismatch" in rules(issues)


def test_history_before_its_order_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The first status cannot predate the order it belongs to."""
    history = datasets["order_status_history"].with_columns(
        pl.when(pl.col("sequence") == 1)
        .then(pl.lit(datetime(1999, 1, 1)))
        .otherwise(pl.col("status_timestamp"))
        .alias("status_timestamp")
    )

    issues = validate_status_history(datasets["orders"], history)

    assert "history_before_order" in rules(issues)


def test_an_empty_history_with_orders_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """An entirely missing history is reported rather than passing."""
    empty = datasets["order_status_history"].clear()

    issues = validate_status_history(datasets["orders"], empty)

    assert "order_without_history" in rules(issues)


# --------------------------------------------------------------------------
# Bundle-level
# --------------------------------------------------------------------------


def test_missing_dataset_is_reported(datasets: dict[str, pl.DataFrame]) -> None:
    """A dataset that was never generated is an integrity failure."""
    del datasets["order_lines"]

    assert "missing_dataset" in rules(validate_order_data(datasets))


def test_dtype_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A wrong dtype would corrupt the exported Parquet schema."""
    datasets["orders"] = datasets["orders"].with_columns(pl.col("order_id").cast(pl.Int32))

    assert "dtype_mismatch" in rules(validate_order_data(datasets))


def test_assert_valid_raises_on_corrupt_data(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The assertion helper raises when the data is broken."""
    datasets["orders"] = datasets["orders"].with_columns(
        (pl.col("total_amount") + 100.0).alias("total_amount")
    )

    with pytest.raises(ValidationError, match="financial_value_not_copied"):
        assert_valid_order_data(datasets)


def test_earlier_features_still_validate(
    order_upstream: dict[str, pl.DataFrame],
) -> None:
    """Adding order declarations did not disturb earlier validators."""
    from eds.validation.checkout_validation import validate_checkout_data
    from eds.validation.commerce_validation import validate_commerce_data
    from eds.validation.master_data import validate_master_data

    assert validate_master_data(order_upstream) == []
    assert validate_commerce_data(order_upstream) == []
    assert validate_checkout_data(order_upstream) == []
