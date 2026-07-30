"""Validation rules for the F005 checkout dataset.

Referential integrity is delegated to
:func:`eds.core.validation.referential.validate_referential_integrity` with the
checkout declaration, which covers duplicate ``checkout_id`` values, the
one-checkout-per-cart rule, and invalid customer, cart, session, and address
references.

The rules here cover what a schema cannot express: that only checked-out carts
produced a checkout, that the money reconciles against the cart's own items,
and that the attempt's timestamps respect the journey's order.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.validation.issues import ValidationError, ValidationIssue
from eds.domains.retail.domain.commerce.enums import CartStatus, CheckoutStatus
from eds.domains.retail.domain.commerce.schema import CHECKOUT_DATASETS
from eds.domains.retail.validation.referential import validate_referential_integrity

__all__ = [
    "MONEY_TOLERANCE",
    "assert_valid_checkout_data",
    "validate_addresses_belong_to_the_customer",
    "validate_cart_eligibility",
    "validate_checkout_data",
    "validate_checkout_timeline",
    "validate_totals",
]

#: Money is compared to the nearest cent.
MONEY_TOLERANCE = 0.011


def _issue_if(
    frame: pl.DataFrame, dataset: str, rule: str, predicate: pl.Expr, message: str
) -> list[ValidationIssue]:
    """Return one issue when any row violates a rule.

    Args:
        frame: Frame to check.
        dataset: Dataset name for the issue.
        rule: Rule identifier.
        predicate: Expression that is true for violating rows.
        message: Description of what the rule requires.

    Returns:
        A single-item list when violations exist, otherwise an empty list.
    """
    count = frame.filter(predicate).height
    if count:
        return [ValidationIssue(dataset, rule, f"{count} row(s) violate: {message}")]
    return []


def validate_cart_eligibility(
    checkouts: pl.DataFrame, carts: pl.DataFrame
) -> list[ValidationIssue]:
    """Check only checked-out carts produced a checkout, and each did so once.

    Args:
        checkouts: The checkout dataset.
        carts: The F004 shopping carts dataset.

    Returns:
        Issues for a checkout on an ineligible cart, a checked-out cart with
        no checkout, or a cart with more than one.
    """
    issues: list[ValidationIssue] = []

    joined = checkouts.join(
        carts.select(
            "cart_id",
            "cart_status",
            pl.col("customer_id").alias("cart_customer_id"),
            pl.col("session_id").alias("cart_session_id"),
        ),
        on="cart_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "checkout",
        "invalid_cart_status",
        pl.col("cart_status") != str(CartStatus.CHECKED_OUT),
        "only a CHECKED_OUT cart produces a checkout",
    )
    issues += _issue_if(
        joined,
        "checkout",
        "cart_customer_mismatch",
        pl.col("customer_id") != pl.col("cart_customer_id"),
        "the checkout customer matches the cart's customer",
    )
    issues += _issue_if(
        joined,
        "checkout",
        "cart_session_mismatch",
        pl.col("session_id") != pl.col("cart_session_id"),
        "the checkout session matches the cart's session",
    )

    duplicates = checkouts.height - checkouts["cart_id"].n_unique()
    if duplicates:
        issues.append(
            ValidationIssue(
                "checkout",
                "multiple_checkouts_per_cart",
                f"{duplicates} cart(s) produced more than one checkout",
            )
        )

    eligible = set(
        carts.filter(pl.col("cart_status") == str(CartStatus.CHECKED_OUT))["cart_id"].to_list()
    )
    covered = set(checkouts["cart_id"].to_list())
    if missing := eligible - covered:
        issues.append(
            ValidationIssue(
                "checkout",
                "eligible_cart_without_checkout",
                f"{len(missing)} checked-out cart(s) produced no checkout",
            )
        )
    return issues


def validate_totals(checkouts: pl.DataFrame, cart_items: pl.DataFrame) -> list[ValidationIssue]:
    """Check the money reconciles against the cart's remaining items.

    Items the customer removed before checking out are excluded, matching the
    rule the generator applies: only what is still in the cart is paid for.

    Args:
        checkouts: The checkout dataset.
        cart_items: The F004 cart items dataset.

    Returns:
        Issues for a subtotal that disagrees with the cart, a total that does
        not equal the sum of its parts, or a negative amount.
    """
    issues: list[ValidationIssue] = []

    expected = (
        cart_items.filter(pl.col("removed_at").is_null())
        .with_columns((pl.col("quantity") * pl.col("unit_price")).alias("line_total"))
        .group_by("cart_id")
        .agg(pl.col("line_total").sum().alias("expected_subtotal"))
    )
    joined = checkouts.join(expected, on="cart_id", how="left").with_columns(
        pl.col("expected_subtotal").fill_null(0.0)
    )

    issues += _issue_if(
        joined,
        "checkout",
        "subtotal_mismatch",
        (pl.col("subtotal") - pl.col("expected_subtotal")).abs() > MONEY_TOLERANCE,
        "subtotal equals the sum of quantity times unit price",
    )
    issues += _issue_if(
        checkouts,
        "checkout",
        "total_mismatch",
        (
            pl.col("total_amount")
            - (
                pl.col("subtotal")
                + pl.col("shipping_cost")
                + pl.col("tax_amount")
                - pl.col("discount_amount")
            )
        ).abs()
        > MONEY_TOLERANCE,
        "total_amount equals subtotal plus shipping plus tax minus discount",
    )

    for column in ("subtotal", "shipping_cost", "tax_amount", "discount_amount", "total_amount"):
        issues += _issue_if(
            checkouts,
            "checkout",
            "negative_amount",
            pl.col(column) < 0,
            f"{column} >= 0",
        )
    return issues


def validate_checkout_timeline(
    checkouts: pl.DataFrame, carts: pl.DataFrame
) -> list[ValidationIssue]:
    """Check the attempt's timestamps respect the journey's order.

    Args:
        checkouts: The checkout dataset.
        carts: The F004 shopping carts dataset.

    Returns:
        Issues for a checkout that completed before it started, one that began
        before its cart stopped changing, or a completion flag that disagrees
        with the status.
    """
    issues: list[ValidationIssue] = []

    populated = checkouts.filter(pl.col("completed_at").is_not_null())
    issues += _issue_if(
        populated,
        "checkout",
        "completed_before_started",
        pl.col("completed_at") <= pl.col("started_at"),
        "completed_at is after started_at",
    )
    issues += _issue_if(
        checkouts,
        "checkout",
        "abandoned_with_completion",
        (pl.col("checkout_status") == str(CheckoutStatus.ABANDONED))
        & pl.col("completed_at").is_not_null(),
        "an abandoned checkout has no completed_at",
    )
    issues += _issue_if(
        checkouts,
        "checkout",
        "finished_without_completion",
        (pl.col("checkout_status") != str(CheckoutStatus.ABANDONED))
        & pl.col("completed_at").is_null(),
        "a successful or failed checkout has a completed_at",
    )

    after_cart = checkouts.join(
        carts.select("cart_id", pl.col("updated_at").alias("cart_updated_at")),
        on="cart_id",
        how="inner",
    )
    issues += _issue_if(
        after_cart,
        "checkout",
        "started_before_cart",
        pl.col("started_at") <= pl.col("cart_updated_at"),
        "the checkout starts after the cart was last changed",
    )
    return issues


def validate_addresses_belong_to_the_customer(
    checkouts: pl.DataFrame, addresses: pl.DataFrame
) -> list[ValidationIssue]:
    """Check both addresses belong to the customer checking out.

    Args:
        checkouts: The checkout dataset.
        addresses: The F002 customer addresses dataset.

    Returns:
        Issues where a shipping or billing address belongs to someone else.
    """
    owners = addresses.select("address_id", pl.col("customer_id").alias("address_customer_id"))
    issues: list[ValidationIssue] = []

    shipping = checkouts.join(
        owners.rename({"address_id": "shipping_address_id"}),
        on="shipping_address_id",
        how="inner",
    )
    issues += _issue_if(
        shipping,
        "checkout",
        "shipping_address_not_owned",
        pl.col("customer_id") != pl.col("address_customer_id"),
        "the shipping address belongs to the checking-out customer",
    )

    billing = checkouts.join(
        owners.rename({"address_id": "billing_address_id"}),
        on="billing_address_id",
        how="inner",
    )
    issues += _issue_if(
        billing,
        "checkout",
        "billing_address_not_owned",
        pl.col("customer_id") != pl.col("address_customer_id"),
        "the billing address belongs to the checking-out customer",
    )
    return issues


def validate_checkout_data(
    datasets: Mapping[str, pl.DataFrame],
) -> list[ValidationIssue]:
    """Validate schema, referential integrity, and checkout business rules.

    Args:
        datasets: The checkout dataset plus the upstream datasets it
            references, keyed by name.

    Returns:
        Every issue found. An empty list means the data satisfies the F005
        acceptance criteria.
    """
    issues = validate_referential_integrity(datasets, CHECKOUT_DATASETS)

    checkouts = datasets.get("checkout")
    if checkouts is None:
        return issues

    carts = datasets.get("shopping_carts")
    cart_items = datasets.get("cart_items")
    addresses = datasets.get("customer_addresses")

    if carts is not None:
        issues.extend(validate_cart_eligibility(checkouts, carts))
        issues.extend(validate_checkout_timeline(checkouts, carts))
    if cart_items is not None:
        issues.extend(validate_totals(checkouts, cart_items))
    if addresses is not None:
        issues.extend(validate_addresses_belong_to_the_customer(checkouts, addresses))
    return issues


def assert_valid_checkout_data(datasets: Mapping[str, pl.DataFrame]) -> None:
    """Validate the checkout dataset and raise if anything is wrong.

    Args:
        datasets: The checkout dataset plus the upstream data it references.

    Raises:
        ValidationError: If any validation issue is found.
    """
    issues = validate_checkout_data(datasets)
    if issues:
        raise ValidationError(issues)
