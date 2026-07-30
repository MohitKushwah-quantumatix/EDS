"""Tests for the cart item generator."""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import CommerceConfig
from eds.domain.commerce.enums import CartItemSource
from eds.generators.commerce.cart_generator import plan_carts
from eds.generators.commerce.cart_item_generator import (
    QUANTITY_WEIGHTS,
    CartSources,
    generate_cart_items,
    iter_cart_item_batches,
)
from eds.generators.commerce.commerce import CommerceData

SEED = 7070


@pytest.fixture
def config() -> CommerceConfig:
    """Return a commerce configuration with a small batch size."""
    return CommerceConfig(batch_size=200)


@pytest.fixture
def items(commerce_data: CommerceData) -> pl.DataFrame:
    """Return the generated cart items frame."""
    return commerce_data["cart_items"]


@pytest.fixture
def carts(commerce_data: CommerceData) -> pl.DataFrame:
    """Return the generated shopping carts frame."""
    return commerce_data["shopping_carts"]


@pytest.fixture
def sources(commerce_upstream: dict[str, pl.DataFrame]) -> CartSources:
    """Return everything the carts can be filled from."""
    return CartSources.from_frames(
        commerce_upstream["product_views"],
        commerce_upstream["wishlists"],
        commerce_upstream["products"],
    )


@pytest.fixture
def planned(config: CommerceConfig, commerce_upstream: dict[str, pl.DataFrame]) -> list:
    """Return the planned carts."""
    return plan_carts(
        config,
        commerce_upstream["sessions"],
        commerce_upstream["customer_personas"],
        SEED,
    )


def test_quantity_weights_favour_a_single_unit() -> None:
    """The documented 70/18/7/3/2 split is encoded."""
    assert QUANTITY_WEIGHTS == (70, 18, 7, 3, 2)


def test_sources_require_product_views(
    commerce_upstream: dict[str, pl.DataFrame],
) -> None:
    """Nothing can reach a cart without a product view."""
    with pytest.raises(ValueError, match="product views dataset is empty"):
        CartSources.from_frames(
            commerce_upstream["product_views"].clear(),
            commerce_upstream["wishlists"],
            commerce_upstream["products"],
        )


def test_sources_require_products(commerce_upstream: dict[str, pl.DataFrame]) -> None:
    """Prices come from the product catalog."""
    with pytest.raises(ValueError, match="products dataset is empty"):
        CartSources.from_frames(
            commerce_upstream["product_views"],
            commerce_upstream["wishlists"],
            commerce_upstream["products"].clear(),
        )


def test_empty_wishlists_are_allowed(
    commerce_upstream: dict[str, pl.DataFrame],
) -> None:
    """A run with no wishlists still fills carts from product views."""
    sources = CartSources.from_frames(
        commerce_upstream["product_views"],
        commerce_upstream["wishlists"].clear(),
        commerce_upstream["products"],
    )

    assert sources.wishlist_by_customer == {}


def test_item_ids_are_unique_and_sequential(items: pl.DataFrame) -> None:
    """Item ids form a dense sequence starting at one."""
    assert items["cart_item_id"].to_list() == list(range(1, items.height + 1))


def test_added_from_uses_declared_values(items: pl.DataFrame) -> None:
    """Every source comes from the enum."""
    assert set(items["added_from"].to_list()) <= {str(m) for m in CartItemSource}


def test_only_wishlist_items_carry_a_wishlist_id(items: pl.DataFrame) -> None:
    """`wishlist_id` is populated exactly when the source is a wishlist."""
    from_wishlist = items.filter(pl.col("added_from") == str(CartItemSource.WISHLIST))
    from_view = items.filter(pl.col("added_from") == str(CartItemSource.PRODUCT_VIEW))

    assert from_wishlist.filter(pl.col("wishlist_id").is_null()).height == 0
    assert from_view.filter(pl.col("wishlist_id").is_not_null()).height == 0


def test_both_sources_are_exercised(items: pl.DataFrame) -> None:
    """The wishlist path is not dead code."""
    assert items.filter(pl.col("added_from") == str(CartItemSource.WISHLIST)).height > 0
    assert items.filter(pl.col("added_from") == str(CartItemSource.PRODUCT_VIEW)).height > 0


def test_products_match_their_product_view(
    items: pl.DataFrame, commerce_upstream: dict[str, pl.DataFrame]
) -> None:
    """Every item's product is the product that was viewed."""
    joined = items.join(
        commerce_upstream["product_views"].select(
            "product_view_id",
            pl.col("product_id").alias("viewed_product"),
            pl.col("customer_id").alias("viewing_customer"),
        ),
        on="product_view_id",
        how="inner",
    )

    assert joined.height == items.height
    assert joined.filter(pl.col("product_id") != pl.col("viewed_product")).height == 0
    assert joined.filter(pl.col("customer_id") != pl.col("viewing_customer")).height == 0


def test_wishlist_items_match_their_wishlist_entry(
    items: pl.DataFrame, commerce_upstream: dict[str, pl.DataFrame]
) -> None:
    """A wishlist-sourced product matches the saved product."""
    joined = items.filter(pl.col("wishlist_id").is_not_null()).join(
        commerce_upstream["wishlists"].select(
            "wishlist_id", pl.col("product_id").alias("saved_product")
        ),
        on="wishlist_id",
        how="inner",
    )

    assert joined.filter(pl.col("product_id") != pl.col("saved_product")).height == 0


def test_no_product_repeats_within_a_cart(items: pl.DataFrame) -> None:
    """Quantity carries repeats; a product appears once per cart."""
    pairs = items.select("cart_id", "product_id")

    assert pairs.n_unique() == pairs.height


def test_quantities_stay_within_the_configured_bounds(
    items: pl.DataFrame, config: CommerceConfig
) -> None:
    """Between one and five units of a product are added."""
    quantities = items["quantity"].to_list()

    assert min(quantities) >= config.min_quantity
    assert max(quantities) <= config.max_quantity


def test_quantity_distribution_is_approximately_as_specified(
    items: pl.DataFrame,
) -> None:
    """Most items are a single unit."""
    quantities = items["quantity"].to_list()
    share = quantities.count(1) / len(quantities)

    assert share == pytest.approx(0.70, abs=0.10)


def test_unit_prices_match_the_product_catalog(
    items: pl.DataFrame, commerce_upstream: dict[str, pl.DataFrame]
) -> None:
    """The recorded price is the product's list price."""
    joined = items.join(
        commerce_upstream["products"].select(
            "product_id", pl.col("list_price").alias("catalog_price")
        ),
        on="product_id",
        how="inner",
    )

    assert joined.height == items.height
    assert joined.filter(pl.col("unit_price") != pl.col("catalog_price")).height == 0


def test_items_are_added_after_the_product_was_viewed(
    items: pl.DataFrame, commerce_upstream: dict[str, pl.DataFrame]
) -> None:
    """Chronology holds: view first, then add."""
    joined = items.join(
        commerce_upstream["product_views"].select(
            "product_view_id", pl.col("timestamp").alias("viewed_at")
        ),
        on="product_view_id",
    )

    assert joined.filter(pl.col("added_at") <= pl.col("viewed_at")).height == 0


def test_wishlist_items_are_added_after_they_were_saved(
    items: pl.DataFrame, commerce_upstream: dict[str, pl.DataFrame]
) -> None:
    """A wishlist entry is saved before it reaches the cart."""
    joined = items.filter(pl.col("wishlist_id").is_not_null()).join(
        commerce_upstream["wishlists"].select("wishlist_id", pl.col("timestamp").alias("saved_at")),
        on="wishlist_id",
    )

    assert joined.filter(pl.col("added_at") <= pl.col("saved_at")).height == 0


def test_removed_items_are_removed_after_being_added(items: pl.DataFrame) -> None:
    """A removal never predates the add."""
    removed = items.filter(pl.col("removed_at").is_not_null())

    assert removed.height > 0
    assert removed.filter(pl.col("removed_at") <= pl.col("added_at")).height == 0


def test_most_items_are_never_removed(items: pl.DataFrame) -> None:
    """Removal is the exception, matching the configured rate."""
    removed = items.filter(pl.col("removed_at").is_not_null()).height

    assert removed / items.height == pytest.approx(0.12, abs=0.06)


def test_items_fall_inside_the_cart_window(items: pl.DataFrame, carts: pl.DataFrame) -> None:
    """An item is added between the cart being opened and last touched."""
    joined = items.join(
        carts.select("cart_id", "created_at", "updated_at"), on="cart_id", how="inner"
    )

    assert joined.height == items.height
    assert joined.filter(pl.col("added_at") < pl.col("created_at")).height == 0
    assert joined.filter(pl.col("added_at") > pl.col("updated_at")).height == 0


def test_batching_does_not_change_the_output(planned: list, sources: CartSources) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = generate_cart_items(CommerceConfig(batch_size=11), planned, sources, SEED)
    large = generate_cart_items(CommerceConfig(batch_size=1_000_000), planned, sources, SEED)

    assert small.equals(large)


def test_batches_never_split_a_cart(planned: list, sources: CartSources) -> None:
    """A cart's items always land in one frame."""
    seen: set[int] = set()

    for batch in iter_cart_item_batches(CommerceConfig(batch_size=100), planned, sources, SEED):
        in_batch = set(batch["cart_id"].to_list())
        assert not (in_batch & seen)
        seen |= in_batch


def test_generation_is_deterministic(
    config: CommerceConfig, planned: list, sources: CartSources
) -> None:
    """The same seed reproduces the same items."""
    first = generate_cart_items(config, planned, sources, SEED)
    second = generate_cart_items(config, planned, sources, SEED)

    assert first.equals(second)


def test_generation_varies_with_the_seed(
    config: CommerceConfig, planned: list, sources: CartSources
) -> None:
    """A different seed produces different items."""
    first = generate_cart_items(config, planned, sources, 1)
    second = generate_cart_items(config, planned, sources, 2)

    assert not first.equals(second)


def test_no_planned_carts_produces_no_items(config: CommerceConfig, sources: CartSources) -> None:
    """Without carts there is nothing to fill."""
    result = generate_cart_items(config, [], sources, SEED)

    assert result.height == 0
