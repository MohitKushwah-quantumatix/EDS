"""Tests for engagement validation.

Every failure path corrupts a valid bundle and asserts the specific rule
fires, covering each check the F003.3 specification lists.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from eds.generators.journey.engagement import EngagementData
from eds.validation.engagement_validation import (
    assert_valid_engagement_data,
    validate_engagement_data,
    validate_product_category_containment,
    validate_product_view_sequences,
    validate_product_view_timeline,
    validate_search_source,
    validate_view_durations,
    validate_wishlist_origin,
    validate_wishlist_timeline,
    validate_wishlist_uniqueness,
)
from eds.validation.issues import ValidationError, ValidationIssue


@pytest.fixture
def datasets(
    engagement_data: EngagementData, engagement_upstream: dict[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Return a mutable bundle of engagement datasets plus upstream data."""
    return {**engagement_upstream, **engagement_data.datasets}


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
    assert validate_engagement_data(datasets) == []


def test_assert_valid_passes_on_clean_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper does not raise for valid data."""
    assert_valid_engagement_data(datasets)


def test_duplicate_product_view_ids_are_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The product view id is the primary key."""
    datasets["product_views"] = datasets["product_views"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("product_view_id")
    )

    assert "duplicate_primary_key" in rules(validate_engagement_data(datasets))


def test_duplicate_wishlist_ids_are_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The wishlist id is the primary key."""
    datasets["wishlists"] = datasets["wishlists"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("wishlist_id")
    )

    assert "duplicate_primary_key" in rules(validate_engagement_data(datasets))


@pytest.mark.parametrize(
    ("dataset", "column", "target"),
    [
        ("product_views", "session_id", "sessions.session_id"),
        ("product_views", "customer_id", "customers.customer_id"),
        ("product_views", "category_view_id", "category_views.category_view_id"),
        ("product_views", "category_id", "categories.category_id"),
        ("product_views", "product_id", "products.product_id"),
        ("wishlists", "customer_id", "customers.customer_id"),
        ("wishlists", "product_view_id", "product_views.product_view_id"),
        ("wishlists", "product_id", "products.product_id"),
    ],
)
def test_invalid_references_are_detected(
    datasets: dict[str, pl.DataFrame], dataset: str, column: str, target: str
) -> None:
    """Every declared foreign key is checked against its target."""
    datasets[dataset] = datasets[dataset].with_columns(pl.lit(999_999).cast(pl.Int64).alias(column))

    issues = validate_engagement_data(datasets)

    assert "orphan_reference" in rules(issues)
    assert any(target in issue.detail for issue in issues)


def test_invalid_search_reference_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A search-sourced view pointing at no real search is an orphan."""
    datasets["product_views"] = datasets["product_views"].with_columns(
        pl.when(pl.col("search_id").is_not_null())
        .then(pl.lit(999_999).cast(pl.Int64))
        .otherwise(pl.col("search_id"))
        .alias("search_id")
    )

    issues = validate_engagement_data(datasets)

    assert "orphan_reference" in rules(issues)
    assert any("search_history.search_id" in issue.detail for issue in issues)


def test_product_category_mismatch_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A view's category must match the category view it came from."""
    views = datasets["product_views"].with_columns((pl.col("category_id") + 1).alias("category_id"))

    issues = validate_product_category_containment(
        views,
        datasets["category_views"],
        datasets["categories"],
        datasets["products"],
    )

    assert "category_mismatch" in rules(issues)


def test_product_outside_its_category_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A product from an unrelated section is caught by path containment."""
    products = datasets["products"]
    categories = datasets["categories"]
    # Re-point every product view at a product from a different top-level
    # section than the one being browsed.
    first_root = categories.filter(pl.col("level") == 1).row(0, named=True)
    other_root = categories.filter(pl.col("level") == 1).row(1, named=True)
    other_leaf = categories.filter(
        pl.col("category_path").str.starts_with(other_root["category_path"] + "/")
        & pl.col("is_leaf")
    ).row(0, named=True)
    foreign_product = products.filter(pl.col("category_id") == other_leaf["category_id"]).row(
        0, named=True
    )

    views = datasets["product_views"].with_columns(
        pl.lit(first_root["category_id"]).cast(pl.Int64).alias("category_id"),
        pl.lit(foreign_product["product_id"]).cast(pl.Int64).alias("product_id"),
    )
    category_views = datasets["category_views"].with_columns(
        pl.lit(first_root["category_id"]).cast(pl.Int64).alias("category_id")
    )

    issues = validate_product_category_containment(views, category_views, categories, products)

    assert "product_outside_category" in rules(issues)


def test_search_source_without_a_search_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A search-sourced view must reference a search."""
    views = datasets["product_views"].with_columns(
        pl.lit("SEARCH").alias("view_source"),
        pl.lit(None).cast(pl.Int64).alias("search_id"),
    )

    assert "search_source_without_search" in rules(
        validate_search_source(views, datasets["search_history"])
    )


def test_search_on_a_non_search_source_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Only a search-sourced view may carry a search."""
    views = datasets["product_views"].with_columns(pl.lit("CATEGORY").alias("view_source"))

    assert "search_on_non_search_source" in rules(
        validate_search_source(views, datasets["search_history"])
    )


def test_search_category_mismatch_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The search must be about the category being viewed."""
    views = datasets["product_views"].with_columns(
        pl.when(pl.col("search_id").is_not_null())
        .then(pl.col("category_id") + 1)
        .otherwise(pl.col("category_id"))
        .alias("category_id")
    )

    assert "search_category_mismatch" in rules(
        validate_search_source(views, datasets["search_history"])
    )


def test_view_before_its_search_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A product view cannot precede the search that produced it."""
    views = datasets["product_views"].with_columns(pl.lit(datetime(1999, 1, 1)).alias("timestamp"))

    assert "view_before_search" in rules(validate_search_source(views, datasets["search_history"]))


def test_negative_duration_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A product view cannot last a negative length of time."""
    views = datasets["product_views"].with_columns(
        pl.lit(-5).cast(pl.Int64).alias("view_duration_seconds")
    )

    assert "negative_duration" in rules(validate_view_durations(views, 5, 600))


def test_out_of_range_duration_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Durations outside the configured band are reported."""
    assert "duration_out_of_range" in rules(
        validate_view_durations(datasets["product_views"], 5, 20)
    )


def test_invalid_view_sequence_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """View sequences must start at one."""
    views = datasets["product_views"].with_columns(pl.lit(0).cast(pl.Int64).alias("view_sequence"))

    assert "invalid_view_sequence" in rules(validate_product_view_sequences(views))


def test_gapped_view_sequence_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A sequence with gaps is reported even when every value is positive."""
    views = datasets["product_views"].with_columns(
        (pl.col("view_sequence") * 2).alias("view_sequence")
    )

    assert "invalid_view_sequence" in rules(validate_product_view_sequences(views))


def test_timestamp_outside_session_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A product view cannot happen outside its session."""
    views = datasets["product_views"].with_columns(pl.lit(datetime(1999, 1, 1)).alias("timestamp"))

    issues = validate_product_view_timeline(views, datasets["sessions"], datasets["category_views"])

    assert "timestamp_outside_session" in rules(issues)


def test_view_outlasting_its_session_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A product view cannot run past the end of its session."""
    views = datasets["product_views"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias("view_duration_seconds")
    )

    issues = validate_product_view_timeline(views, datasets["sessions"], datasets["category_views"])

    assert "view_outlasts_session" in rules(issues)


def test_view_before_its_category_view_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A product is opened from a category page, never before it."""
    views = datasets["product_views"].with_columns(pl.lit(datetime(2000, 1, 1)).alias("timestamp"))

    issues = validate_product_view_timeline(views, datasets["sessions"], datasets["category_views"])

    assert "view_before_category_view" in rules(issues)


def test_wishlist_without_a_product_view_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """An entry with no originating view is reported."""
    wishlists = datasets["wishlists"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias("product_view_id")
    )

    issues = validate_wishlist_origin(wishlists, datasets["product_views"])

    assert "wishlist_without_product_view" in rules(issues)


def test_wishlist_product_mismatch_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The saved product must be the product that was viewed."""
    wishlists = datasets["wishlists"].with_columns((pl.col("product_id") + 1).alias("product_id"))

    issues = validate_wishlist_origin(wishlists, datasets["product_views"])

    assert "product_mismatch" in rules(issues)


def test_wishlist_customer_mismatch_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The saving customer must be the one who viewed the product."""
    wishlists = datasets["wishlists"].with_columns((pl.col("customer_id") + 1).alias("customer_id"))

    issues = validate_wishlist_origin(wishlists, datasets["product_views"])

    assert "customer_mismatch" in rules(issues)


def test_wishlist_source_mismatch_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The recorded source must match the product view's source."""
    wishlists = datasets["wishlists"].with_columns(pl.lit("NOWHERE").alias("added_from_source"))

    issues = validate_wishlist_origin(wishlists, datasets["product_views"])

    assert "source_mismatch" in rules(issues)


def test_duplicate_wishlist_product_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A customer may not hold the same product twice."""
    wishlists = datasets["wishlists"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("customer_id"),
        pl.lit(1).cast(pl.Int64).alias("product_id"),
    )

    assert "duplicate_wishlist_product" in rules(validate_wishlist_uniqueness(wishlists))


def test_wishlist_before_its_product_view_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """An entry cannot be saved before the product was viewed."""
    wishlists = datasets["wishlists"].with_columns(pl.lit(datetime(1999, 1, 1)).alias("timestamp"))

    assert "wishlist_before_product_view" in rules(
        validate_wishlist_timeline(wishlists, datasets["product_views"])
    )


def test_missing_dataset_is_reported(datasets: dict[str, pl.DataFrame]) -> None:
    """A dataset that was never generated is an integrity failure."""
    del datasets["wishlists"]

    assert "missing_dataset" in rules(validate_engagement_data(datasets))


def test_dtype_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A wrong dtype would corrupt the exported Parquet schema."""
    datasets["product_views"] = datasets["product_views"].with_columns(
        pl.col("product_view_id").cast(pl.Int32)
    )

    assert "dtype_mismatch" in rules(validate_engagement_data(datasets))


def test_empty_wishlists_validate_cleanly(datasets: dict[str, pl.DataFrame]) -> None:
    """Uniqueness on an empty frame is vacuously satisfied."""
    assert validate_wishlist_uniqueness(datasets["wishlists"].clear()) == []


def test_assert_valid_raises_on_corrupt_data(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The assertion helper raises when the data is broken."""
    datasets["wishlists"] = datasets["wishlists"].with_columns(
        (pl.col("product_id") + 1).alias("product_id")
    )

    with pytest.raises(ValidationError, match="product_mismatch"):
        assert_valid_engagement_data(datasets)


def test_earlier_features_still_validate(
    engagement_upstream: dict[str, pl.DataFrame],
) -> None:
    """Adding engagement declarations did not disturb earlier validators."""
    from eds.validation.browsing_validation import validate_browsing_data
    from eds.validation.master_data import validate_master_data

    assert validate_master_data(engagement_upstream) == []
    assert validate_browsing_data(engagement_upstream) == []
