"""Validation rules for the F006 order datasets.

Referential integrity is delegated to
:func:`eds.core.validation.referential.validate_referential_integrity` with the
order declarations, which covers duplicate ``order_id``, ``order_number``,
``order_line_id`` and ``history_id`` values, the one-order-per-checkout rule,
and invalid checkout, cart, customer, session, address, product and order
references.

The rules here cover what a schema cannot express: that orders came only from
successful checkouts, that the money was copied rather than recomputed, that
the lines reconcile against it, and that the status history is a well-formed
lifecycle ending at the order's current status.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import polars as pl

from eds.core.validation.issues import ValidationError, ValidationIssue
from eds.domains.retail.domain.commerce.enums import ORDER_LIFECYCLE, CheckoutStatus, OrderStatus
from eds.domains.retail.domain.commerce.schema import ORDER_DATASETS
from eds.domains.retail.validation.referential import validate_referential_integrity

__all__ = [
    "MONEY_TOLERANCE",
    "ORDER_NUMBER_PATTERN",
    "assert_valid_order_data",
    "validate_checkout_eligibility",
    "validate_financial_copy",
    "validate_line_reconciliation",
    "validate_order_numbers",
    "validate_order_timeline",
    "validate_status_history",
]

#: Money is compared to the nearest cent.
MONEY_TOLERANCE: Final[float] = 0.011

#: ``ORD-YYYYMMDD-000001`` and anything else with the same shape.
ORDER_NUMBER_PATTERN: Final[str] = r"^[A-Z0-9]{1,8}-\d{8}-\d{6}$"

_FINANCIAL_COLUMNS: Final[tuple[str, ...]] = (
    "subtotal",
    "shipping_cost",
    "tax_amount",
    "discount_amount",
    "total_amount",
)


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


def validate_checkout_eligibility(
    orders: pl.DataFrame, checkouts: pl.DataFrame
) -> list[ValidationIssue]:
    """Check orders came only from successful checkouts, one each.

    Args:
        orders: The orders dataset.
        checkouts: The F005 checkout dataset.

    Returns:
        Issues for an order on a failed or abandoned checkout, a successful
        checkout with no order, a checkout with more than one, or an order
        whose cart, customer, session or addresses disagree with its checkout.
    """
    issues: list[ValidationIssue] = []

    joined = orders.join(
        checkouts.select(
            "checkout_id",
            "checkout_status",
            pl.col("cart_id").alias("checkout_cart_id"),
            pl.col("customer_id").alias("checkout_customer_id"),
            pl.col("session_id").alias("checkout_session_id"),
            pl.col("shipping_address_id").alias("checkout_shipping_address_id"),
            pl.col("billing_address_id").alias("checkout_billing_address_id"),
        ),
        on="checkout_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "orders",
        "invalid_checkout_status",
        pl.col("checkout_status") != str(CheckoutStatus.SUCCESS),
        "only a SUCCESS checkout produces an order",
    )
    for column in (
        "cart_id",
        "customer_id",
        "session_id",
        "shipping_address_id",
        "billing_address_id",
    ):
        issues += _issue_if(
            joined,
            "orders",
            "checkout_field_mismatch",
            pl.col(column) != pl.col(f"checkout_{column}"),
            f"{column} matches the checkout it came from",
        )

    duplicates = orders.height - orders["checkout_id"].n_unique()
    if duplicates:
        issues.append(
            ValidationIssue(
                "orders",
                "multiple_orders_per_checkout",
                f"{duplicates} checkout(s) produced more than one order",
            )
        )

    eligible = set(
        checkouts.filter(pl.col("checkout_status") == str(CheckoutStatus.SUCCESS))[
            "checkout_id"
        ].to_list()
    )
    covered = set(orders["checkout_id"].to_list())
    if missing := eligible - covered:
        issues.append(
            ValidationIssue(
                "orders",
                "successful_checkout_without_order",
                f"{len(missing)} successful checkout(s) produced no order",
            )
        )
    return issues


def validate_financial_copy(orders: pl.DataFrame, checkouts: pl.DataFrame) -> list[ValidationIssue]:
    """Check every financial value was copied from the checkout.

    ADR-007 makes the checkout the single source of financial truth, so these
    are compared for exact equality rather than within a tolerance: a value
    that was recomputed rather than copied would rarely land on the same cent.

    Args:
        orders: The orders dataset.
        checkouts: The F005 checkout dataset.

    Returns:
        One issue per financial column that disagrees.
    """
    joined = orders.join(
        checkouts.select(
            "checkout_id",
            *[pl.col(column).alias(f"checkout_{column}") for column in _FINANCIAL_COLUMNS],
        ),
        on="checkout_id",
        how="inner",
    )

    issues: list[ValidationIssue] = []
    for column in _FINANCIAL_COLUMNS:
        issues += _issue_if(
            joined,
            "orders",
            "financial_value_not_copied",
            pl.col(column) != pl.col(f"checkout_{column}"),
            f"{column} is copied verbatim from the checkout",
        )
    return issues


def validate_line_reconciliation(
    orders: pl.DataFrame, order_lines: pl.DataFrame, cart_items: pl.DataFrame
) -> list[ValidationIssue]:
    """Check the lines add up and came from the right cart items.

    Args:
        orders: The orders dataset.
        order_lines: The order lines dataset.
        cart_items: The F004 cart items dataset.

    Returns:
        Issues for a line total that is not quantity times price, a set of
        lines that does not sum to the order's subtotal, a non-positive
        quantity, or a line drawn from a removed cart item.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        order_lines,
        "order_lines",
        "line_total_mismatch",
        (pl.col("line_total") - pl.col("quantity") * pl.col("unit_price")).abs() > MONEY_TOLERANCE,
        "line_total equals quantity times unit_price",
    )
    issues += _issue_if(
        order_lines,
        "order_lines",
        "non_positive_quantity",
        pl.col("quantity") <= 0,
        "quantity > 0",
    )
    issues += _issue_if(
        order_lines,
        "order_lines",
        "negative_unit_price",
        pl.col("unit_price") < 0,
        "unit_price >= 0",
    )

    summed = order_lines.group_by("order_id").agg(pl.col("line_total").sum().alias("lines_total"))
    reconciled = orders.join(summed, on="order_id", how="left").with_columns(
        pl.col("lines_total").fill_null(0.0)
    )
    issues += _issue_if(
        reconciled,
        "orders",
        "subtotal_mismatch",
        (pl.col("subtotal") - pl.col("lines_total")).abs() > MONEY_TOLERANCE,
        "subtotal equals the sum of its order lines",
    )

    # Every line must correspond to an item still in the order's cart.
    active = cart_items.filter(pl.col("removed_at").is_null()).select(
        "cart_id", "product_id", "quantity", "unit_price"
    )
    with_cart = order_lines.join(orders.select("order_id", "cart_id"), on="order_id", how="inner")
    matched = with_cart.join(
        active.with_columns(pl.lit(True).alias("in_cart")),
        on=["cart_id", "product_id", "quantity", "unit_price"],
        how="left",
    )
    issues += _issue_if(
        matched,
        "order_lines",
        "line_not_from_active_cart_item",
        pl.col("in_cart").is_null(),
        "the line matches an active cart item of the order's cart",
    )

    removed = cart_items.filter(pl.col("removed_at").is_not_null()).select("cart_id", "product_id")
    leaked = with_cart.join(
        removed.with_columns(pl.lit(True).alias("was_removed")),
        on=["cart_id", "product_id"],
        how="left",
    )
    issues += _issue_if(
        leaked,
        "order_lines",
        "removed_cart_item_ordered",
        pl.col("was_removed").is_not_null(),
        "a removed cart item never becomes an order line",
    )
    return issues


def validate_order_numbers(orders: pl.DataFrame) -> list[ValidationIssue]:
    """Check the business order number is well formed and consistent.

    Args:
        orders: The orders dataset.

    Returns:
        Issues for a malformed number, or one whose embedded date disagrees
        with the order's own date.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        orders,
        "orders",
        "malformed_order_number",
        ~pl.col("order_number").str.contains(ORDER_NUMBER_PATTERN),
        "order_number matches PREFIX-YYYYMMDD-NNNNNN",
    )

    # The remaining checks read the number apart, so they only run on the
    # rows that are shaped like one. A malformed number has already been
    # reported above; parsing it here would raise rather than add an issue.
    well_formed = orders.filter(pl.col("order_number").str.contains(ORDER_NUMBER_PATTERN))
    if well_formed.is_empty():
        return issues

    issues += _issue_if(
        well_formed,
        "orders",
        "order_number_date_mismatch",
        pl.col("order_number").str.slice(-15, 8) != pl.col("order_date").dt.strftime("%Y%m%d"),
        "the date inside order_number equals order_date",
    )

    numbered = well_formed.group_by("order_date").agg(
        pl.col("order_number").str.slice(-6).cast(pl.Int64).min().alias("lowest"),
        pl.col("order_number").str.slice(-6).cast(pl.Int64).max().alias("highest"),
        pl.len().alias("total"),
    )
    broken = numbered.filter((pl.col("lowest") != 1) | (pl.col("highest") != pl.col("total")))
    if not broken.is_empty():
        issues.append(
            ValidationIssue(
                "orders",
                "order_number_not_sequential",
                f"{broken.height} date(s) are not numbered 1..n without gaps",
            )
        )
    return issues


def validate_order_timeline(orders: pl.DataFrame, checkouts: pl.DataFrame) -> list[ValidationIssue]:
    """Check an order was created after the checkout that produced it.

    Args:
        orders: The orders dataset.
        checkouts: The F005 checkout dataset.

    Returns:
        Issues for an order predating its checkout's completion, or an
        ``order_date`` that disagrees with ``created_at``.
    """
    issues: list[ValidationIssue] = []

    joined = orders.join(
        checkouts.select("checkout_id", pl.col("completed_at").alias("checkout_completed_at")),
        on="checkout_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "orders",
        "order_before_checkout",
        pl.col("created_at") <= pl.col("checkout_completed_at"),
        "the order is created after its checkout completed",
    )
    issues += _issue_if(
        orders,
        "orders",
        "order_date_mismatch",
        pl.col("order_date") != pl.col("created_at").dt.date(),
        "order_date is the date of created_at",
    )
    return issues


def validate_status_history(
    orders: pl.DataFrame, status_history: pl.DataFrame
) -> list[ValidationIssue]:
    """Check the status history is a well-formed lifecycle.

    Args:
        orders: The orders dataset.
        status_history: The order status history dataset.

    Returns:
        Issues for an unknown status, a sequence that is not numbered from one
        without gaps, timestamps that move backwards, a history that does not
        follow the lifecycle order, an order with no history, or a
        ``current_status`` that disagrees with the latest row.
    """
    issues: list[ValidationIssue] = []
    known = [str(member) for member in ORDER_LIFECYCLE]

    issues += _issue_if(
        status_history,
        "order_status_history",
        "unknown_status",
        ~pl.col("status").is_in(known),
        f"status is one of {known}",
    )
    issues += _issue_if(
        status_history,
        "order_status_history",
        "invalid_sequence",
        pl.col("sequence") < 1,
        "sequence >= 1",
    )

    if status_history.is_empty():
        if not orders.is_empty():
            issues.append(
                ValidationIssue(
                    "order_status_history",
                    "order_without_history",
                    f"{orders.height} order(s) have no status history",
                )
            )
        return issues

    grouped = status_history.group_by("order_id").agg(
        pl.col("sequence").min().alias("lowest"),
        pl.col("sequence").max().alias("highest"),
        pl.col("sequence").n_unique().alias("distinct"),
        pl.len().alias("total"),
    )
    broken = grouped.filter(
        (pl.col("lowest") != 1)
        | (pl.col("highest") != pl.col("total"))
        | (pl.col("distinct") != pl.col("total"))
    )
    if not broken.is_empty():
        issues.append(
            ValidationIssue(
                "order_status_history",
                "invalid_sequence",
                f"{broken.height} order(s) are not numbered 1..n without gaps",
            )
        )

    # Position in the lifecycle must advance in step with the sequence, and
    # time must move forwards with it.
    positions = pl.DataFrame(
        {
            "status": known,
            "lifecycle_position": list(range(1, len(known) + 1)),
        }
    )
    ordered = (
        status_history.join(positions, on="status", how="inner")
        .sort("order_id", "sequence")
        .with_columns(
            pl.col("status_timestamp").shift(1).over("order_id").alias("previous_timestamp"),
            pl.col("lifecycle_position").shift(1).over("order_id").alias("previous_position"),
        )
    )
    issues += _issue_if(
        ordered,
        "order_status_history",
        "history_out_of_order",
        pl.col("previous_timestamp").is_not_null()
        & (pl.col("status_timestamp") <= pl.col("previous_timestamp")),
        "each status happens after the one before it",
    )
    issues += _issue_if(
        ordered,
        "order_status_history",
        "lifecycle_out_of_order",
        pl.col("previous_position").is_not_null()
        & (pl.col("lifecycle_position") <= pl.col("previous_position")),
        "the lifecycle advances with the sequence",
    )
    issues += _issue_if(
        ordered,
        "order_status_history",
        "lifecycle_does_not_start_at_created",
        (pl.col("sequence") == 1) & (pl.col("status") != str(OrderStatus.CREATED)),
        "every history starts at CREATED",
    )

    covered = set(status_history["order_id"].to_list())
    if without := [
        order_id for order_id in orders["order_id"].to_list() if order_id not in covered
    ]:
        issues.append(
            ValidationIssue(
                "order_status_history",
                "order_without_history",
                f"{len(without)} order(s) have no status history",
            )
        )

    latest = (
        status_history.sort("order_id", "sequence")
        .group_by("order_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest_status"))
    )
    reconciled = orders.join(latest, on="order_id", how="inner")
    issues += _issue_if(
        reconciled,
        "orders",
        "current_status_mismatch",
        pl.col("current_status") != pl.col("latest_status"),
        "current_status equals the status of the latest history row",
    )

    first = status_history.filter(pl.col("sequence") == 1).select(
        "order_id", pl.col("status_timestamp").alias("created_status_at")
    )
    anchored = orders.join(first, on="order_id", how="inner")
    issues += _issue_if(
        anchored,
        "order_status_history",
        "history_before_order",
        pl.col("created_status_at") < pl.col("created_at"),
        "the first status is recorded no earlier than the order",
    )
    return issues


def validate_order_data(
    datasets: Mapping[str, pl.DataFrame],
) -> list[ValidationIssue]:
    """Validate schema, referential integrity, and order business rules.

    Args:
        datasets: The order datasets plus the upstream datasets they
            reference, keyed by name.

    Returns:
        Every issue found. An empty list means the data satisfies the F006
        acceptance criteria.
    """
    issues = validate_referential_integrity(datasets, ORDER_DATASETS)

    orders = datasets.get("orders")
    order_lines = datasets.get("order_lines")
    status_history = datasets.get("order_status_history")
    if orders is None or order_lines is None or status_history is None:
        return issues

    issues.extend(validate_order_numbers(orders))
    issues.extend(validate_status_history(orders, status_history))

    checkouts = datasets.get("checkout")
    if checkouts is not None:
        issues.extend(validate_checkout_eligibility(orders, checkouts))
        issues.extend(validate_financial_copy(orders, checkouts))
        issues.extend(validate_order_timeline(orders, checkouts))

    cart_items = datasets.get("cart_items")
    if cart_items is not None:
        issues.extend(validate_line_reconciliation(orders, order_lines, cart_items))
    return issues


def assert_valid_order_data(datasets: Mapping[str, pl.DataFrame]) -> None:
    """Validate the order datasets and raise if anything is wrong.

    Args:
        datasets: The order datasets plus the upstream data they reference.

    Raises:
        ValidationError: If any validation issue is found.
    """
    issues = validate_order_data(datasets)
    if issues:
        raise ValidationError(issues)
