"""Tests for return validation.

Every failure path corrupts a valid bundle and asserts the specific rule
fires, covering each check the F009 specification lists.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from eds.config import DEFAULT_REFUND_TYPES
from eds.domain.commerce.enums import ReturnStatus, ShipmentStatus
from eds.generators.commerce.returns import ReturnData
from eds.validation.issues import ValidationError, ValidationIssue
from eds.validation.return_validation import (
    assert_valid_return_data,
    validate_item_reconciliation,
    validate_refund_types,
    validate_return_data,
    validate_return_numbers,
    validate_return_status_history,
    validate_return_timeline,
    validate_shipment_eligibility,
)

REFUND_TYPES = DEFAULT_REFUND_TYPES


@pytest.fixture
def datasets(
    return_data: ReturnData, return_upstream: dict[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Return a mutable bundle of the return datasets plus upstream data."""
    return {**return_upstream, **return_data.datasets}


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
    assert validate_return_data(datasets, REFUND_TYPES) == []


def test_assert_valid_passes_on_clean_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper does not raise for valid data."""
    assert_valid_return_data(datasets, REFUND_TYPES)


def test_assert_valid_raises_on_broken_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper reports what it found."""
    datasets["returns"] = datasets["returns"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("return_id")
    )

    with pytest.raises(ValidationError):
        assert_valid_return_data(datasets, REFUND_TYPES)


# --------------------------------------------------------------------------
# Duplicates and references
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dataset", "column"),
    [
        ("returns", "return_id"),
        ("return_items", "return_item_id"),
        ("return_status_history", "history_id"),
    ],
)
def test_duplicate_primary_keys_are_detected(
    datasets: dict[str, pl.DataFrame], dataset: str, column: str
) -> None:
    """Each dataset's identifier is a primary key."""
    datasets[dataset] = datasets[dataset].with_columns(pl.lit(1).cast(pl.Int64).alias(column))

    assert "duplicate_primary_key" in rules(validate_return_data(datasets, REFUND_TYPES))


def test_duplicate_return_number_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The business identifier is never reused."""
    datasets["returns"] = datasets["returns"].with_columns(
        pl.lit("RET-20250101-000001").alias("return_number")
    )

    assert "duplicate_unique_column" in rules(validate_return_data(datasets, REFUND_TYPES))


def test_two_returns_for_one_shipment_are_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A shipment is sent back once, not repeatedly."""
    first = datasets["returns"]["shipment_id"][0]
    datasets["returns"] = datasets["returns"].with_columns(
        pl.lit(first).cast(pl.Int64).alias("shipment_id")
    )

    found = rules(validate_return_data(datasets, REFUND_TYPES))

    assert "duplicate_unique_column" in found
    assert "multiple_returns_per_shipment" in found


def test_duplicate_shipment_item_in_items_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A shipped item comes back at most once."""
    first = datasets["return_items"]["shipment_item_id"][0]
    datasets["return_items"] = datasets["return_items"].with_columns(
        pl.lit(first).cast(pl.Int64).alias("shipment_item_id")
    )

    assert "duplicate_unique_column" in rules(validate_return_data(datasets, REFUND_TYPES))


@pytest.mark.parametrize(
    ("dataset", "column"),
    [
        ("returns", "shipment_id"),
        ("returns", "customer_id"),
        ("return_items", "return_id"),
        ("return_items", "shipment_item_id"),
        ("return_items", "order_line_id"),
        ("return_items", "product_id"),
        ("return_status_history", "return_id"),
    ],
)
def test_unknown_references_are_detected(
    datasets: dict[str, pl.DataFrame], dataset: str, column: str
) -> None:
    """Every declared foreign key is checked."""
    datasets[dataset] = datasets[dataset].with_columns(pl.lit(-1).cast(pl.Int64).alias(column))

    assert "orphan_reference" in rules(validate_return_data(datasets, REFUND_TYPES))


def test_an_unknown_return_reason_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The reason must exist in the F001 master table."""
    datasets["returns"] = datasets["returns"].with_columns(
        pl.lit("MADE_UP_REASON").alias("return_reason")
    )

    assert "orphan_reference" in rules(validate_return_data(datasets, REFUND_TYPES))


# --------------------------------------------------------------------------
# Shipment eligibility
# --------------------------------------------------------------------------


def test_a_return_on_an_undelivered_shipment_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Only a DELIVERED shipment produces a return."""
    shipments = datasets["shipments"].with_columns(
        pl.lit(str(ShipmentStatus.IN_TRANSIT)).alias("current_status")
    )

    issues = validate_shipment_eligibility(datasets["returns"], shipments)

    assert "invalid_shipment_status" in rules(issues)


def test_a_customer_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The returner is whoever received the shipment."""
    datasets["returns"] = datasets["returns"].with_columns(
        (pl.col("customer_id") + 1).alias("customer_id")
    )

    assert "customer_mismatch" in rules(validate_return_data(datasets, REFUND_TYPES))


# --------------------------------------------------------------------------
# Refund type
# --------------------------------------------------------------------------


def test_an_unknown_refund_type_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Settlement is configuration driven."""
    datasets["returns"] = datasets["returns"].with_columns(pl.lit("CRYPTO").alias("refund_type"))

    assert "unknown_refund_type" in rules(validate_return_data(datasets, REFUND_TYPES))


def test_an_empty_refund_type_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Every return is settled somehow."""
    issues = validate_refund_types(
        datasets["returns"].with_columns(pl.lit("").alias("refund_type")), REFUND_TYPES
    )

    assert "missing_refund_type" in rules(issues)


def test_the_refund_check_is_skipped_without_the_configuration(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Nothing but the configuration knows which types were on offer."""
    datasets["returns"] = datasets["returns"].with_columns(pl.lit("CRYPTO").alias("refund_type"))

    assert "unknown_refund_type" not in rules(validate_return_data(datasets))


# --------------------------------------------------------------------------
# Return numbers
# --------------------------------------------------------------------------


def test_a_malformed_return_number_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The number reads as PREFIX-YYYYMMDD-NNNNNN."""
    issues = validate_return_numbers(
        datasets["returns"].with_columns(pl.lit("not-a-number").alias("return_number"))
    )

    assert "malformed_return_number" in rules(issues)


def test_a_malformed_number_does_not_crash_the_later_checks(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Unparsable text is reported, not raised on."""
    datasets["returns"] = datasets["returns"].with_columns(
        pl.lit("not-a-number").alias("return_number")
    )

    found = rules(validate_return_data(datasets, REFUND_TYPES))

    assert "malformed_return_number" in found
    assert "return_number_date_mismatch" not in found


def test_a_number_date_that_disagrees_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The date inside the number is the day of the request."""
    issues = validate_return_numbers(
        datasets["returns"].with_columns(pl.lit("RET-19990101-000001").alias("return_number"))
    )

    assert "return_number_date_mismatch" in rules(issues)


def test_a_gap_in_the_daily_sequence_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Each day is numbered 1..n without gaps."""
    returns = datasets["returns"].with_columns(
        pl.col("return_number").str.slice(0, 13).add("999999").alias("return_number")
    )

    assert "return_number_not_sequential" in rules(validate_return_numbers(returns))


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


def test_a_return_before_delivery_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """requested_at must be after shipment.delivered_at."""
    datasets["returns"] = datasets["returns"].with_columns(
        (pl.col("requested_at") - timedelta(days=365)).alias("requested_at"),
        (pl.col("created_at") - timedelta(days=365)).alias("created_at"),
    )

    assert "return_before_delivery" in rules(validate_return_data(datasets, REFUND_TYPES))


def test_a_created_at_that_disagrees_with_the_request_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The document exists as soon as the customer asks."""
    issues = validate_return_timeline(
        datasets["returns"].with_columns(
            (pl.col("created_at") + timedelta(hours=1)).alias("created_at")
        ),
        datasets["shipments"],
    )

    assert "created_at_mismatch" in rules(issues)


@pytest.mark.parametrize(
    ("earlier", "later"),
    [
        ("requested_at", "approved_at"),
        ("approved_at", "received_at"),
        ("received_at", "completed_at"),
    ],
)
def test_a_stage_that_precedes_the_one_before_it_is_detected(
    datasets: dict[str, pl.DataFrame], earlier: str, later: str
) -> None:
    """Request, approval, receipt and completion happen in order."""
    issues = validate_return_timeline(
        datasets["returns"].with_columns(
            pl.when(pl.col(later).is_not_null())
            .then(pl.col(earlier) - timedelta(days=1))
            .otherwise(pl.col(later))
            .alias(later)
        ),
        datasets["shipments"],
    )

    assert "timeline_out_of_order" in rules(issues)


def test_an_unreached_stage_with_a_timestamp_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A return still in transit has not been received."""
    issues = validate_return_timeline(
        datasets["returns"].with_columns(
            pl.lit(str(ReturnStatus.IN_TRANSIT)).alias("current_status")
        ),
        datasets["shipments"],
    )

    assert "timestamp_inconsistent" in rules(issues)


# --------------------------------------------------------------------------
# Item reconciliation
# --------------------------------------------------------------------------


def test_a_non_positive_quantity_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Returning nothing is not returning."""
    issues = validate_item_reconciliation(
        datasets["returns"],
        datasets["return_items"].with_columns(pl.lit(0).cast(pl.Int64).alias("quantity")),
        datasets["shipment_items"],
    )

    assert "non_positive_quantity" in rules(issues)


def test_an_item_from_another_shipment_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """An item never comes back from somebody else's shipment."""
    shipment_items = datasets["shipment_items"].with_columns(
        (pl.col("shipment_id") + 1).alias("shipment_id")
    )

    issues = validate_item_reconciliation(
        datasets["returns"], datasets["return_items"], shipment_items
    )

    assert "item_from_another_shipment" in rules(issues)


@pytest.mark.parametrize("column", ["order_line_id", "product_id", "quantity"])
def test_altered_lineage_is_detected(datasets: dict[str, pl.DataFrame], column: str) -> None:
    """Lineage is carried across from the shipment item unchanged."""
    issues = validate_item_reconciliation(
        datasets["returns"],
        datasets["return_items"].with_columns((pl.col(column) + 1).alias(column)),
        datasets["shipment_items"],
    )

    assert "lineage_not_preserved" in rules(issues)


def test_a_return_with_no_items_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A return of nothing is not a return."""
    dropped = datasets["return_items"]["return_id"][0]
    issues = validate_item_reconciliation(
        datasets["returns"],
        datasets["return_items"].filter(pl.col("return_id") != dropped),
        datasets["shipment_items"],
    )

    assert "return_without_items" in rules(issues)


def test_an_item_created_before_its_return_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The item exists as soon as the return does, never sooner."""
    issues = validate_item_reconciliation(
        datasets["returns"],
        datasets["return_items"].with_columns(
            (pl.col("created_at") - timedelta(days=1)).alias("created_at")
        ),
        datasets["shipment_items"],
    )

    assert "item_before_return" in rules(issues)


# --------------------------------------------------------------------------
# Status history
# --------------------------------------------------------------------------


def test_an_unknown_status_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """REJECTED, CANCELLED and REFUNDED are not F009 statuses."""
    datasets["return_status_history"] = datasets["return_status_history"].with_columns(
        pl.lit("REFUNDED").alias("status")
    )

    assert "unknown_status" in rules(validate_return_data(datasets, REFUND_TYPES))


def test_a_sequence_below_one_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Numbering starts at one."""
    datasets["return_status_history"] = datasets["return_status_history"].with_columns(
        pl.lit(0).cast(pl.Int64).alias("sequence")
    )

    assert "invalid_sequence" in rules(validate_return_data(datasets, REFUND_TYPES))


def test_a_return_without_history_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Every return records how far it got."""
    issues = validate_return_status_history(
        datasets["returns"], datasets["return_status_history"].slice(6)
    )

    assert "return_without_history" in rules(issues)


def test_an_empty_history_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A returns frame with no history at all is reported, not ignored."""
    issues = validate_return_status_history(
        datasets["returns"], datasets["return_status_history"].clear()
    )

    assert "return_without_history" in rules(issues)


def test_a_history_that_moves_backwards_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Time moves forwards with the sequence."""
    datasets["return_status_history"] = datasets["return_status_history"].with_columns(
        pl.lit(datetime(2000, 1, 1)).alias("status_timestamp")
    )

    assert "history_out_of_order" in rules(validate_return_data(datasets, REFUND_TYPES))


def test_a_history_that_does_not_start_at_requested_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Every history opens at REQUESTED."""
    history = datasets["return_status_history"].with_columns(
        pl.when(pl.col("sequence") == 1)
        .then(pl.lit(str(ReturnStatus.APPROVED)))
        .otherwise(pl.col("status"))
        .alias("status")
    )

    assert "lifecycle_does_not_start_at_requested" in rules(
        validate_return_status_history(datasets["returns"], history)
    )


def test_a_lifecycle_that_runs_backwards_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Position must advance in step with the sequence."""
    history = datasets["return_status_history"].with_columns(
        pl.when(pl.col("sequence") == 2)
        .then(pl.lit(str(ReturnStatus.REQUESTED)))
        .otherwise(pl.col("status"))
        .alias("status")
    )

    assert "lifecycle_out_of_order" in rules(
        validate_return_status_history(datasets["returns"], history)
    )


def test_a_status_that_disagrees_with_the_history_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """ADR-012: the history is the source of truth."""
    datasets["returns"] = datasets["returns"].with_columns(
        pl.lit(str(ReturnStatus.IN_TRANSIT)).alias("current_status")
    )

    assert "current_status_mismatch" in rules(validate_return_data(datasets, REFUND_TYPES))


def test_a_timeline_column_that_disagrees_with_the_history_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """approved_at is denormalised from the history, not maintained apart."""
    returns = datasets["returns"].with_columns(
        (pl.col("approved_at") + timedelta(minutes=5)).alias("approved_at")
    )

    assert "timeline_history_mismatch" in rules(
        validate_return_status_history(returns, datasets["return_status_history"])
    )


# --------------------------------------------------------------------------
# Partial bundles
# --------------------------------------------------------------------------


def test_missing_return_datasets_stop_the_business_rules(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Without the outputs there is nothing to check beyond the schema."""
    del datasets["returns"]

    assert "invalid_shipment_status" not in rules(validate_return_data(datasets, REFUND_TYPES))


def test_upstream_rules_are_skipped_when_the_upstream_is_absent(
    return_data: ReturnData,
) -> None:
    """A bare bundle reports the absent parents and nothing else."""
    issues = validate_return_data(dict(return_data.datasets), REFUND_TYPES)

    assert rules(issues) == {"missing_reference_dataset"}
