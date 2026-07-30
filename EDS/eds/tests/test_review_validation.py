"""Tests for review validation.

Every failure path corrupts a valid bundle and asserts the specific rule
fires, covering each check the F010 specification lists.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl
import pytest

from eds.config import DEFAULT_REVIEW_TEXTS, DEFAULT_REVIEW_TITLES
from eds.domain.commerce.enums import ShipmentStatus
from eds.generators.commerce.reviews import ReviewData
from eds.validation.issues import ValidationError, ValidationIssue
from eds.validation.review_validation import (
    assert_valid_review_data,
    validate_review_content,
    validate_review_data,
    validate_review_eligibility,
    validate_review_numbers,
    validate_review_ratings,
    validate_review_timeline,
)

TITLES = DEFAULT_REVIEW_TITLES
TEXTS = DEFAULT_REVIEW_TEXTS


@pytest.fixture
def datasets(
    review_data: ReviewData, review_upstream: dict[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Return a mutable bundle of the review dataset plus upstream data."""
    return {**review_upstream, **review_data.datasets}


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
    assert validate_review_data(datasets, TITLES, TEXTS) == []


def test_assert_valid_passes_on_clean_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper does not raise for valid data."""
    assert_valid_review_data(datasets, TITLES, TEXTS)


def test_assert_valid_raises_on_broken_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper reports what it found."""
    datasets["reviews"] = datasets["reviews"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("review_id")
    )

    with pytest.raises(ValidationError):
        assert_valid_review_data(datasets, TITLES, TEXTS)


# --------------------------------------------------------------------------
# Duplicates and references
# --------------------------------------------------------------------------


def test_duplicate_review_id_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The identifier is a primary key."""
    datasets["reviews"] = datasets["reviews"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("review_id")
    )

    assert "duplicate_primary_key" in rules(validate_review_data(datasets, TITLES, TEXTS))


def test_duplicate_review_number_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The business identifier is never reused."""
    datasets["reviews"] = datasets["reviews"].with_columns(
        pl.lit("REV-20250101-000001").alias("review_number")
    )

    assert "duplicate_unique_column" in rules(validate_review_data(datasets, TITLES, TEXTS))


def test_two_reviews_for_one_item_are_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """An item is reviewed once, not repeatedly."""
    first = datasets["reviews"]["shipment_item_id"][0]
    datasets["reviews"] = datasets["reviews"].with_columns(
        pl.lit(first).cast(pl.Int64).alias("shipment_item_id")
    )

    found = rules(validate_review_data(datasets, TITLES, TEXTS))

    assert "duplicate_unique_column" in found
    assert "multiple_reviews_per_item" in found


@pytest.mark.parametrize(
    "column",
    ["shipment_item_id", "shipment_id", "order_id", "product_id", "customer_id"],
)
def test_unknown_references_are_detected(datasets: dict[str, pl.DataFrame], column: str) -> None:
    """Every declared foreign key is checked."""
    datasets["reviews"] = datasets["reviews"].with_columns(pl.lit(-1).cast(pl.Int64).alias(column))

    assert "orphan_reference" in rules(validate_review_data(datasets, TITLES, TEXTS))


# --------------------------------------------------------------------------
# Eligibility
# --------------------------------------------------------------------------


def test_a_review_on_an_undelivered_shipment_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Only a DELIVERED shipment produces a review."""
    shipments = datasets["shipments"].with_columns(
        pl.lit(str(ShipmentStatus.IN_TRANSIT)).alias("current_status")
    )

    issues = validate_review_eligibility(
        datasets["reviews"], shipments, datasets["shipment_items"], datasets["return_items"]
    )

    assert "invalid_shipment_status" in rules(issues)


def test_a_review_on_a_returned_item_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """An item the customer sent back is no longer theirs to comment on."""
    returned = datasets["reviews"].select("shipment_item_id").head(3)

    issues = validate_review_eligibility(
        datasets["reviews"], datasets["shipments"], datasets["shipment_items"], returned
    )

    assert "returned_item_reviewed" in rules(issues)


@pytest.mark.parametrize("column", ["order_id", "customer_id"])
def test_a_shipment_field_mismatch_is_detected(
    datasets: dict[str, pl.DataFrame], column: str
) -> None:
    """The order and customer come from the shipment the item arrived in."""
    datasets["reviews"] = datasets["reviews"].with_columns((pl.col(column) + 1).alias(column))

    assert "shipment_field_mismatch" in rules(validate_review_data(datasets, TITLES, TEXTS))


def test_a_product_that_disagrees_with_the_item_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The product is whatever the shipment item carried."""
    issues = validate_review_eligibility(
        datasets["reviews"].with_columns((pl.col("product_id") + 1).alias("product_id")),
        datasets["shipments"],
        datasets["shipment_items"],
        datasets["return_items"],
    )

    assert "product_mismatch" in rules(issues)


def test_a_shipment_that_disagrees_with_the_item_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The review's shipment is the one its item belongs to."""
    items = datasets["shipment_items"].with_columns(
        (pl.col("shipment_id") + 1).alias("shipment_id")
    )

    issues = validate_review_eligibility(
        datasets["reviews"], datasets["shipments"], items, datasets["return_items"]
    )

    assert "shipment_item_mismatch" in rules(issues)


# --------------------------------------------------------------------------
# Rating and content
# --------------------------------------------------------------------------


@pytest.mark.parametrize("rating", [0, 6, -1])
def test_a_rating_out_of_range_is_detected(datasets: dict[str, pl.DataFrame], rating: int) -> None:
    """Stars run from one to five."""
    issues = validate_review_ratings(
        datasets["reviews"].with_columns(pl.lit(rating).cast(pl.Int64).alias("rating"))
    )

    assert "rating_out_of_range" in rules(issues)


def test_an_unverified_purchase_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Every review comes from a delivered shipment."""
    datasets["reviews"] = datasets["reviews"].with_columns(pl.lit(False).alias("verified_purchase"))

    assert "unverified_purchase" in rules(validate_review_data(datasets, TITLES, TEXTS))


@pytest.mark.parametrize("column", ["review_title", "review_text"])
def test_empty_wording_is_detected(datasets: dict[str, pl.DataFrame], column: str) -> None:
    """Every review says something."""
    issues = validate_review_content(
        datasets["reviews"].with_columns(pl.lit("").alias(column)), TITLES, TEXTS
    )

    assert "empty_review_content" in rules(issues)


def test_wording_that_does_not_match_the_rating_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A three-star review never carries five-star wording."""
    reviews = datasets["reviews"].with_columns(
        pl.lit("Excellent Product").alias("review_title"),
        pl.lit(3).cast(pl.Int64).alias("rating"),
    )

    assert "content_not_offered_for_rating" in rules(
        validate_review_content(reviews, TITLES, TEXTS)
    )


def test_wording_from_outside_the_configuration_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The phrases are selected, never invented."""
    reviews = datasets["reviews"].with_columns(
        pl.lit("A sentence nobody configured.").alias("review_text")
    )

    assert "content_not_offered_for_rating" in rules(
        validate_review_content(reviews, TITLES, TEXTS)
    )


def test_the_content_check_is_skipped_without_the_configuration(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Nothing but the configuration knows which phrases were on offer."""
    datasets["reviews"] = datasets["reviews"].with_columns(
        pl.lit("A sentence nobody configured.").alias("review_text")
    )

    assert "content_not_offered_for_rating" not in rules(validate_review_data(datasets))


# --------------------------------------------------------------------------
# Review numbers
# --------------------------------------------------------------------------


def test_a_malformed_review_number_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The number reads as PREFIX-YYYYMMDD-NNNNNN."""
    issues = validate_review_numbers(
        datasets["reviews"].with_columns(pl.lit("not-a-number").alias("review_number"))
    )

    assert "malformed_review_number" in rules(issues)


def test_a_malformed_number_does_not_crash_the_later_checks(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Unparsable text is reported, not raised on."""
    datasets["reviews"] = datasets["reviews"].with_columns(
        pl.lit("not-a-number").alias("review_number")
    )

    found = rules(validate_review_data(datasets, TITLES, TEXTS))

    assert "malformed_review_number" in found
    assert "review_number_date_mismatch" not in found


def test_a_number_date_that_disagrees_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The date inside the number is the day the review was written."""
    issues = validate_review_numbers(
        datasets["reviews"].with_columns(pl.lit("REV-19990101-000001").alias("review_number"))
    )

    assert "review_number_date_mismatch" in rules(issues)


def test_a_gap_in_the_daily_sequence_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Each day is numbered 1..n without gaps."""
    reviews = datasets["reviews"].with_columns(
        pl.col("review_number").str.slice(0, 13).add("999999").alias("review_number")
    )

    assert "review_number_not_sequential" in rules(validate_review_numbers(reviews))


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


def test_a_review_before_delivery_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """created_at must be after shipment.delivered_at."""
    datasets["reviews"] = datasets["reviews"].with_columns(
        (pl.col("created_at") - timedelta(days=365)).alias("created_at")
    )

    assert "review_before_delivery" in rules(validate_review_data(datasets, TITLES, TEXTS))


def test_a_review_on_a_shipment_with_no_delivery_time_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A shipment that never arrived cannot anchor a review."""
    shipments = datasets["shipments"].with_columns(
        pl.lit(None, dtype=pl.Datetime("us")).alias("delivered_at")
    )

    issues = validate_review_timeline(datasets["reviews"], shipments)

    assert "review_before_delivery" in rules(issues)


# --------------------------------------------------------------------------
# Partial bundles
# --------------------------------------------------------------------------


def test_missing_reviews_stop_the_business_rules(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Without the output there is nothing to check beyond the schema."""
    del datasets["reviews"]

    assert "invalid_shipment_status" not in rules(validate_review_data(datasets, TITLES, TEXTS))


def test_upstream_rules_are_skipped_when_the_upstream_is_absent(
    review_data: ReviewData,
) -> None:
    """A bare bundle reports the absent parents and nothing else."""
    issues = validate_review_data(dict(review_data.datasets), TITLES, TEXTS)

    assert rules(issues) == {"missing_reference_dataset"}
