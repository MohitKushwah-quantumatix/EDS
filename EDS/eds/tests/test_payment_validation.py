"""Tests for payment validation.

Every failure path corrupts a valid bundle and asserts the specific rule
fires, covering each check the F007 specification lists.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from eds.domain.commerce.enums import PaymentStatus
from eds.generators.commerce.payments import PaymentData
from eds.validation.issues import ValidationError, ValidationIssue
from eds.validation.payment_validation import (
    assert_valid_payment_data,
    validate_order_coverage,
    validate_payment_amounts,
    validate_payment_data,
    validate_payment_method,
    validate_payment_references,
    validate_payment_status_history,
    validate_payment_timeline,
)


@pytest.fixture
def datasets(
    payment_data: PaymentData, payment_upstream: dict[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Return a mutable bundle of the payment datasets plus upstream data."""
    return {**payment_upstream, **payment_data.datasets}


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
    assert validate_payment_data(datasets) == []


def test_assert_valid_passes_on_clean_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper does not raise for valid data."""
    assert_valid_payment_data(datasets)


def test_assert_valid_raises_on_broken_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper reports what it found."""
    datasets["payments"] = datasets["payments"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("payment_id")
    )

    with pytest.raises(ValidationError):
        assert_valid_payment_data(datasets)


# --------------------------------------------------------------------------
# Duplicates and references
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dataset", "column"),
    [
        ("payments", "payment_id"),
        ("payment_status_history", "history_id"),
    ],
)
def test_duplicate_primary_keys_are_detected(
    datasets: dict[str, pl.DataFrame], dataset: str, column: str
) -> None:
    """Each dataset's identifier is a primary key."""
    datasets[dataset] = datasets[dataset].with_columns(pl.lit(1).cast(pl.Int64).alias(column))

    assert "duplicate_primary_key" in rules(validate_payment_data(datasets))


def test_duplicate_payment_reference_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The business identifier is never reused."""
    datasets["payments"] = datasets["payments"].with_columns(
        pl.lit("PAY-20250101-000001").alias("payment_reference")
    )

    assert "duplicate_unique_column" in rules(validate_payment_data(datasets))


def test_two_payments_for_one_order_are_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """An order is paid for exactly once in F007."""
    first = datasets["payments"]["order_id"][0]
    datasets["payments"] = datasets["payments"].with_columns(
        pl.lit(first).cast(pl.Int64).alias("order_id")
    )

    found = rules(validate_payment_data(datasets))

    assert "duplicate_unique_column" in found
    assert "multiple_payments_per_order" in found


def test_unknown_order_reference_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A payment must point at a real order."""
    datasets["payments"] = datasets["payments"].with_columns(
        pl.lit(-1).cast(pl.Int64).alias("order_id")
    )

    assert "orphan_reference" in rules(validate_payment_data(datasets))


def test_unknown_payment_reference_in_history_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A history row must point at a real payment."""
    datasets["payment_status_history"] = datasets["payment_status_history"].with_columns(
        pl.lit(-1).cast(pl.Int64).alias("payment_id")
    )

    assert "orphan_reference" in rules(validate_payment_data(datasets))


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------


def test_a_payable_order_without_a_payment_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Every order billed above zero is charged."""
    payments = datasets["payments"].slice(1)

    issues = validate_order_coverage(payments, datasets["orders"])

    assert "payable_order_without_payment" in rules(issues)


def test_a_payment_for_an_unpayable_order_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """An order billed at zero is never charged."""
    orders = datasets["orders"].with_columns(pl.lit(0.0).alias("total_amount"))

    issues = validate_order_coverage(datasets["payments"], orders)

    assert "payment_for_unpayable_order" in rules(issues)


def test_a_customer_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The payer is whoever placed the order."""
    datasets["payments"] = datasets["payments"].with_columns(
        (pl.col("customer_id") + 1).alias("customer_id")
    )

    assert "customer_mismatch" in rules(validate_payment_data(datasets))


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------


def test_a_recalculated_amount_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """ADR-007: the amount is copied, not recomputed."""
    datasets["payments"] = datasets["payments"].with_columns(
        (pl.col("payment_amount") + 0.01).alias("payment_amount")
    )

    assert "amount_not_copied" in rules(validate_payment_data(datasets))


def test_a_non_positive_amount_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A payment for nothing is not a payment."""
    issues = validate_payment_amounts(
        datasets["payments"].with_columns(pl.lit(0.0).alias("payment_amount")),
        datasets["orders"],
    )

    assert "non_positive_amount" in rules(issues)


def test_a_malformed_currency_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The code must be three uppercase letters."""
    datasets["payments"] = datasets["payments"].with_columns(pl.lit("usd").alias("currency"))

    assert "malformed_currency" in rules(validate_payment_data(datasets))


def test_mixed_currencies_are_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """F007 is single-currency by design."""
    datasets["payments"] = datasets["payments"].with_columns(
        pl.when(pl.col("payment_id") == 1)
        .then(pl.lit("EUR"))
        .otherwise(pl.col("currency"))
        .alias("currency")
    )

    assert "mixed_currency" in rules(validate_payment_data(datasets))


# --------------------------------------------------------------------------
# Method and provider
# --------------------------------------------------------------------------


def test_an_unknown_payment_method_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The method comes from the checkout vocabulary."""
    datasets["payments"] = datasets["payments"].with_columns(
        pl.lit("CRYPTO").alias("payment_method")
    )

    assert "unknown_payment_method" in rules(validate_payment_data(datasets))


def test_a_provider_that_does_not_follow_the_method_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """ADR-009: the provider is derived, so it cannot disagree."""
    datasets["payments"] = datasets["payments"].with_columns(
        pl.lit("Stripe").alias("payment_provider")
    )

    assert "provider_mismatch" in rules(validate_payment_data(datasets))


def test_a_method_that_disagrees_with_the_checkout_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The customer's chosen method is the one that gets charged."""
    swapped = {
        "UPI": "WALLET",
        "WALLET": "UPI",
        "CREDIT_CARD": "DEBIT_CARD",
        "DEBIT_CARD": "CREDIT_CARD",
        "NET_BANKING": "COD",
        "COD": "NET_BANKING",
    }
    payments = datasets["payments"].with_columns(
        pl.col("payment_method").replace_strict(swapped).alias("payment_method")
    )

    issues = validate_payment_method(payments, datasets["checkout"], datasets["orders"])

    assert "method_not_copied" in rules(issues)


# --------------------------------------------------------------------------
# References
# --------------------------------------------------------------------------


def test_a_malformed_payment_reference_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The reference reads as PREFIX-YYYYMMDD-NNNNNN."""
    issues = validate_payment_references(
        datasets["payments"].with_columns(pl.lit("not-a-reference").alias("payment_reference"))
    )

    assert "malformed_payment_reference" in rules(issues)


def test_a_malformed_reference_does_not_crash_the_later_checks(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Unparsable text is reported, not raised on."""
    datasets["payments"] = datasets["payments"].with_columns(
        pl.lit("not-a-reference").alias("payment_reference")
    )

    found = rules(validate_payment_data(datasets))

    assert "malformed_payment_reference" in found
    assert "payment_reference_date_mismatch" not in found


def test_a_reference_date_that_disagrees_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The date inside the reference is the day of the attempt."""
    issues = validate_payment_references(
        datasets["payments"].with_columns(pl.lit("PAY-19990101-000001").alias("payment_reference"))
    )

    assert "payment_reference_date_mismatch" in rules(issues)


def test_a_gap_in_the_daily_sequence_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Each day is numbered 1..n without gaps."""
    payments = datasets["payments"].with_columns(
        pl.col("payment_reference").str.slice(0, 13).add("999999").alias("payment_reference")
    )

    assert "payment_reference_not_sequential" in rules(validate_payment_references(payments))


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


def test_a_payment_before_its_order_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Money moves after the order document exists."""
    datasets["payments"] = datasets["payments"].with_columns(
        (pl.col("created_at") - timedelta(days=30)).alias("created_at")
    )

    assert "payment_before_order" in rules(validate_payment_data(datasets))


def test_an_authorisation_before_the_attempt_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The record cannot postdate the authorisation it carries."""
    issues = validate_payment_timeline(
        datasets["payments"].with_columns(
            (pl.col("authorized_at") - timedelta(hours=1)).alias("authorized_at")
        ),
        datasets["orders"],
    )

    assert "authorized_before_created" in rules(issues)


def test_a_capture_before_its_authorisation_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The money is taken after it is held, never before."""
    issues = validate_payment_timeline(
        datasets["payments"].with_columns(
            (pl.col("captured_at") - timedelta(days=1)).alias("captured_at")
        ),
        datasets["orders"],
    )

    assert "captured_before_authorized" in rules(issues)


def test_an_authorised_failure_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A failed payment never reached authorisation."""
    issues = validate_payment_timeline(
        datasets["payments"].with_columns(
            pl.col("created_at").alias("authorized_at"),
            pl.lit(str(PaymentStatus.FAILED)).alias("payment_status"),
        ),
        datasets["orders"],
    )

    assert "authorized_at_inconsistent" in rules(issues)


def test_a_voided_payment_that_captured_money_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Only a captured payment ever took the money."""
    issues = validate_payment_timeline(
        datasets["payments"].with_columns(
            pl.col("created_at").alias("captured_at"),
            pl.lit(str(PaymentStatus.VOIDED)).alias("payment_status"),
        ),
        datasets["orders"],
    )

    assert "captured_at_inconsistent" in rules(issues)


# --------------------------------------------------------------------------
# Status history
# --------------------------------------------------------------------------


def test_an_unknown_status_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Refunds and chargebacks are not F007 statuses."""
    datasets["payment_status_history"] = datasets["payment_status_history"].with_columns(
        pl.lit("REFUNDED").alias("status")
    )

    assert "unknown_status" in rules(validate_payment_data(datasets))


def test_a_sequence_below_one_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Numbering starts at one."""
    datasets["payment_status_history"] = datasets["payment_status_history"].with_columns(
        pl.lit(0).cast(pl.Int64).alias("sequence")
    )

    assert "invalid_sequence" in rules(validate_payment_data(datasets))


def test_a_payment_without_history_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Every payment records how it ended."""
    issues = validate_payment_status_history(
        datasets["payments"], datasets["payment_status_history"].slice(3)
    )

    assert "payment_without_history" in rules(issues)


def test_an_empty_history_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A payments frame with no history at all is reported, not ignored."""
    issues = validate_payment_status_history(
        datasets["payments"], datasets["payment_status_history"].clear()
    )

    assert "payment_without_history" in rules(issues)


def test_a_history_that_moves_backwards_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Time moves forwards with the sequence."""
    datasets["payment_status_history"] = datasets["payment_status_history"].with_columns(
        pl.lit(datetime(2000, 1, 1)).alias("status_timestamp")
    )

    assert "history_out_of_order" in rules(validate_payment_data(datasets))


def test_a_history_that_opens_at_capture_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A payment opens at AUTHORIZED or FAILED, nothing else."""
    history = datasets["payment_status_history"].with_columns(
        pl.when(pl.col("sequence") == 1)
        .then(pl.lit(str(PaymentStatus.CAPTURED)))
        .otherwise(pl.col("status"))
        .alias("status")
    )

    assert "invalid_opening_status" in rules(
        validate_payment_status_history(datasets["payments"], history)
    )


def test_a_transition_the_lifecycle_forbids_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """FAILED is terminal, so nothing may follow it."""
    history = datasets["payment_status_history"].with_columns(
        pl.when(pl.col("sequence") == 2)
        .then(pl.lit(str(PaymentStatus.FAILED)))
        .otherwise(pl.col("status"))
        .alias("status")
    )

    assert "invalid_transition" in rules(
        validate_payment_status_history(datasets["payments"], history)
    )


def test_a_status_that_disagrees_with_the_history_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """ADR-012: the history is the source of truth."""
    datasets["payments"] = datasets["payments"].with_columns(
        pl.lit(str(PaymentStatus.VOIDED)).alias("payment_status")
    )

    assert "payment_status_mismatch" in rules(validate_payment_data(datasets))


def test_history_before_the_payment_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The opening status is not recorded before the attempt."""
    history = datasets["payment_status_history"].with_columns(
        pl.when(pl.col("sequence") == 1)
        .then(pl.col("status_timestamp") - timedelta(days=1))
        .otherwise(pl.col("status_timestamp"))
        .alias("status_timestamp")
    )

    assert "history_before_payment" in rules(
        validate_payment_status_history(datasets["payments"], history)
    )


# --------------------------------------------------------------------------
# Partial bundles
# --------------------------------------------------------------------------


def test_missing_payment_datasets_stop_the_business_rules(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Without the outputs there is nothing to check beyond the schema."""
    del datasets["payments"]

    assert "amount_not_copied" not in rules(validate_payment_data(datasets))


def test_upstream_rules_are_skipped_when_the_upstream_is_absent(
    payment_data: PaymentData,
) -> None:
    """A bare bundle reports the absent parents and nothing else."""
    issues = validate_payment_data(dict(payment_data.datasets))

    assert rules(issues) == {"missing_reference_dataset"}
