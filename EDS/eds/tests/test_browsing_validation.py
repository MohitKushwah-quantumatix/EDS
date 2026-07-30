"""Tests for browsing validation.

Every failure path corrupts a valid bundle and asserts the specific rule
fires, covering each check the F003.2 specification lists.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from eds.generators.journey.browsing import BrowsingData
from eds.validation.browsing_validation import (
    assert_valid_browsing_data,
    validate_browsing_data,
    validate_category_view_timeline,
    validate_search_category_consistency,
    validate_search_results,
    validate_search_timeline,
    validate_sequences,
    validate_view_durations,
)
from eds.validation.issues import ValidationError, ValidationIssue


@pytest.fixture
def datasets(
    browsing_data: BrowsingData, browsing_upstream: dict[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Return a mutable bundle of browsing datasets plus their upstream data."""
    return {**browsing_upstream, **browsing_data.datasets}


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
    assert validate_browsing_data(datasets) == []


def test_assert_valid_passes_on_clean_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper does not raise for valid data."""
    assert_valid_browsing_data(datasets)


def test_duplicate_category_view_ids_are_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The view id is the primary key."""
    datasets["category_views"] = datasets["category_views"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("category_view_id")
    )

    assert "duplicate_primary_key" in rules(validate_browsing_data(datasets))


def test_duplicate_search_ids_are_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The search id is the primary key."""
    datasets["search_history"] = datasets["search_history"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("search_id")
    )

    assert "duplicate_primary_key" in rules(validate_browsing_data(datasets))


@pytest.mark.parametrize(
    ("dataset", "column", "target"),
    [
        ("category_views", "session_id", "sessions.session_id"),
        ("category_views", "customer_id", "customers.customer_id"),
        ("category_views", "category_id", "categories.category_id"),
        ("search_history", "session_id", "sessions.session_id"),
        ("search_history", "customer_id", "customers.customer_id"),
        ("search_history", "category_id", "categories.category_id"),
        ("search_history", "category_view_id", "category_views.category_view_id"),
    ],
)
def test_invalid_references_are_detected(
    datasets: dict[str, pl.DataFrame], dataset: str, column: str, target: str
) -> None:
    """Every declared foreign key is checked against its target."""
    datasets[dataset] = datasets[dataset].with_columns(pl.lit(999_999).cast(pl.Int64).alias(column))

    issues = validate_browsing_data(datasets)

    assert "orphan_reference" in rules(issues)
    assert any(target in issue.detail for issue in issues)


def test_category_view_timestamp_outside_session_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A view cannot happen outside its session."""
    views = datasets["category_views"].with_columns(pl.lit(datetime(1999, 1, 1)).alias("timestamp"))

    issues = validate_category_view_timeline(views, datasets["sessions"])

    assert "timestamp_outside_session" in rules(issues)


def test_view_outlasting_its_session_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A view cannot run past the end of its session."""
    views = datasets["category_views"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias("duration_seconds")
    )

    issues = validate_category_view_timeline(views, datasets["sessions"])

    assert "view_outlasts_session" in rules(issues)


def test_search_timestamp_outside_session_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A search cannot happen outside its session."""
    searches = datasets["search_history"].with_columns(
        pl.lit(datetime(1999, 1, 1)).alias("timestamp")
    )

    issues = validate_search_timeline(searches, datasets["sessions"], datasets["category_views"])

    assert "timestamp_outside_session" in rules(issues)


def test_search_before_the_first_view_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A search cannot precede the first category view of its session."""
    first = (
        datasets["category_views"]
        .group_by("session_id")
        .agg(pl.col("timestamp").min().alias("first_view"))
    )
    searches = (
        datasets["search_history"]
        .join(first, on="session_id", how="inner")
        .with_columns(pl.col("first_view").alias("timestamp"))
        .drop("first_view")
    )

    issues = validate_search_timeline(searches, datasets["sessions"], datasets["category_views"])

    assert "search_before_first_view" in rules(issues)


def test_negative_view_duration_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A view cannot last a negative length of time."""
    views = datasets["category_views"].with_columns(
        pl.lit(-10).cast(pl.Int64).alias("duration_seconds")
    )

    assert "negative_duration" in rules(validate_view_durations(views, 5, 180))


def test_out_of_range_view_duration_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Durations outside the configured band are reported."""
    assert "duration_out_of_range" in rules(
        validate_view_durations(datasets["category_views"], 5, 10)
    )


def test_invalid_view_sequence_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """View sequences must start at one."""
    views = datasets["category_views"].with_columns(pl.lit(0).cast(pl.Int64).alias("view_sequence"))

    assert "invalid_view_sequence" in rules(validate_sequences(views, datasets["search_history"]))


def test_gapped_view_sequence_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A sequence with gaps is reported even when every value is positive."""
    views = datasets["category_views"].with_columns(
        (pl.col("view_sequence") * 2).alias("view_sequence")
    )

    assert "invalid_view_sequence" in rules(validate_sequences(views, datasets["search_history"]))


def test_invalid_search_sequence_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Search sequences must start at one."""
    searches = datasets["search_history"].with_columns(
        pl.lit(0).cast(pl.Int64).alias("search_sequence")
    )

    assert "invalid_search_sequence" in rules(
        validate_sequences(datasets["category_views"], searches)
    )


def test_category_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A search must belong to the category of the view it came from."""
    searches = datasets["search_history"].with_columns(
        (pl.col("category_id") + 1).alias("category_id")
    )

    issues = validate_search_category_consistency(searches, datasets["category_views"])

    assert "category_mismatch" in rules(issues)


def test_session_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A search must sit in the same session as its category view."""
    searches = datasets["search_history"].with_columns(
        (pl.col("session_id") + 1).alias("session_id")
    )

    issues = validate_search_category_consistency(searches, datasets["category_views"])

    assert "session_mismatch" in rules(issues)


def test_out_of_range_results_count_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Result counts above the ceiling are reported."""
    searches = datasets["search_history"].with_columns(
        pl.lit(9_999).cast(pl.Int64).alias("results_count")
    )

    assert "results_out_of_range" in rules(validate_search_results(searches, 250))


def test_negative_results_count_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A negative result count is a defect."""
    searches = datasets["search_history"].with_columns(
        pl.lit(-1).cast(pl.Int64).alias("results_count")
    )

    assert "results_out_of_range" in rules(validate_search_results(searches, 250))


def test_click_without_results_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A search that found nothing cannot have been clicked."""
    searches = datasets["search_history"].with_columns(
        pl.lit(0).cast(pl.Int64).alias("results_count"),
        pl.lit(True).alias("clicked_result"),
    )

    assert "clicked_without_results" in rules(validate_search_results(searches, 250))


def test_empty_search_text_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A search must carry text."""
    searches = datasets["search_history"].with_columns(pl.lit("   ").alias("search_text"))

    assert "empty_search_text" in rules(validate_search_results(searches, 250))


def test_missing_dataset_is_reported(datasets: dict[str, pl.DataFrame]) -> None:
    """A dataset that was never generated is an integrity failure."""
    del datasets["search_history"]

    assert "missing_dataset" in rules(validate_browsing_data(datasets))


def test_dtype_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A wrong dtype would corrupt the exported Parquet schema."""
    datasets["category_views"] = datasets["category_views"].with_columns(
        pl.col("category_view_id").cast(pl.Int32)
    )

    assert "dtype_mismatch" in rules(validate_browsing_data(datasets))


def test_assert_valid_raises_on_corrupt_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper raises when the data is broken."""
    datasets["search_history"] = datasets["search_history"].with_columns(
        (pl.col("category_id") + 1).alias("category_id")
    )

    with pytest.raises(ValidationError, match="category_mismatch"):
        assert_valid_browsing_data(datasets)


def test_earlier_features_still_validate(
    browsing_upstream: dict[str, pl.DataFrame],
) -> None:
    """Adding browsing declarations did not disturb the earlier validators."""
    from eds.validation.journey_validation import validate_journey_data
    from eds.validation.master_data import validate_master_data

    assert validate_master_data(browsing_upstream) == []
    assert validate_journey_data(browsing_upstream, datetime(2026, 1, 1).date()) == []
