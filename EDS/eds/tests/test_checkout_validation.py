"""Tests for checkout validation.

Every failure path corrupts a valid bundle and asserts the specific rule
fires, covering each check the F005 specification lists.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from eds.domain.commerce.enums import CartStatus, CheckoutStatus
from eds.generators.commerce.checkout_generator import CheckoutData
from eds.validation.checkout_validation import (
    assert_valid_checkout_data,
    validate_addresses_belong_to_the_customer,
    validate_cart_eligibility,
    validate_checkout_data,
    validate_checkout_timeline,
    validate_totals,
)
from eds.validation.issues import ValidationError, ValidationIssue


@pytest.fixture
def datasets(
    checkout_data: CheckoutData, checkout_upstream: dict[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Return a mutable bundle of the checkout dataset plus upstream data."""
    return {**checkout_upstream, **checkout_data.datasets}


def rules(issues: list[ValidationIssue]) -> set[str]:
    """Return the rule identifiers present in a list of issues.

    Args:
        issues: Issues to summarise.

    Returns:
        The set of rule names.
    """
    return {issue.rule for issue in issues}


def test_clean_data_produces_no_issues(datasets: dict[str, pl.DataFrame]) -> None:
    """A freshly generated dataset validates cleanly."""
    assert validate_checkout_data(datasets) == []


def test_assert_valid_passes_on_clean_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper does not raise for valid data."""
    assert_valid_checkout_data(datasets)


def test_duplicate_checkout_ids_are_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The checkout id is the primary key."""
    datasets["checkout"] = datasets["checkout"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("checkout_id")
    )

    assert "duplicate_primary_key" in rules(validate_checkout_data(datasets))


@pytest.mark.parametrize(
    ("column", "target"),
    [
        ("cart_id", "shopping_carts.cart_id"),
        ("customer_id", "customers.customer_id"),
        ("session_id", "sessions.session_id"),
        ("shipping_address_id", "customer_addresses.address_id"),
        ("billing_address_id", "customer_addresses.address_id"),
    ],
)
def test_invalid_references_are_detected(
    datasets: dict[str, pl.DataFrame], column: str, target: str
) -> None:
    """Every declared foreign key is checked against its target."""
    datasets["checkout"] = datasets["checkout"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias(column)
    )

    issues = validate_checkout_data(datasets)

    assert "orphan_reference" in rules(issues)
    assert any(target in issue.detail for issue in issues)


def test_multiple_checkouts_per_cart_are_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A cart may produce only one checkout."""
    datasets["checkout"] = datasets["checkout"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("cart_id")
    )

    issues = validate_checkout_data(datasets)

    assert "duplicate_unique_column" in rules(issues)
    assert "multiple_checkouts_per_cart" in rules(issues)


def test_invalid_cart_status_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A checkout on an ineligible cart is a defect."""
    carts = datasets["shopping_carts"].with_columns(
        pl.lit(str(CartStatus.ABANDONED)).alias("cart_status")
    )

    issues = validate_cart_eligibility(datasets["checkout"], carts)

    assert "invalid_cart_status" in rules(issues)


def test_eligible_cart_without_a_checkout_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Every checked-out cart must produce a checkout."""
    checkouts = datasets["checkout"].head(5)

    issues = validate_cart_eligibility(checkouts, datasets["shopping_carts"])

    assert "eligible_cart_without_checkout" in rules(issues)


def test_cart_customer_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The checkout customer must be the cart's customer."""
    checkouts = datasets["checkout"].with_columns((pl.col("customer_id") + 1).alias("customer_id"))

    issues = validate_cart_eligibility(checkouts, datasets["shopping_carts"])

    assert "cart_customer_mismatch" in rules(issues)


def test_cart_session_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The checkout session must be the cart's session."""
    checkouts = datasets["checkout"].with_columns((pl.col("session_id") + 1).alias("session_id"))

    issues = validate_cart_eligibility(checkouts, datasets["shopping_carts"])

    assert "cart_session_mismatch" in rules(issues)


def test_subtotal_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The subtotal must equal the cart's item value."""
    checkouts = datasets["checkout"].with_columns((pl.col("subtotal") + 10.0).alias("subtotal"))

    assert "subtotal_mismatch" in rules(validate_totals(checkouts, datasets["cart_items"]))


def test_a_subtotal_including_removed_items_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Charging for items the customer took back out is a defect.

    This is the rule the F005 correctness fix introduced: the validator now
    recomputes the subtotal over remaining items only, so a checkout priced
    against everything ever added no longer reconciles.
    """
    items = datasets["cart_items"]
    everything = (
        items.with_columns((pl.col("quantity") * pl.col("unit_price")).alias("line"))
        .group_by("cart_id")
        .agg(pl.col("line").sum().alias("all_items"))
    )
    overcharged = (
        datasets["checkout"]
        .join(everything, on="cart_id", how="inner")
        .with_columns(pl.col("all_items").round(2).alias("subtotal"))
        .drop("all_items")
    )

    assert "subtotal_mismatch" in rules(validate_totals(overcharged, items))


def test_removed_items_do_not_break_a_clean_bundle(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The generated data already prices only what remains in the cart."""
    removed = datasets["cart_items"].filter(pl.col("removed_at").is_not_null())

    assert removed.height > 0, "the sample should contain removed items"
    assert validate_totals(datasets["checkout"], datasets["cart_items"]) == []


def test_total_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The total must equal the sum of its parts."""
    checkouts = datasets["checkout"].with_columns(
        (pl.col("total_amount") + 5.0).alias("total_amount")
    )

    assert "total_mismatch" in rules(validate_totals(checkouts, datasets["cart_items"]))


def test_negative_amount_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Money never goes below zero."""
    checkouts = datasets["checkout"].with_columns(pl.lit(-1.0).alias("shipping_cost"))

    assert "negative_amount" in rules(validate_totals(checkouts, datasets["cart_items"]))


def test_completed_before_started_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A checkout cannot finish before it begins."""
    checkouts = datasets["checkout"].with_columns(
        pl.when(pl.col("completed_at").is_not_null())
        .then(pl.lit(datetime(1999, 1, 1)))
        .otherwise(pl.col("completed_at"))
        .alias("completed_at")
    )

    issues = validate_checkout_timeline(checkouts, datasets["shopping_carts"])

    assert "completed_before_started" in rules(issues)


def test_abandoned_with_a_completion_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """An abandoned checkout has no completion time."""
    checkouts = datasets["checkout"].with_columns(
        pl.lit(str(CheckoutStatus.ABANDONED)).alias("checkout_status")
    )

    issues = validate_checkout_timeline(checkouts, datasets["shopping_carts"])

    assert "abandoned_with_completion" in rules(issues)


def test_finished_without_a_completion_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A successful or failed checkout records when it finished."""
    checkouts = datasets["checkout"].with_columns(
        pl.lit(str(CheckoutStatus.SUCCESS)).alias("checkout_status")
    )

    issues = validate_checkout_timeline(checkouts, datasets["shopping_carts"])

    assert "finished_without_completion" in rules(issues)


def test_started_before_the_cart_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A checkout cannot begin before the cart stopped changing."""
    checkouts = datasets["checkout"].with_columns(pl.lit(datetime(1999, 1, 1)).alias("started_at"))

    issues = validate_checkout_timeline(checkouts, datasets["shopping_carts"])

    assert "started_before_cart" in rules(issues)


def test_shipping_address_not_owned_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The shipping address must belong to the checking-out customer."""
    checkouts = datasets["checkout"].with_columns((pl.col("customer_id") + 1).alias("customer_id"))

    issues = validate_addresses_belong_to_the_customer(checkouts, datasets["customer_addresses"])

    assert "shipping_address_not_owned" in rules(issues)


def test_billing_address_not_owned_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The billing address must belong to the checking-out customer too."""
    other = datasets["customer_addresses"].with_columns(
        (pl.col("customer_id") + 1).alias("customer_id")
    )

    issues = validate_addresses_belong_to_the_customer(datasets["checkout"], other)

    assert "billing_address_not_owned" in rules(issues)


def test_missing_dataset_is_reported(datasets: dict[str, pl.DataFrame]) -> None:
    """A dataset that was never generated is an integrity failure."""
    del datasets["checkout"]

    assert "missing_dataset" in rules(validate_checkout_data(datasets))


def test_dtype_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A wrong dtype would corrupt the exported Parquet schema."""
    datasets["checkout"] = datasets["checkout"].with_columns(pl.col("checkout_id").cast(pl.Int32))

    assert "dtype_mismatch" in rules(validate_checkout_data(datasets))


def test_assert_valid_raises_on_corrupt_data(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The assertion helper raises when the data is broken."""
    datasets["checkout"] = datasets["checkout"].with_columns(
        (pl.col("total_amount") + 100.0).alias("total_amount")
    )

    with pytest.raises(ValidationError, match="total_mismatch"):
        assert_valid_checkout_data(datasets)


def test_earlier_features_still_validate(
    checkout_upstream: dict[str, pl.DataFrame],
) -> None:
    """Adding the checkout declaration did not disturb earlier validators."""
    from eds.validation.commerce_validation import validate_commerce_data
    from eds.validation.master_data import validate_master_data

    assert validate_master_data(checkout_upstream) == []
    assert validate_commerce_data(checkout_upstream) == []
