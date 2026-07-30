"""Tests for shipment validation.

Every failure path corrupts a valid bundle and asserts the specific rule
fires, covering each check the F008 specification lists.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from eds.config import ShipmentConfig
from eds.domain.commerce.enums import PaymentStatus, ShipmentStatus
from eds.generators.commerce.shipments import ShipmentData
from eds.validation.issues import ValidationError, ValidationIssue
from eds.validation.shipment_validation import (
    assert_valid_shipment_data,
    validate_carrier_assignment,
    validate_item_reconciliation,
    validate_payment_eligibility,
    validate_shipment_data,
    validate_shipment_numbers,
    validate_shipment_status_history,
    validate_shipment_timeline,
)

CARRIERS = ShipmentConfig().carriers


@pytest.fixture
def datasets(
    shipment_data: ShipmentData, shipment_upstream: dict[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Return a mutable bundle of the shipment datasets plus upstream data."""
    return {**shipment_upstream, **shipment_data.datasets}


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
    assert validate_shipment_data(datasets, CARRIERS) == []


def test_assert_valid_passes_on_clean_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper does not raise for valid data."""
    assert_valid_shipment_data(datasets, CARRIERS)


def test_assert_valid_raises_on_broken_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper reports what it found."""
    datasets["shipments"] = datasets["shipments"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("shipment_id")
    )

    with pytest.raises(ValidationError):
        assert_valid_shipment_data(datasets, CARRIERS)


# --------------------------------------------------------------------------
# Duplicates and references
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dataset", "column"),
    [
        ("shipments", "shipment_id"),
        ("shipment_items", "shipment_item_id"),
        ("shipment_status_history", "history_id"),
    ],
)
def test_duplicate_primary_keys_are_detected(
    datasets: dict[str, pl.DataFrame], dataset: str, column: str
) -> None:
    """Each dataset's identifier is a primary key."""
    datasets[dataset] = datasets[dataset].with_columns(pl.lit(1).cast(pl.Int64).alias(column))

    assert "duplicate_primary_key" in rules(validate_shipment_data(datasets, CARRIERS))


@pytest.mark.parametrize("column", ["shipment_number", "tracking_number"])
def test_duplicate_business_identifiers_are_detected(
    datasets: dict[str, pl.DataFrame], column: str
) -> None:
    """Neither business identifier is ever reused."""
    datasets["shipments"] = datasets["shipments"].with_columns(pl.lit("DUP-VALUE").alias(column))

    assert "duplicate_unique_column" in rules(validate_shipment_data(datasets, CARRIERS))


def test_two_shipments_for_one_payment_are_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A payment is shipped exactly once in F008."""
    first = datasets["shipments"]["payment_id"][0]
    datasets["shipments"] = datasets["shipments"].with_columns(
        pl.lit(first).cast(pl.Int64).alias("payment_id")
    )

    found = rules(validate_shipment_data(datasets, CARRIERS))

    assert "duplicate_unique_column" in found
    assert "multiple_shipments_per_payment" in found


def test_duplicate_order_line_in_items_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Split shipments are out of scope, so a line ships once."""
    first = datasets["shipment_items"]["order_line_id"][0]
    datasets["shipment_items"] = datasets["shipment_items"].with_columns(
        pl.lit(first).cast(pl.Int64).alias("order_line_id")
    )

    assert "duplicate_unique_column" in rules(validate_shipment_data(datasets, CARRIERS))


@pytest.mark.parametrize(
    ("dataset", "column"),
    [
        ("shipments", "payment_id"),
        ("shipments", "order_id"),
        ("shipments", "customer_id"),
        ("shipment_items", "shipment_id"),
        ("shipment_items", "order_line_id"),
        ("shipment_items", "product_id"),
        ("shipment_status_history", "shipment_id"),
    ],
)
def test_unknown_references_are_detected(
    datasets: dict[str, pl.DataFrame], dataset: str, column: str
) -> None:
    """Every declared foreign key is checked."""
    datasets[dataset] = datasets[dataset].with_columns(pl.lit(-1).cast(pl.Int64).alias(column))

    assert "orphan_reference" in rules(validate_shipment_data(datasets, CARRIERS))


# --------------------------------------------------------------------------
# Payment eligibility
# --------------------------------------------------------------------------


def test_a_shipment_on_an_uncaptured_payment_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Only a CAPTURED payment produces a shipment."""
    payments = datasets["payments"].with_columns(
        pl.lit(str(PaymentStatus.VOIDED)).alias("payment_status")
    )

    issues = validate_payment_eligibility(datasets["shipments"], payments)

    assert "invalid_payment_status" in rules(issues)


def test_a_captured_payment_without_a_shipment_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Every captured payment ships."""
    issues = validate_payment_eligibility(datasets["shipments"].slice(1), datasets["payments"])

    assert "captured_payment_without_shipment" in rules(issues)


def test_an_order_mismatch_against_the_payment_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The shipment ships the order that was paid for."""
    datasets["shipments"] = datasets["shipments"].with_columns(
        (pl.col("customer_id") + 1).alias("customer_id")
    )

    assert "payment_field_mismatch" in rules(validate_shipment_data(datasets, CARRIERS))


# --------------------------------------------------------------------------
# Carrier and method
# --------------------------------------------------------------------------


def test_a_method_that_disagrees_with_the_checkout_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The customer's chosen method is the one that ships."""
    swapped = {
        "STANDARD": "EXPRESS",
        "EXPRESS": "STANDARD",
        "NEXT_DAY": "STORE_PICKUP",
        "STORE_PICKUP": "NEXT_DAY",
    }
    shipments = datasets["shipments"].with_columns(
        pl.col("shipping_method").replace_strict(swapped).alias("shipping_method")
    )

    issues = validate_carrier_assignment(
        shipments, datasets["checkout"], datasets["orders"], CARRIERS
    )

    assert "shipping_method_not_copied" in rules(issues)


def test_a_carrier_the_method_does_not_offer_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Carrier selection depends on the shipping method."""
    datasets["shipments"] = datasets["shipments"].with_columns(
        pl.lit("Royal Mail").alias("carrier")
    )

    assert "carrier_not_offered_for_method" in rules(validate_shipment_data(datasets, CARRIERS))


def test_an_empty_carrier_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Every shipment has somebody carrying it."""
    datasets["shipments"] = datasets["shipments"].with_columns(pl.lit("").alias("carrier"))

    assert "missing_carrier" in rules(validate_shipment_data(datasets, CARRIERS))


def test_the_carrier_check_is_skipped_without_the_configuration(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Nothing but the configuration knows which carriers were on offer."""
    datasets["shipments"] = datasets["shipments"].with_columns(
        pl.lit("Royal Mail").alias("carrier")
    )

    assert "carrier_not_offered_for_method" not in rules(validate_shipment_data(datasets))


# --------------------------------------------------------------------------
# Identifiers
# --------------------------------------------------------------------------


def test_a_malformed_shipment_number_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The number reads as PREFIX-YYYYMMDD-NNNNNN."""
    issues = validate_shipment_numbers(
        datasets["shipments"].with_columns(pl.lit("not-a-number").alias("shipment_number"))
    )

    assert "malformed_shipment_number" in rules(issues)


def test_a_malformed_number_does_not_crash_the_later_checks(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Unparsable text is reported, not raised on."""
    datasets["shipments"] = datasets["shipments"].with_columns(
        pl.lit("not-a-number").alias("shipment_number")
    )

    found = rules(validate_shipment_data(datasets, CARRIERS))

    assert "malformed_shipment_number" in found
    assert "shipment_number_date_mismatch" not in found


def test_a_malformed_tracking_number_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The tracking number reads as TRK-XXXXXXXXXX."""
    issues = validate_shipment_numbers(
        datasets["shipments"].with_columns(pl.lit("TRK-123").alias("tracking_number"))
    )

    assert "malformed_tracking_number" in rules(issues)


def test_a_number_date_that_disagrees_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The date inside the number is the day the shipment was created."""
    issues = validate_shipment_numbers(
        datasets["shipments"].with_columns(pl.lit("SHP-19990101-000001").alias("shipment_number"))
    )

    assert "shipment_number_date_mismatch" in rules(issues)


def test_a_gap_in_the_daily_sequence_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Each day is numbered 1..n without gaps."""
    shipments = datasets["shipments"].with_columns(
        pl.col("shipment_number").str.slice(0, 13).add("999999").alias("shipment_number")
    )

    assert "shipment_number_not_sequential" in rules(validate_shipment_numbers(shipments))


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


def test_a_shipment_before_its_payment_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Goods move after the money did."""
    datasets["shipments"] = datasets["shipments"].with_columns(
        (pl.col("created_at") - timedelta(days=30)).alias("created_at")
    )

    assert "shipment_before_payment" in rules(validate_shipment_data(datasets, CARRIERS))


def test_a_dispatch_before_creation_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A shipment is dispatched after it is created."""
    issues = validate_shipment_timeline(
        datasets["shipments"].with_columns(
            (pl.col("created_at") - timedelta(hours=1)).alias("shipped_at")
        ),
        datasets["payments"],
    )

    assert "shipped_before_created" in rules(issues)


def test_a_delivery_before_dispatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """delivered_at must be after shipped_at."""
    issues = validate_shipment_timeline(
        datasets["shipments"].with_columns(
            (pl.col("shipped_at") - timedelta(days=1)).alias("delivered_at")
        ),
        datasets["payments"],
    )

    assert "delivered_before_shipped" in rules(issues)


def test_an_estimate_before_creation_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The promise is made when the shipment is created."""
    issues = validate_shipment_timeline(
        datasets["shipments"].with_columns(
            (pl.col("created_at") - timedelta(days=1)).alias("estimated_delivery_at")
        ),
        datasets["payments"],
    )

    assert "estimate_before_created" in rules(issues)


def test_a_dispatched_shipment_without_a_dispatch_time_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A SHIPPED parcel has left, so it has a dispatch time."""
    issues = validate_shipment_timeline(
        datasets["shipments"].with_columns(
            pl.lit(None, dtype=pl.Datetime("us")).alias("shipped_at")
        ),
        datasets["payments"],
    )

    assert "shipped_at_inconsistent" in rules(issues)


def test_an_undelivered_shipment_with_a_delivery_time_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A parcel still in transit has not arrived."""
    issues = validate_shipment_timeline(
        datasets["shipments"].with_columns(
            pl.lit(str(ShipmentStatus.IN_TRANSIT)).alias("current_status")
        ),
        datasets["payments"],
    )

    assert "delivered_at_inconsistent" in rules(issues)


# --------------------------------------------------------------------------
# Item reconciliation
# --------------------------------------------------------------------------


def test_a_non_positive_quantity_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Shipping nothing is not shipping."""
    issues = validate_item_reconciliation(
        datasets["shipments"],
        datasets["shipment_items"].with_columns(pl.lit(0).cast(pl.Int64).alias("quantity")),
        datasets["order_lines"],
    )

    assert "non_positive_quantity" in rules(issues)


def test_a_line_from_another_order_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """An item never carries somebody else's order line."""
    lines = datasets["order_lines"].with_columns((pl.col("order_id") + 1).alias("order_id"))

    issues = validate_item_reconciliation(datasets["shipments"], datasets["shipment_items"], lines)

    assert "line_from_another_order" in rules(issues)


def test_a_quantity_that_disagrees_with_the_line_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """No partial shipments, so the whole line goes out."""
    datasets["shipment_items"] = datasets["shipment_items"].with_columns(
        (pl.col("quantity") + 1).alias("quantity")
    )

    assert "quantity_mismatch" in rules(validate_shipment_data(datasets, CARRIERS))


def test_a_product_that_disagrees_with_the_line_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The item ships what the line ordered."""
    first = datasets["shipment_items"]["product_id"][0]
    items = datasets["shipment_items"].with_columns(
        pl.lit(first).cast(pl.Int64).alias("product_id")
    )

    issues = validate_item_reconciliation(datasets["shipments"], items, datasets["order_lines"])

    assert "product_mismatch" in rules(issues)


def test_an_order_line_left_behind_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Split shipments and backorders are out of scope."""
    issues = validate_item_reconciliation(
        datasets["shipments"], datasets["shipment_items"].slice(1), datasets["order_lines"]
    )

    assert "order_line_not_shipped" in rules(issues)


def test_an_item_created_before_its_shipment_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The item exists as soon as the shipment does, never sooner."""
    issues = validate_item_reconciliation(
        datasets["shipments"],
        datasets["shipment_items"].with_columns(
            (pl.col("created_at") - timedelta(days=1)).alias("created_at")
        ),
        datasets["order_lines"],
    )

    assert "item_before_shipment" in rules(issues)


# --------------------------------------------------------------------------
# Status history
# --------------------------------------------------------------------------


def test_an_unknown_status_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """RETURNED, LOST and DAMAGED are not F008 statuses."""
    datasets["shipment_status_history"] = datasets["shipment_status_history"].with_columns(
        pl.lit("RETURNED").alias("status")
    )

    assert "unknown_status" in rules(validate_shipment_data(datasets, CARRIERS))


def test_a_sequence_below_one_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Numbering starts at one."""
    datasets["shipment_status_history"] = datasets["shipment_status_history"].with_columns(
        pl.lit(0).cast(pl.Int64).alias("sequence")
    )

    assert "invalid_sequence" in rules(validate_shipment_data(datasets, CARRIERS))


def test_a_shipment_without_history_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Every shipment records how far it got."""
    issues = validate_shipment_status_history(
        datasets["shipments"], datasets["shipment_status_history"].slice(6)
    )

    assert "shipment_without_history" in rules(issues)


def test_an_empty_history_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A shipments frame with no history at all is reported, not ignored."""
    issues = validate_shipment_status_history(
        datasets["shipments"], datasets["shipment_status_history"].clear()
    )

    assert "shipment_without_history" in rules(issues)


def test_a_history_that_moves_backwards_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Time moves forwards with the sequence."""
    datasets["shipment_status_history"] = datasets["shipment_status_history"].with_columns(
        pl.lit(datetime(2000, 1, 1)).alias("status_timestamp")
    )

    assert "history_out_of_order" in rules(validate_shipment_data(datasets, CARRIERS))


def test_a_history_that_does_not_start_at_created_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Every history opens at CREATED."""
    history = datasets["shipment_status_history"].with_columns(
        pl.when(pl.col("sequence") == 1)
        .then(pl.lit(str(ShipmentStatus.PACKED)))
        .otherwise(pl.col("status"))
        .alias("status")
    )

    found = rules(validate_shipment_status_history(datasets["shipments"], history))

    assert "lifecycle_does_not_start_at_created" in found


def test_a_lifecycle_that_runs_backwards_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Position must advance in step with the sequence."""
    history = datasets["shipment_status_history"].with_columns(
        pl.when(pl.col("sequence") == 2)
        .then(pl.lit(str(ShipmentStatus.CREATED)))
        .otherwise(pl.col("status"))
        .alias("status")
    )

    assert "lifecycle_out_of_order" in rules(
        validate_shipment_status_history(datasets["shipments"], history)
    )


def test_a_status_that_disagrees_with_the_history_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """ADR-012: the history is the source of truth."""
    datasets["shipments"] = datasets["shipments"].with_columns(
        pl.lit(str(ShipmentStatus.PACKED)).alias("current_status")
    )

    assert "current_status_mismatch" in rules(validate_shipment_data(datasets, CARRIERS))


def test_a_timeline_column_that_disagrees_with_the_history_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """shipped_at is denormalised from the history, not maintained apart."""
    shipments = datasets["shipments"].with_columns(
        (pl.col("shipped_at") + timedelta(minutes=5)).alias("shipped_at")
    )

    assert "timeline_history_mismatch" in rules(
        validate_shipment_status_history(shipments, datasets["shipment_status_history"])
    )


def test_history_before_the_shipment_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The opening status is not recorded before the shipment."""
    history = datasets["shipment_status_history"].with_columns(
        pl.when(pl.col("sequence") == 1)
        .then(pl.col("status_timestamp") - timedelta(days=1))
        .otherwise(pl.col("status_timestamp"))
        .alias("status_timestamp")
    )

    assert "history_before_shipment" in rules(
        validate_shipment_status_history(datasets["shipments"], history)
    )


# --------------------------------------------------------------------------
# Partial bundles
# --------------------------------------------------------------------------


def test_missing_shipment_datasets_stop_the_business_rules(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Without the outputs there is nothing to check beyond the schema."""
    del datasets["shipments"]

    assert "invalid_payment_status" not in rules(validate_shipment_data(datasets, CARRIERS))


def test_upstream_rules_are_skipped_when_the_upstream_is_absent(
    shipment_data: ShipmentData,
) -> None:
    """A bare bundle reports the absent parents and nothing else."""
    issues = validate_shipment_data(dict(shipment_data.datasets), CARRIERS)

    assert rules(issues) == {"missing_reference_dataset"}
