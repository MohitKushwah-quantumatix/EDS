"""Validation rules for the F007 payment datasets.

Referential integrity is delegated to
:func:`eds.core.validation.referential.validate_referential_integrity` with the
payment declarations, which covers duplicate ``payment_id``,
``payment_reference`` and ``history_id`` values, the one-payment-per-order
rule, and invalid order, customer and payment references.

The rules here cover what a schema cannot express: that payments came only
from orders, that the money and the method were copied rather than re-drawn,
that the provider follows from the method, and that the status history is a
well-formed lifecycle ending at the payment's recorded status.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import polars as pl

from eds.core.validation.issues import ValidationError, ValidationIssue
from eds.domains.retail.domain.commerce.enums import (
    PAYMENT_INITIAL_STATUSES,
    PAYMENT_TRANSITIONS,
    PaymentStatus,
)
from eds.domains.retail.domain.commerce.schema import PAYMENT_DATASETS
from eds.domains.retail.generators.commerce.payment_generator import PROVIDER_BY_METHOD
from eds.domains.retail.validation.referential import validate_referential_integrity

__all__ = [
    "CURRENCY_PATTERN",
    "PAYMENT_REFERENCE_PATTERN",
    "assert_valid_payment_data",
    "validate_payment_amounts",
    "validate_payment_data",
    "validate_payment_method",
    "validate_payment_references",
    "validate_payment_status_history",
    "validate_payment_timeline",
    "validate_order_coverage",
]

#: ``PAY-YYYYMMDD-000001`` and anything else with the same shape.
PAYMENT_REFERENCE_PATTERN: Final[str] = r"^[A-Z0-9]{1,8}-\d{8}-\d{6}$"

#: An ISO 4217 alphabetic code.
CURRENCY_PATTERN: Final[str] = r"^[A-Z]{3}$"


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


def validate_order_coverage(payments: pl.DataFrame, orders: pl.DataFrame) -> list[ValidationIssue]:
    """Check every payable order has exactly one payment, and nothing else does.

    Args:
        payments: The payments dataset.
        orders: The F006 orders dataset.

    Returns:
        Issues for a payable order with no payment, an order billed at zero or
        less that was nevertheless charged, an order paid for more than once,
        or a payment whose customer disagrees with its order.
    """
    issues: list[ValidationIssue] = []

    duplicates = payments.height - payments["order_id"].n_unique()
    if duplicates:
        issues.append(
            ValidationIssue(
                "payments",
                "multiple_payments_per_order",
                f"{duplicates} order(s) were paid for more than once",
            )
        )

    payable = set(orders.filter(pl.col("total_amount") > 0.0)["order_id"].to_list())
    covered = set(payments["order_id"].to_list())
    if missing := payable - covered:
        issues.append(
            ValidationIssue(
                "payments",
                "payable_order_without_payment",
                f"{len(missing)} payable order(s) produced no payment",
            )
        )
    if extra := covered - payable:
        issues.append(
            ValidationIssue(
                "payments",
                "payment_for_unpayable_order",
                f"{len(extra)} payment(s) belong to an order billed at zero or less",
            )
        )

    joined = payments.join(
        orders.select("order_id", pl.col("customer_id").alias("order_customer_id")),
        on="order_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "payments",
        "customer_mismatch",
        pl.col("customer_id") != pl.col("order_customer_id"),
        "customer_id matches the order being paid for",
    )
    return issues


def validate_payment_amounts(payments: pl.DataFrame, orders: pl.DataFrame) -> list[ValidationIssue]:
    """Check the amount was copied from the order and the currency is sound.

    ADR-007 makes the order the single source of financial truth for a
    payment, so the amount is compared for exact equality rather than within a
    tolerance: a recomputed figure would rarely land on the same cent.

    Args:
        payments: The payments dataset.
        orders: The F006 orders dataset.

    Returns:
        Issues for an amount that disagrees with its order's total, a
        non-positive amount, a malformed currency code, or more than one
        currency in the dataset.
    """
    issues: list[ValidationIssue] = []

    joined = payments.join(
        orders.select("order_id", pl.col("total_amount").alias("order_total")),
        on="order_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "payments",
        "amount_not_copied",
        pl.col("payment_amount") != pl.col("order_total"),
        "payment_amount is copied verbatim from the order's total_amount",
    )
    issues += _issue_if(
        payments,
        "payments",
        "non_positive_amount",
        pl.col("payment_amount") <= 0.0,
        "payment_amount > 0",
    )
    issues += _issue_if(
        payments,
        "payments",
        "malformed_currency",
        ~pl.col("currency").str.contains(CURRENCY_PATTERN),
        "currency is a three-letter ISO 4217 code",
    )

    # F007 is single-currency by design; a second code means something other
    # than the configured value leaked in.
    distinct = payments["currency"].n_unique()
    if distinct > 1:
        issues.append(
            ValidationIssue(
                "payments",
                "mixed_currency",
                f"{distinct} distinct currencies found, expected exactly one",
            )
        )
    return issues


def validate_payment_method(
    payments: pl.DataFrame, checkouts: pl.DataFrame, orders: pl.DataFrame
) -> list[ValidationIssue]:
    """Check the method came from the checkout and the provider from the method.

    Args:
        payments: The payments dataset.
        checkouts: The F005 checkout dataset.
        orders: The F006 orders dataset, which links a payment to its checkout.

    Returns:
        Issues for a method that disagrees with the checkout, an unknown
        method, or a provider that does not follow from the method.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        payments,
        "payments",
        "unknown_payment_method",
        ~pl.col("payment_method").is_in(list(PROVIDER_BY_METHOD)),
        f"payment_method is one of {sorted(PROVIDER_BY_METHOD)}",
    )

    expected = pl.DataFrame(
        {
            "payment_method": list(PROVIDER_BY_METHOD),
            "expected_provider": list(PROVIDER_BY_METHOD.values()),
        }
    )
    issues += _issue_if(
        payments.join(expected, on="payment_method", how="inner"),
        "payments",
        "provider_mismatch",
        pl.col("payment_provider") != pl.col("expected_provider"),
        "payment_provider is the provider that handles payment_method",
    )

    joined = payments.join(
        orders.select("order_id", "checkout_id"), on="order_id", how="inner"
    ).join(
        checkouts.select("checkout_id", pl.col("payment_method").alias("checkout_method")),
        on="checkout_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "payments",
        "method_not_copied",
        pl.col("payment_method") != pl.col("checkout_method"),
        "payment_method is copied from the checkout the order came from",
    )
    return issues


def validate_payment_references(payments: pl.DataFrame) -> list[ValidationIssue]:
    """Check the business payment reference is well formed and consistent.

    Args:
        payments: The payments dataset.

    Returns:
        Issues for a malformed reference, or one whose embedded date disagrees
        with the day the payment was created, or a day that is not numbered
        from one without gaps.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        payments,
        "payments",
        "malformed_payment_reference",
        ~pl.col("payment_reference").str.contains(PAYMENT_REFERENCE_PATTERN),
        "payment_reference matches PREFIX-YYYYMMDD-NNNNNN",
    )

    # The remaining checks read the reference apart, so they only run on the
    # rows that are shaped like one. A malformed reference has already been
    # reported above; parsing it here would raise rather than add an issue.
    well_formed = payments.filter(
        pl.col("payment_reference").str.contains(PAYMENT_REFERENCE_PATTERN)
    )
    if well_formed.is_empty():
        return issues

    dated = well_formed.with_columns(pl.col("created_at").dt.date().alias("payment_date"))
    issues += _issue_if(
        dated,
        "payments",
        "payment_reference_date_mismatch",
        pl.col("payment_reference").str.slice(-15, 8)
        != pl.col("payment_date").dt.strftime("%Y%m%d"),
        "the date inside payment_reference is the date of created_at",
    )

    numbered = dated.group_by("payment_date").agg(
        pl.col("payment_reference").str.slice(-6).cast(pl.Int64).min().alias("lowest"),
        pl.col("payment_reference").str.slice(-6).cast(pl.Int64).max().alias("highest"),
        pl.len().alias("total"),
    )
    broken = numbered.filter((pl.col("lowest") != 1) | (pl.col("highest") != pl.col("total")))
    if not broken.is_empty():
        issues.append(
            ValidationIssue(
                "payments",
                "payment_reference_not_sequential",
                f"{broken.height} date(s) are not numbered 1..n without gaps",
            )
        )
    return issues


def validate_payment_timeline(
    payments: pl.DataFrame, orders: pl.DataFrame
) -> list[ValidationIssue]:
    """Check a payment was attempted after the order it pays for.

    Args:
        payments: The payments dataset.
        orders: The F006 orders dataset.

    Returns:
        Issues for a payment predating its order, an authorisation before the
        attempt, a capture that does not follow its authorisation, or a
        timestamp populated on a status that never reached that stage.
    """
    issues: list[ValidationIssue] = []

    joined = payments.join(
        orders.select("order_id", pl.col("created_at").alias("order_created_at")),
        on="order_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "payments",
        "payment_before_order",
        pl.col("created_at") <= pl.col("order_created_at"),
        "the payment is created after the order it pays for",
    )
    issues += _issue_if(
        payments,
        "payments",
        "authorized_before_created",
        pl.col("authorized_at").is_not_null() & (pl.col("authorized_at") < pl.col("created_at")),
        "authorized_at is no earlier than created_at",
    )
    issues += _issue_if(
        payments,
        "payments",
        "captured_before_authorized",
        pl.col("captured_at").is_not_null()
        & (pl.col("authorized_at").is_null() | (pl.col("captured_at") < pl.col("authorized_at"))),
        "captured_at follows an authorisation",
    )

    # A failed payment never reached authorisation; only a captured one ever
    # took the money.
    issues += _issue_if(
        payments,
        "payments",
        "authorized_at_inconsistent",
        (pl.col("payment_status") == str(PaymentStatus.FAILED))
        != pl.col("authorized_at").is_null(),
        "authorized_at is populated exactly when the payment is not FAILED",
    )
    issues += _issue_if(
        payments,
        "payments",
        "captured_at_inconsistent",
        (pl.col("payment_status") == str(PaymentStatus.CAPTURED))
        != pl.col("captured_at").is_not_null(),
        "captured_at is populated exactly when the payment is CAPTURED",
    )
    return issues


def validate_payment_status_history(
    payments: pl.DataFrame, status_history: pl.DataFrame
) -> list[ValidationIssue]:
    """Check the status history is a well-formed payment lifecycle.

    Args:
        payments: The payments dataset.
        status_history: The payment status history dataset.

    Returns:
        Issues for an unknown status, a sequence that is not numbered from one
        without gaps, timestamps that move backwards, a transition the
        lifecycle does not allow, a payment with no history, or a
        ``payment_status`` that disagrees with the latest row.
    """
    issues: list[ValidationIssue] = []
    known = [str(member) for member in PaymentStatus]

    issues += _issue_if(
        status_history,
        "payment_status_history",
        "unknown_status",
        ~pl.col("status").is_in(known),
        f"status is one of {known}",
    )
    issues += _issue_if(
        status_history,
        "payment_status_history",
        "invalid_sequence",
        pl.col("sequence") < 1,
        "sequence >= 1",
    )

    if status_history.is_empty():
        if not payments.is_empty():
            issues.append(
                ValidationIssue(
                    "payment_status_history",
                    "payment_without_history",
                    f"{payments.height} payment(s) have no status history",
                )
            )
        return issues

    grouped = status_history.group_by("payment_id").agg(
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
                "payment_status_history",
                "invalid_sequence",
                f"{broken.height} payment(s) are not numbered 1..n without gaps",
            )
        )

    ordered = status_history.sort("payment_id", "sequence").with_columns(
        pl.col("status_timestamp").shift(1).over("payment_id").alias("previous_timestamp"),
        pl.col("status").shift(1).over("payment_id").alias("previous_status"),
    )
    issues += _issue_if(
        ordered,
        "payment_status_history",
        "history_out_of_order",
        pl.col("previous_timestamp").is_not_null()
        & (pl.col("status_timestamp") <= pl.col("previous_timestamp")),
        "each status happens after the one before it",
    )
    issues += _issue_if(
        ordered,
        "payment_status_history",
        "invalid_opening_status",
        (pl.col("sequence") == 1)
        & ~pl.col("status").is_in([str(member) for member in PAYMENT_INITIAL_STATUSES]),
        f"a history opens at one of {[str(m) for m in PAYMENT_INITIAL_STATUSES]}",
    )

    # Every non-opening row must be a transition the lifecycle allows.
    pairs = [
        (str(source), str(target))
        for source, targets in PAYMENT_TRANSITIONS.items()
        for target in targets
    ]
    allowed = pl.DataFrame(
        {
            "previous_status": [source for source, _ in pairs],
            "status": [target for _, target in pairs],
            "allowed": [True] * len(pairs),
        },
        schema={"previous_status": pl.String, "status": pl.String, "allowed": pl.Boolean},
    )
    transitions = ordered.filter(pl.col("previous_status").is_not_null()).join(
        allowed, on=["previous_status", "status"], how="left"
    )
    issues += _issue_if(
        transitions,
        "payment_status_history",
        "invalid_transition",
        pl.col("allowed").is_null(),
        "each status follows one the lifecycle allows",
    )

    covered = set(status_history["payment_id"].to_list())
    if without := [
        payment_id for payment_id in payments["payment_id"].to_list() if payment_id not in covered
    ]:
        issues.append(
            ValidationIssue(
                "payment_status_history",
                "payment_without_history",
                f"{len(without)} payment(s) have no status history",
            )
        )

    latest = (
        status_history.sort("payment_id", "sequence")
        .group_by("payment_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest_status"))
    )
    reconciled = payments.join(latest, on="payment_id", how="inner")
    issues += _issue_if(
        reconciled,
        "payments",
        "payment_status_mismatch",
        pl.col("payment_status") != pl.col("latest_status"),
        "payment_status equals the status of the latest history row",
    )

    first = status_history.filter(pl.col("sequence") == 1).select(
        "payment_id", pl.col("status_timestamp").alias("opening_status_at")
    )
    anchored = payments.join(first, on="payment_id", how="inner")
    issues += _issue_if(
        anchored,
        "payment_status_history",
        "history_before_payment",
        pl.col("opening_status_at") < pl.col("created_at"),
        "the first status is recorded no earlier than the payment",
    )
    return issues


def validate_payment_data(
    datasets: Mapping[str, pl.DataFrame],
) -> list[ValidationIssue]:
    """Validate schema, referential integrity, and payment business rules.

    Args:
        datasets: The payment datasets plus the upstream datasets they
            reference, keyed by name.

    Returns:
        Every issue found. An empty list means the data satisfies the F007
        acceptance criteria.
    """
    issues = validate_referential_integrity(datasets, PAYMENT_DATASETS)

    payments = datasets.get("payments")
    status_history = datasets.get("payment_status_history")
    if payments is None or status_history is None:
        return issues

    issues.extend(validate_payment_references(payments))
    issues.extend(validate_payment_status_history(payments, status_history))

    orders = datasets.get("orders")
    if orders is not None:
        issues.extend(validate_order_coverage(payments, orders))
        issues.extend(validate_payment_amounts(payments, orders))
        issues.extend(validate_payment_timeline(payments, orders))

    checkouts = datasets.get("checkout")
    if checkouts is not None and orders is not None:
        issues.extend(validate_payment_method(payments, checkouts, orders))
    return issues


def assert_valid_payment_data(datasets: Mapping[str, pl.DataFrame]) -> None:
    """Validate the payment datasets and raise if anything is wrong.

    Args:
        datasets: The payment datasets plus the upstream data they reference.

    Raises:
        ValidationError: If any validation issue is found.
    """
    issues = validate_payment_data(datasets)
    if issues:
        raise ValidationError(issues)
