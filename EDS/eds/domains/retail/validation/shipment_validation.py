"""Validation rules for the F008 shipment datasets.

Referential integrity is delegated to
:func:`eds.core.validation.referential.validate_referential_integrity` with the
shipment declarations, which covers duplicate ``shipment_id``,
``shipment_number``, ``tracking_number``, ``shipment_item_id`` and
``history_id`` values, the one-shipment-per-payment rule, and invalid payment,
order, customer, order line, product and shipment references.

The rules here cover what a schema cannot express: that shipments came only
from captured payments, that the carrier follows from the shipping method,
that the items reconcile against the order lines, and that the status history
is a well-formed lifecycle ending at the shipment's current status.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import polars as pl

from eds.core.validation.issues import ValidationError, ValidationIssue
from eds.domains.retail.domain.commerce.enums import (
    SHIPMENT_LIFECYCLE,
    PaymentStatus,
    ShipmentStatus,
)
from eds.domains.retail.domain.commerce.schema import SHIPMENT_DATASETS
from eds.domains.retail.validation.referential import validate_referential_integrity

__all__ = [
    "SHIPMENT_NUMBER_PATTERN",
    "TRACKING_NUMBER_PATTERN",
    "assert_valid_shipment_data",
    "validate_carrier_assignment",
    "validate_item_reconciliation",
    "validate_payment_eligibility",
    "validate_shipment_data",
    "validate_shipment_numbers",
    "validate_shipment_status_history",
    "validate_shipment_timeline",
]

#: ``SHP-YYYYMMDD-000001`` and anything else with the same shape.
SHIPMENT_NUMBER_PATTERN: Final[str] = r"^[A-Z0-9]{1,8}-\d{8}-\d{6}$"

#: ``TRK-4738105562`` and anything else with the same shape.
TRACKING_NUMBER_PATTERN: Final[str] = r"^[A-Z0-9]{1,8}-[A-Z0-9]{10}$"


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


def validate_payment_eligibility(
    shipments: pl.DataFrame, payments: pl.DataFrame
) -> list[ValidationIssue]:
    """Check shipments came only from captured payments, one each.

    Args:
        shipments: The shipments dataset.
        payments: The F007 payments dataset.

    Returns:
        Issues for a shipment on a failed or voided payment, a captured
        payment with no shipment, a payment shipped more than once, or a
        shipment whose order or customer disagrees with its payment.
    """
    issues: list[ValidationIssue] = []

    joined = shipments.join(
        payments.select(
            "payment_id",
            "payment_status",
            pl.col("order_id").alias("payment_order_id"),
            pl.col("customer_id").alias("payment_customer_id"),
        ),
        on="payment_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "shipments",
        "invalid_payment_status",
        pl.col("payment_status") != str(PaymentStatus.CAPTURED),
        "only a CAPTURED payment produces a shipment",
    )
    for column in ("order_id", "customer_id"):
        issues += _issue_if(
            joined,
            "shipments",
            "payment_field_mismatch",
            pl.col(column) != pl.col(f"payment_{column}"),
            f"{column} matches the payment it ships",
        )

    duplicates = shipments.height - shipments["payment_id"].n_unique()
    if duplicates:
        issues.append(
            ValidationIssue(
                "shipments",
                "multiple_shipments_per_payment",
                f"{duplicates} payment(s) produced more than one shipment",
            )
        )

    eligible = set(
        payments.filter(pl.col("payment_status") == str(PaymentStatus.CAPTURED))[
            "payment_id"
        ].to_list()
    )
    covered = set(shipments["payment_id"].to_list())
    if missing := eligible - covered:
        issues.append(
            ValidationIssue(
                "shipments",
                "captured_payment_without_shipment",
                f"{len(missing)} captured payment(s) produced no shipment",
            )
        )
    return issues


def validate_carrier_assignment(
    shipments: pl.DataFrame,
    checkouts: pl.DataFrame,
    orders: pl.DataFrame,
    carriers: Mapping[str, tuple[str, ...]] | None = None,
) -> list[ValidationIssue]:
    """Check the shipping method and its carrier.

    Args:
        shipments: The shipments dataset.
        checkouts: The F005 checkout dataset.
        orders: The F006 orders dataset, which links a shipment to its checkout.
        carriers: The configured carriers per shipping method. When omitted the
            carrier-membership check is skipped, because nothing else knows
            which carriers were on offer.

    Returns:
        Issues for a method that disagrees with the checkout, an empty
        carrier, or a carrier the method does not offer.
    """
    issues: list[ValidationIssue] = []

    joined = shipments.join(
        orders.select("order_id", "checkout_id"), on="order_id", how="inner"
    ).join(
        checkouts.select("checkout_id", pl.col("shipping_method").alias("checkout_method")),
        on="checkout_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "shipments",
        "shipping_method_not_copied",
        pl.col("shipping_method") != pl.col("checkout_method"),
        "shipping_method is copied from the checkout the order came from",
    )
    issues += _issue_if(
        shipments,
        "shipments",
        "missing_carrier",
        pl.col("carrier").str.len_chars() == 0,
        "carrier is not empty",
    )

    if carriers is None:
        return issues

    allowed = pl.DataFrame(
        {
            "shipping_method": [method for method, options in carriers.items() for _ in options],
            "carrier": [carrier for options in carriers.values() for carrier in options],
            "offered": [True for options in carriers.values() for _ in options],
        },
        schema={"shipping_method": pl.String, "carrier": pl.String, "offered": pl.Boolean},
    )
    matched = shipments.join(allowed, on=["shipping_method", "carrier"], how="left")
    issues += _issue_if(
        matched,
        "shipments",
        "carrier_not_offered_for_method",
        pl.col("offered").is_null(),
        "carrier is one the shipping method offers",
    )
    return issues


def validate_shipment_numbers(shipments: pl.DataFrame) -> list[ValidationIssue]:
    """Check the shipment and tracking numbers are well formed.

    Args:
        shipments: The shipments dataset.

    Returns:
        Issues for a malformed shipment number, one whose embedded date
        disagrees with the day the shipment was created, a day that is not
        numbered from one without gaps, or a malformed tracking number.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        shipments,
        "shipments",
        "malformed_shipment_number",
        ~pl.col("shipment_number").str.contains(SHIPMENT_NUMBER_PATTERN),
        "shipment_number matches PREFIX-YYYYMMDD-NNNNNN",
    )
    issues += _issue_if(
        shipments,
        "shipments",
        "malformed_tracking_number",
        ~pl.col("tracking_number").str.contains(TRACKING_NUMBER_PATTERN),
        "tracking_number matches PREFIX-XXXXXXXXXX",
    )

    # The remaining checks read the number apart, so they only run on the rows
    # that are shaped like one. A malformed number has already been reported
    # above; parsing it here would raise rather than add an issue.
    well_formed = shipments.filter(pl.col("shipment_number").str.contains(SHIPMENT_NUMBER_PATTERN))
    if well_formed.is_empty():
        return issues

    dated = well_formed.with_columns(pl.col("created_at").dt.date().alias("shipment_date"))
    issues += _issue_if(
        dated,
        "shipments",
        "shipment_number_date_mismatch",
        pl.col("shipment_number").str.slice(-15, 8)
        != pl.col("shipment_date").dt.strftime("%Y%m%d"),
        "the date inside shipment_number is the date of created_at",
    )

    numbered = dated.group_by("shipment_date").agg(
        pl.col("shipment_number").str.slice(-6).cast(pl.Int64).min().alias("lowest"),
        pl.col("shipment_number").str.slice(-6).cast(pl.Int64).max().alias("highest"),
        pl.len().alias("total"),
    )
    broken = numbered.filter((pl.col("lowest") != 1) | (pl.col("highest") != pl.col("total")))
    if not broken.is_empty():
        issues.append(
            ValidationIssue(
                "shipments",
                "shipment_number_not_sequential",
                f"{broken.height} date(s) are not numbered 1..n without gaps",
            )
        )
    return issues


def validate_shipment_timeline(
    shipments: pl.DataFrame, payments: pl.DataFrame
) -> list[ValidationIssue]:
    """Check a shipment was created after the payment that funded it.

    Args:
        shipments: The shipments dataset.
        payments: The F007 payments dataset.

    Returns:
        Issues for a shipment predating its payment's capture, a dispatch
        before creation, a delivery that does not follow dispatch, an estimate
        before creation, or a timestamp populated on a status that never
        reached that stage.
    """
    issues: list[ValidationIssue] = []

    joined = shipments.join(
        payments.select("payment_id", pl.col("captured_at").alias("payment_captured_at")),
        on="payment_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "shipments",
        "shipment_before_payment",
        pl.col("payment_captured_at").is_null()
        | (pl.col("created_at") <= pl.col("payment_captured_at")),
        "the shipment is created after its payment was captured",
    )
    issues += _issue_if(
        shipments,
        "shipments",
        "shipped_before_created",
        pl.col("shipped_at").is_not_null() & (pl.col("shipped_at") <= pl.col("created_at")),
        "shipped_at is after created_at",
    )
    issues += _issue_if(
        shipments,
        "shipments",
        "delivered_before_shipped",
        pl.col("delivered_at").is_not_null()
        & (pl.col("shipped_at").is_null() | (pl.col("delivered_at") <= pl.col("shipped_at"))),
        "delivered_at is after shipped_at",
    )
    issues += _issue_if(
        shipments,
        "shipments",
        "estimate_before_created",
        pl.col("estimated_delivery_at") < pl.col("created_at"),
        "estimated_delivery_at is no earlier than created_at",
    )

    # A shipment that never left has no dispatch time, and one that never
    # arrived has no delivery time.
    issues += _issue_if(
        shipments,
        "shipments",
        "shipped_at_inconsistent",
        pl.col("current_status").is_in(
            [
                str(ShipmentStatus.SHIPPED),
                str(ShipmentStatus.IN_TRANSIT),
                str(ShipmentStatus.DELIVERED),
            ]
        )
        & pl.col("shipped_at").is_null(),
        "shipped_at is populated once the shipment has been dispatched",
    )
    issues += _issue_if(
        shipments,
        "shipments",
        "delivered_at_inconsistent",
        (pl.col("current_status") == str(ShipmentStatus.DELIVERED))
        != pl.col("delivered_at").is_not_null(),
        "delivered_at is populated exactly when the shipment is DELIVERED",
    )
    return issues


def validate_item_reconciliation(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, order_lines: pl.DataFrame
) -> list[ValidationIssue]:
    """Check the items match the order lines of the shipment's order.

    Args:
        shipments: The shipments dataset.
        shipment_items: The shipment items dataset.
        order_lines: The F006 order lines dataset.

    Returns:
        Issues for a non-positive quantity, an item whose order line belongs to
        a different order, a quantity or product that disagrees with the order
        line, an order line of a shipped order that was left behind, or an item
        created before its shipment.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        shipment_items,
        "shipment_items",
        "non_positive_quantity",
        pl.col("quantity") <= 0,
        "quantity > 0",
    )

    joined = shipment_items.join(
        shipments.select(
            "shipment_id",
            pl.col("order_id").alias("shipment_order_id"),
            pl.col("created_at").alias("shipment_created_at"),
        ),
        on="shipment_id",
        how="inner",
    ).join(
        order_lines.select(
            "order_line_id",
            pl.col("order_id").alias("line_order_id"),
            pl.col("product_id").alias("line_product_id"),
            pl.col("quantity").alias("line_quantity"),
        ),
        on="order_line_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "shipment_items",
        "line_from_another_order",
        pl.col("shipment_order_id") != pl.col("line_order_id"),
        "the order line belongs to the shipment's own order",
    )
    issues += _issue_if(
        joined,
        "shipment_items",
        "quantity_mismatch",
        pl.col("quantity") != pl.col("line_quantity"),
        "quantity equals the order line's quantity",
    )
    issues += _issue_if(
        joined,
        "shipment_items",
        "product_mismatch",
        pl.col("product_id") != pl.col("line_product_id"),
        "product_id equals the order line's product",
    )
    issues += _issue_if(
        joined,
        "shipment_items",
        "item_before_shipment",
        pl.col("created_at") < pl.col("shipment_created_at"),
        "the item is created no earlier than its shipment",
    )

    # Every line of a shipped order must go out: split shipments and
    # backorders are out of scope.
    expected = order_lines.join(shipments.select("order_id"), on="order_id", how="semi").select(
        "order_line_id"
    )
    shipped_lines = set(shipment_items["order_line_id"].to_list())
    if left_behind := set(expected["order_line_id"].to_list()) - shipped_lines:
        issues.append(
            ValidationIssue(
                "shipment_items",
                "order_line_not_shipped",
                f"{len(left_behind)} order line(s) of a shipped order produced no item",
            )
        )
    return issues


def validate_shipment_status_history(
    shipments: pl.DataFrame, status_history: pl.DataFrame
) -> list[ValidationIssue]:
    """Check the status history is a well-formed lifecycle.

    Args:
        shipments: The shipments dataset.
        status_history: The shipment status history dataset.

    Returns:
        Issues for an unknown status, a sequence that is not numbered from one
        without gaps, timestamps that move backwards, a history that does not
        follow the lifecycle order, a shipment with no history, or a
        ``current_status`` or timeline column that disagrees with the history.
    """
    issues: list[ValidationIssue] = []
    known = [str(member) for member in SHIPMENT_LIFECYCLE]

    issues += _issue_if(
        status_history,
        "shipment_status_history",
        "unknown_status",
        ~pl.col("status").is_in(known),
        f"status is one of {known}",
    )
    issues += _issue_if(
        status_history,
        "shipment_status_history",
        "invalid_sequence",
        pl.col("sequence") < 1,
        "sequence >= 1",
    )

    if status_history.is_empty():
        if not shipments.is_empty():
            issues.append(
                ValidationIssue(
                    "shipment_status_history",
                    "shipment_without_history",
                    f"{shipments.height} shipment(s) have no status history",
                )
            )
        return issues

    grouped = status_history.group_by("shipment_id").agg(
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
                "shipment_status_history",
                "invalid_sequence",
                f"{broken.height} shipment(s) are not numbered 1..n without gaps",
            )
        )

    # Position in the lifecycle must advance in step with the sequence, and
    # time must move forwards with it.
    positions = pl.DataFrame(
        {
            "status": known,
            "lifecycle_position": list(range(1, len(known) + 1)),
        },
        schema={"status": pl.String, "lifecycle_position": pl.Int64},
    )
    ordered = (
        status_history.join(positions, on="status", how="inner")
        .sort("shipment_id", "sequence")
        .with_columns(
            pl.col("status_timestamp").shift(1).over("shipment_id").alias("previous_timestamp"),
            pl.col("lifecycle_position").shift(1).over("shipment_id").alias("previous_position"),
        )
    )
    issues += _issue_if(
        ordered,
        "shipment_status_history",
        "history_out_of_order",
        pl.col("previous_timestamp").is_not_null()
        & (pl.col("status_timestamp") <= pl.col("previous_timestamp")),
        "each status happens after the one before it",
    )
    issues += _issue_if(
        ordered,
        "shipment_status_history",
        "lifecycle_out_of_order",
        pl.col("previous_position").is_not_null()
        & (pl.col("lifecycle_position") <= pl.col("previous_position")),
        "the lifecycle advances with the sequence",
    )
    issues += _issue_if(
        ordered,
        "shipment_status_history",
        "lifecycle_does_not_start_at_created",
        (pl.col("sequence") == 1) & (pl.col("status") != str(ShipmentStatus.CREATED)),
        "every history starts at CREATED",
    )

    covered = set(status_history["shipment_id"].to_list())
    if without := [
        shipment_id
        for shipment_id in shipments["shipment_id"].to_list()
        if shipment_id not in covered
    ]:
        issues.append(
            ValidationIssue(
                "shipment_status_history",
                "shipment_without_history",
                f"{len(without)} shipment(s) have no status history",
            )
        )

    latest = (
        status_history.sort("shipment_id", "sequence")
        .group_by("shipment_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest_status"))
    )
    reconciled = shipments.join(latest, on="shipment_id", how="inner")
    issues += _issue_if(
        reconciled,
        "shipments",
        "current_status_mismatch",
        pl.col("current_status") != pl.col("latest_status"),
        "current_status equals the status of the latest history row",
    )

    # The timeline columns are denormalised from the history, so they must
    # carry exactly the timestamps the history recorded.
    stamps = status_history.group_by("shipment_id").agg(
        pl.col("status_timestamp")
        .filter(pl.col("status") == str(ShipmentStatus.SHIPPED))
        .first()
        .alias("history_shipped_at"),
        pl.col("status_timestamp")
        .filter(pl.col("status") == str(ShipmentStatus.DELIVERED))
        .first()
        .alias("history_delivered_at"),
    )
    stamped = shipments.join(stamps, on="shipment_id", how="inner")
    for column in ("shipped_at", "delivered_at"):
        issues += _issue_if(
            stamped,
            "shipments",
            "timeline_history_mismatch",
            pl.col(column).is_null() != pl.col(f"history_{column}").is_null(),
            f"{column} is populated exactly when the history records it",
        )
        issues += _issue_if(
            stamped,
            "shipments",
            "timeline_history_mismatch",
            pl.col(column).is_not_null() & (pl.col(column) != pl.col(f"history_{column}")),
            f"{column} equals the timestamp of its history row",
        )

    first = status_history.filter(pl.col("sequence") == 1).select(
        "shipment_id", pl.col("status_timestamp").alias("created_status_at")
    )
    anchored = shipments.join(first, on="shipment_id", how="inner")
    issues += _issue_if(
        anchored,
        "shipment_status_history",
        "history_before_shipment",
        pl.col("created_status_at") < pl.col("created_at"),
        "the first status is recorded no earlier than the shipment",
    )
    return issues


def validate_shipment_data(
    datasets: Mapping[str, pl.DataFrame],
    carriers: Mapping[str, tuple[str, ...]] | None = None,
) -> list[ValidationIssue]:
    """Validate schema, referential integrity, and shipment business rules.

    Args:
        datasets: The shipment datasets plus the upstream datasets they
            reference, keyed by name.
        carriers: The configured carriers per shipping method, used to check
            that each shipment's carrier was actually on offer.

    Returns:
        Every issue found. An empty list means the data satisfies the F008
        acceptance criteria.
    """
    issues = validate_referential_integrity(datasets, SHIPMENT_DATASETS)

    shipments = datasets.get("shipments")
    shipment_items = datasets.get("shipment_items")
    status_history = datasets.get("shipment_status_history")
    if shipments is None or shipment_items is None or status_history is None:
        return issues

    issues.extend(validate_shipment_numbers(shipments))
    issues.extend(validate_shipment_status_history(shipments, status_history))

    payments = datasets.get("payments")
    if payments is not None:
        issues.extend(validate_payment_eligibility(shipments, payments))
        issues.extend(validate_shipment_timeline(shipments, payments))

    checkouts = datasets.get("checkout")
    orders = datasets.get("orders")
    if checkouts is not None and orders is not None:
        issues.extend(validate_carrier_assignment(shipments, checkouts, orders, carriers))

    order_lines = datasets.get("order_lines")
    if order_lines is not None:
        issues.extend(validate_item_reconciliation(shipments, shipment_items, order_lines))
    return issues


def assert_valid_shipment_data(
    datasets: Mapping[str, pl.DataFrame],
    carriers: Mapping[str, tuple[str, ...]] | None = None,
) -> None:
    """Validate the shipment datasets and raise if anything is wrong.

    Args:
        datasets: The shipment datasets plus the upstream data they reference.
        carriers: The configured carriers per shipping method.

    Raises:
        ValidationError: If any validation issue is found.
    """
    issues = validate_shipment_data(datasets, carriers)
    if issues:
        raise ValidationError(issues)
