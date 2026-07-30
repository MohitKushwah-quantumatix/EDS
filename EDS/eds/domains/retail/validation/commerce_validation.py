"""Validation rules for the F004 commerce datasets.

Referential integrity is delegated to
:func:`eds.core.validation.referential.validate_referential_integrity` with the
commerce declarations, which covers duplicate ``cart_id`` and
``cart_item_id`` values and invalid customer, session, cart, product,
product view, and wishlist references.

The rules here cover what a schema cannot express: that ``item_count`` agrees
with the items actually present, that a product matches whatever it was added
from, and that the add and remove times respect the journey's order.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.validation.issues import ValidationError, ValidationIssue
from eds.domains.retail.domain.commerce.schema import COMMERCE_DATASETS
from eds.domains.retail.validation.referential import validate_referential_integrity

__all__ = [
    "assert_valid_commerce_data",
    "validate_cart_item_source",
    "validate_cart_timeline",
    "validate_commerce_data",
    "validate_item_counts",
    "validate_quantities",
]


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


def validate_item_counts(carts: pl.DataFrame, cart_items: pl.DataFrame) -> list[ValidationIssue]:
    """Check ``item_count`` matches the items present, and no cart is empty.

    Args:
        carts: The shopping carts dataset.
        cart_items: The cart items dataset.

    Returns:
        Issues for a mismatched count or a cart holding no items.
    """
    issues: list[ValidationIssue] = []

    actual = cart_items.group_by("cart_id").len().rename({"len": "actual_items"})
    joined = carts.join(actual, on="cart_id", how="left").with_columns(
        pl.col("actual_items").fill_null(0)
    )

    issues += _issue_if(
        joined,
        "shopping_carts",
        "item_count_mismatch",
        pl.col("item_count") != pl.col("actual_items"),
        "item_count equals the number of cart items",
    )
    issues += _issue_if(
        joined,
        "shopping_carts",
        "empty_cart",
        pl.col("actual_items") == 0,
        "every cart contains at least one item",
    )
    return issues


def validate_cart_item_source(
    cart_items: pl.DataFrame, product_views: pl.DataFrame, wishlists: pl.DataFrame
) -> list[ValidationIssue]:
    """Check each item's product matches whatever it was added from.

    Args:
        cart_items: The cart items dataset.
        product_views: The F003.3 product views dataset.
        wishlists: The F003.3 wishlists dataset.

    Returns:
        Issues for a wishlist-sourced item without a wishlist, a
        product-view-sourced item carrying one, or a product that disagrees
        with its source.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        cart_items,
        "cart_items",
        "wishlist_source_without_wishlist",
        (pl.col("added_from") == "WISHLIST") & pl.col("wishlist_id").is_null(),
        "a wishlist-sourced item references a wishlist entry",
    )
    issues += _issue_if(
        cart_items,
        "cart_items",
        "wishlist_on_product_view_source",
        (pl.col("added_from") == "PRODUCT_VIEW") & pl.col("wishlist_id").is_not_null(),
        "only a wishlist-sourced item references a wishlist entry",
    )

    from_view = cart_items.join(
        product_views.select(
            "product_view_id",
            pl.col("product_id").alias("viewed_product_id"),
            pl.col("customer_id").alias("viewing_customer_id"),
        ),
        on="product_view_id",
        how="inner",
    )
    issues += _issue_if(
        from_view,
        "cart_items",
        "product_mismatch",
        pl.col("product_id") != pl.col("viewed_product_id"),
        "the product matches the product view it was added from",
    )
    issues += _issue_if(
        from_view,
        "cart_items",
        "customer_mismatch",
        pl.col("customer_id") != pl.col("viewing_customer_id"),
        "the customer matches the customer who viewed the product",
    )

    from_wishlist = cart_items.filter(pl.col("wishlist_id").is_not_null()).join(
        wishlists.select(
            "wishlist_id",
            pl.col("product_id").alias("saved_product_id"),
            pl.col("customer_id").alias("saving_customer_id"),
        ),
        on="wishlist_id",
        how="inner",
    )
    issues += _issue_if(
        from_wishlist,
        "cart_items",
        "wishlist_product_mismatch",
        pl.col("product_id") != pl.col("saved_product_id"),
        "the product matches the wishlist entry it was added from",
    )
    issues += _issue_if(
        from_wishlist,
        "cart_items",
        "wishlist_customer_mismatch",
        pl.col("customer_id") != pl.col("saving_customer_id"),
        "the customer matches the customer who saved the product",
    )
    return issues


def validate_quantities(
    cart_items: pl.DataFrame, min_quantity: int, max_quantity: int
) -> list[ValidationIssue]:
    """Check quantities and prices are sane.

    Args:
        cart_items: The cart items dataset.
        min_quantity: Fewest permitted units.
        max_quantity: Most permitted units.

    Returns:
        Issues for non-positive or out-of-range quantities, or a negative
        unit price.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        cart_items,
        "cart_items",
        "negative_quantity",
        pl.col("quantity") <= 0,
        "quantity > 0",
    )
    issues += _issue_if(
        cart_items,
        "cart_items",
        "quantity_out_of_range",
        (pl.col("quantity") < min_quantity) | (pl.col("quantity") > max_quantity),
        f"{min_quantity} <= quantity <= {max_quantity}",
    )
    issues += _issue_if(
        cart_items,
        "cart_items",
        "negative_unit_price",
        pl.col("unit_price") < 0,
        "unit_price >= 0",
    )
    return issues


def validate_cart_timeline(
    carts: pl.DataFrame,
    cart_items: pl.DataFrame,
    sessions: pl.DataFrame,
    product_views: pl.DataFrame,
    wishlists: pl.DataFrame,
) -> list[ValidationIssue]:
    """Check the cart chronology holds end to end.

    Args:
        carts: The shopping carts dataset.
        cart_items: The cart items dataset.
        sessions: The F003.1 sessions dataset.
        product_views: The F003.3 product views dataset.
        wishlists: The F003.3 wishlists dataset.

    Returns:
        Issues for a cart updated before it was created, a cart outside its
        session, or an item added before the event it came from.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        carts,
        "shopping_carts",
        "updated_before_created",
        pl.col("updated_at") <= pl.col("created_at"),
        "updated_at is after created_at",
    )

    within = carts.join(
        sessions.select("session_id", "start_time", "end_time"),
        on="session_id",
        how="inner",
    )
    issues += _issue_if(
        within,
        "shopping_carts",
        "cart_outside_session",
        (pl.col("created_at") < pl.col("start_time")) | (pl.col("updated_at") > pl.col("end_time")),
        "the cart falls inside its session",
    )

    after_view = cart_items.join(
        product_views.select("product_view_id", pl.col("timestamp").alias("viewed_at")),
        on="product_view_id",
        how="inner",
    )
    issues += _issue_if(
        after_view,
        "cart_items",
        "added_before_product_view",
        pl.col("added_at") <= pl.col("viewed_at"),
        "the item was added after the product was viewed",
    )

    after_wishlist = cart_items.filter(pl.col("wishlist_id").is_not_null()).join(
        wishlists.select("wishlist_id", pl.col("timestamp").alias("saved_at")),
        on="wishlist_id",
        how="inner",
    )
    issues += _issue_if(
        after_wishlist,
        "cart_items",
        "added_before_wishlist",
        pl.col("added_at") <= pl.col("saved_at"),
        "the item was added after it was saved to the wishlist",
    )

    issues += _issue_if(
        cart_items.filter(pl.col("removed_at").is_not_null()),
        "cart_items",
        "removed_before_added",
        pl.col("removed_at") <= pl.col("added_at"),
        "removed_at is after added_at",
    )

    bracketed = cart_items.join(
        carts.select("cart_id", "created_at", "updated_at"), on="cart_id", how="inner"
    )
    issues += _issue_if(
        bracketed,
        "cart_items",
        "item_outside_cart_window",
        (pl.col("added_at") < pl.col("created_at")) | (pl.col("added_at") > pl.col("updated_at")),
        "the item was added between the cart's created and updated times",
    )
    return issues


def validate_commerce_data(
    datasets: Mapping[str, pl.DataFrame],
    min_quantity: int = 1,
    max_quantity: int = 5,
) -> list[ValidationIssue]:
    """Validate schema, referential integrity, and commerce business rules.

    Args:
        datasets: The commerce datasets plus the upstream datasets they
            reference, keyed by name.
        min_quantity: Fewest permitted units of one product.
        max_quantity: Most permitted units of one product.

    Returns:
        Every issue found. An empty list means the data satisfies the F004
        acceptance criteria.
    """
    issues = validate_referential_integrity(datasets, COMMERCE_DATASETS)

    carts = datasets.get("shopping_carts")
    cart_items = datasets.get("cart_items")
    if carts is None or cart_items is None:
        return issues

    issues.extend(validate_item_counts(carts, cart_items))
    issues.extend(validate_quantities(cart_items, min_quantity, max_quantity))

    product_views = datasets.get("product_views")
    wishlists = datasets.get("wishlists")
    sessions = datasets.get("sessions")

    if product_views is not None and wishlists is not None:
        issues.extend(validate_cart_item_source(cart_items, product_views, wishlists))
        if sessions is not None:
            issues.extend(
                validate_cart_timeline(carts, cart_items, sessions, product_views, wishlists)
            )
    return issues


def assert_valid_commerce_data(
    datasets: Mapping[str, pl.DataFrame],
    min_quantity: int = 1,
    max_quantity: int = 5,
) -> None:
    """Validate commerce datasets and raise if anything is wrong.

    Args:
        datasets: The commerce datasets plus the upstream data they use.
        min_quantity: Fewest permitted units of one product.
        max_quantity: Most permitted units of one product.

    Raises:
        ValidationError: If any validation issue is found.
    """
    issues = validate_commerce_data(datasets, min_quantity, max_quantity)
    if issues:
        raise ValidationError(issues)
