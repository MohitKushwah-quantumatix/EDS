"""Tests for commerce validation.

Every failure path corrupts a valid bundle and asserts the specific rule
fires, covering each check the F004 specification lists.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from eds.generators.commerce.commerce import CommerceData
from eds.validation.commerce_validation import (
    assert_valid_commerce_data,
    validate_cart_item_source,
    validate_cart_timeline,
    validate_commerce_data,
    validate_item_counts,
    validate_quantities,
)
from eds.validation.issues import ValidationError, ValidationIssue


@pytest.fixture
def datasets(
    commerce_data: CommerceData, commerce_upstream: dict[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Return a mutable bundle of commerce datasets plus upstream data."""
    return {**commerce_upstream, **commerce_data.datasets}


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
    assert validate_commerce_data(datasets) == []


def test_assert_valid_passes_on_clean_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper does not raise for valid data."""
    assert_valid_commerce_data(datasets)


def test_duplicate_cart_ids_are_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The cart id is the primary key."""
    datasets["shopping_carts"] = datasets["shopping_carts"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("cart_id")
    )

    assert "duplicate_primary_key" in rules(validate_commerce_data(datasets))


def test_duplicate_cart_item_ids_are_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The cart item id is the primary key."""
    datasets["cart_items"] = datasets["cart_items"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("cart_item_id")
    )

    assert "duplicate_primary_key" in rules(validate_commerce_data(datasets))


def test_duplicate_session_on_carts_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A session may hold at most one cart."""
    datasets["shopping_carts"] = datasets["shopping_carts"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("session_id")
    )

    assert "duplicate_unique_column" in rules(validate_commerce_data(datasets))


@pytest.mark.parametrize(
    ("dataset", "column", "target"),
    [
        ("shopping_carts", "customer_id", "customers.customer_id"),
        ("shopping_carts", "session_id", "sessions.session_id"),
        ("cart_items", "cart_id", "shopping_carts.cart_id"),
        ("cart_items", "customer_id", "customers.customer_id"),
        ("cart_items", "product_id", "products.product_id"),
        ("cart_items", "product_view_id", "product_views.product_view_id"),
    ],
)
def test_invalid_references_are_detected(
    datasets: dict[str, pl.DataFrame], dataset: str, column: str, target: str
) -> None:
    """Every declared foreign key is checked against its target."""
    datasets[dataset] = datasets[dataset].with_columns(pl.lit(999_999).cast(pl.Int64).alias(column))

    issues = validate_commerce_data(datasets)

    assert "orphan_reference" in rules(issues)
    assert any(target in issue.detail for issue in issues)


def test_invalid_wishlist_reference_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A wishlist-sourced item pointing at no real entry is an orphan."""
    datasets["cart_items"] = datasets["cart_items"].with_columns(
        pl.when(pl.col("wishlist_id").is_not_null())
        .then(pl.lit(999_999).cast(pl.Int64))
        .otherwise(pl.col("wishlist_id"))
        .alias("wishlist_id")
    )

    issues = validate_commerce_data(datasets)

    assert "orphan_reference" in rules(issues)
    assert any("wishlists.wishlist_id" in issue.detail for issue in issues)


def test_item_count_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The denormalised count must agree with the items."""
    carts = datasets["shopping_carts"].with_columns((pl.col("item_count") + 1).alias("item_count"))

    assert "item_count_mismatch" in rules(validate_item_counts(carts, datasets["cart_items"]))


def test_empty_cart_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A cart holding no items is a defect."""
    items = datasets["cart_items"].filter(pl.col("cart_id") != 1)

    issues = validate_item_counts(datasets["shopping_carts"], items)

    assert "empty_cart" in rules(issues)


def test_wishlist_source_without_a_wishlist_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A wishlist-sourced item must reference a wishlist entry."""
    items = datasets["cart_items"].with_columns(
        pl.lit("WISHLIST").alias("added_from"),
        pl.lit(None).cast(pl.Int64).alias("wishlist_id"),
    )

    assert "wishlist_source_without_wishlist" in rules(
        validate_cart_item_source(items, datasets["product_views"], datasets["wishlists"])
    )


def test_wishlist_on_a_product_view_source_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Only a wishlist-sourced item may carry a wishlist id."""
    items = datasets["cart_items"].with_columns(pl.lit("PRODUCT_VIEW").alias("added_from"))

    assert "wishlist_on_product_view_source" in rules(
        validate_cart_item_source(items, datasets["product_views"], datasets["wishlists"])
    )


def test_product_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The product must match the product view it came from."""
    items = datasets["cart_items"].with_columns((pl.col("product_id") + 1).alias("product_id"))

    assert "product_mismatch" in rules(
        validate_cart_item_source(items, datasets["product_views"], datasets["wishlists"])
    )


def test_customer_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The customer must be the one who viewed the product."""
    items = datasets["cart_items"].with_columns((pl.col("customer_id") + 1).alias("customer_id"))

    assert "customer_mismatch" in rules(
        validate_cart_item_source(items, datasets["product_views"], datasets["wishlists"])
    )


def test_negative_quantity_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A cart item cannot hold a negative number of units."""
    items = datasets["cart_items"].with_columns(pl.lit(-1).cast(pl.Int64).alias("quantity"))

    assert "negative_quantity" in rules(validate_quantities(items, 1, 5))


def test_out_of_range_quantity_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Quantities above the configured ceiling are reported."""
    assert "quantity_out_of_range" in rules(validate_quantities(datasets["cart_items"], 1, 1))


def test_negative_unit_price_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A negative price is a defect."""
    items = datasets["cart_items"].with_columns(pl.lit(-1.0).alias("unit_price"))

    assert "negative_unit_price" in rules(validate_quantities(items, 1, 5))


def test_updated_before_created_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Cart timestamps must be strictly ordered."""
    carts = datasets["shopping_carts"].with_columns(pl.col("created_at").alias("updated_at"))

    issues = validate_cart_timeline(
        carts,
        datasets["cart_items"],
        datasets["sessions"],
        datasets["product_views"],
        datasets["wishlists"],
    )

    assert "updated_before_created" in rules(issues)


def test_cart_outside_its_session_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A cart cannot be opened outside the session it belongs to."""
    carts = datasets["shopping_carts"].with_columns(
        pl.lit(datetime(1999, 1, 1)).alias("created_at")
    )

    issues = validate_cart_timeline(
        carts,
        datasets["cart_items"],
        datasets["sessions"],
        datasets["product_views"],
        datasets["wishlists"],
    )

    assert "cart_outside_session" in rules(issues)


def test_item_added_before_its_product_view_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """An item cannot be added before the product was seen."""
    items = datasets["cart_items"].with_columns(pl.lit(datetime(1999, 1, 1)).alias("added_at"))

    issues = validate_cart_timeline(
        datasets["shopping_carts"],
        items,
        datasets["sessions"],
        datasets["product_views"],
        datasets["wishlists"],
    )

    assert "added_before_product_view" in rules(issues)


def test_removed_before_added_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A removal cannot predate the add."""
    items = datasets["cart_items"].with_columns(
        pl.when(pl.col("removed_at").is_not_null())
        .then(pl.col("added_at"))
        .otherwise(pl.col("removed_at"))
        .alias("removed_at")
    )

    issues = validate_cart_timeline(
        datasets["shopping_carts"],
        items,
        datasets["sessions"],
        datasets["product_views"],
        datasets["wishlists"],
    )

    assert "removed_before_added" in rules(issues)


def test_item_outside_the_cart_window_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """An item added outside its cart's own window is a defect."""
    carts = datasets["shopping_carts"].with_columns(
        pl.lit(datetime(2030, 1, 1)).alias("created_at"),
        pl.lit(datetime(2030, 1, 2)).alias("updated_at"),
    )

    issues = validate_cart_timeline(
        carts,
        datasets["cart_items"],
        datasets["sessions"],
        datasets["product_views"],
        datasets["wishlists"],
    )

    assert "item_outside_cart_window" in rules(issues)


def test_missing_dataset_is_reported(datasets: dict[str, pl.DataFrame]) -> None:
    """A dataset that was never generated is an integrity failure."""
    del datasets["cart_items"]

    assert "missing_dataset" in rules(validate_commerce_data(datasets))


def test_dtype_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A wrong dtype would corrupt the exported Parquet schema."""
    datasets["shopping_carts"] = datasets["shopping_carts"].with_columns(
        pl.col("cart_id").cast(pl.Int32)
    )

    assert "dtype_mismatch" in rules(validate_commerce_data(datasets))


def test_assert_valid_raises_on_corrupt_data(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """The assertion helper raises when the data is broken."""
    datasets["cart_items"] = datasets["cart_items"].with_columns(
        (pl.col("product_id") + 1).alias("product_id")
    )

    with pytest.raises(ValidationError, match="product_mismatch"):
        assert_valid_commerce_data(datasets)


def test_earlier_features_still_validate(
    commerce_upstream: dict[str, pl.DataFrame],
) -> None:
    """Adding commerce declarations did not disturb earlier validators."""
    from eds.validation.engagement_validation import validate_engagement_data
    from eds.validation.master_data import validate_master_data

    assert validate_master_data(commerce_upstream) == []
    assert validate_engagement_data(commerce_upstream) == []
