"""Generator for the cart items dataset.

Every item traces back to something the customer actually saw. An item is
added either straight from a product view in the same session, or from a
wishlist entry saved earlier - and a wishlist entry itself records the product
view it came from, so ``product_view_id`` is always populated and the product
always matches its source.

Nothing is ever chosen from the product catalog directly.
"""

from __future__ import annotations

import random
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import polars as pl

from eds.config import CommerceConfig
from eds.core.frames import build_frame, empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.commerce.enums import CartItemSource
from eds.domains.retail.domain.commerce.schema import CART_ITEMS
from eds.domains.retail.generators.commerce.cart_generator import (
    CART_OPENED_LEAD_SECONDS,
    PlannedCart,
    persona_cart_profile,
)

__all__ = ["CartSources", "QUANTITY_WEIGHTS", "generate_cart_items", "iter_cart_item_batches"]

#: Units of a single product, for quantities one through five.
QUANTITY_WEIGHTS: Final[tuple[int, ...]] = (70, 18, 7, 3, 2)

# An item is added a short while after the customer saw the product.
_ADD_DELAY_SECONDS: Final[tuple[int, int]] = (1, 120)
# A removed item goes back out of the cart later in the same session.
_REMOVE_DELAY_SECONDS: Final[tuple[int, int]] = (1, 300)


@dataclass(frozen=True, slots=True)
class _Source:
    """One thing a cart item can be added from."""

    product_view_id: int
    product_id: int
    wishlist_id: int | None
    happened_at: datetime


@dataclass(frozen=True, slots=True)
class CartSources:
    """Everything a cart can be filled from.

    Attributes:
        views_by_session: Session id to the product views made in it.
        wishlist_by_customer: Customer id to their wishlist entries.
        price_by_product: Product id to its list price.
    """

    views_by_session: Mapping[int, list[_Source]]
    wishlist_by_customer: Mapping[int, list[_Source]]
    price_by_product: Mapping[int, float]

    @classmethod
    def from_frames(
        cls, product_views: pl.DataFrame, wishlists: pl.DataFrame, products: pl.DataFrame
    ) -> CartSources:
        """Build the lookup from the upstream datasets.

        Args:
            product_views: The F003.3 product views dataset.
            wishlists: The F003.3 wishlists dataset.
            products: The F001 products dataset, supplying list prices.

        Returns:
            The extracted sources.

        Raises:
            ValueError: If product views or products are empty, leaving
                nothing a cart could be filled from.
        """
        if product_views.is_empty():
            raise ValueError("cannot generate cart items: the product views dataset is empty")
        if products.is_empty():
            raise ValueError("cannot generate cart items: the products dataset is empty")

        views_by_session: dict[int, list[_Source]] = {}
        for view_id, session_id, product_id, moment in zip(
            product_views["product_view_id"].to_list(),
            product_views["session_id"].to_list(),
            product_views["product_id"].to_list(),
            product_views["timestamp"].to_list(),
            strict=True,
        ):
            views_by_session.setdefault(session_id, []).append(
                _Source(view_id, product_id, None, moment)
            )

        wishlist_by_customer: dict[int, list[_Source]] = {}
        for wishlist_id, customer_id, view_id, product_id, moment in zip(
            wishlists["wishlist_id"].to_list(),
            wishlists["customer_id"].to_list(),
            wishlists["product_view_id"].to_list(),
            wishlists["product_id"].to_list(),
            wishlists["timestamp"].to_list(),
            strict=True,
        ):
            wishlist_by_customer.setdefault(customer_id, []).append(
                _Source(view_id, product_id, wishlist_id, moment)
            )

        return cls(
            views_by_session=views_by_session,
            wishlist_by_customer=wishlist_by_customer,
            price_by_product=dict(
                zip(
                    products["product_id"].to_list(),
                    products["list_price"].to_list(),
                    strict=True,
                )
            ),
        )


def _quantity(rng: random.Random, config: CommerceConfig) -> int:
    """Sample how many units of a product were added.

    Args:
        rng: Random source.
        config: Global commerce bounds.

    Returns:
        A quantity inside the configured range, mostly one.
    """
    options = list(range(config.min_quantity, config.max_quantity + 1))
    weights = QUANTITY_WEIGHTS[: len(options)] or (1,) * len(options)
    return rng.choices(options, weights=list(weights)[: len(options)], k=1)[0]


def _pick_sources(
    rng: random.Random,
    cart: PlannedCart,
    sources: CartSources,
    wishlist_rate: float,
) -> list[_Source]:
    """Choose the distinct products a cart is filled with.

    Args:
        rng: Random source.
        cart: The planned cart.
        sources: Everything the cart can be filled from.
        wishlist_rate: Chance of reaching for the wishlist instead.

    Returns:
        One source per distinct product, in the order they were chosen.
    """
    views = sources.views_by_session.get(cart.session_id, [])
    # Only entries saved before the cart closes can be added to it.
    saved = [
        entry
        for entry in sources.wishlist_by_customer.get(cart.customer_id, [])
        if entry.happened_at < cart.session_end
    ]
    if not views and not saved:
        return []

    chosen: list[_Source] = []
    seen: set[int] = set()
    for _ in range(cart.target_size):
        pool = saved if (saved and rng.random() < wishlist_rate) else views
        if not pool:
            pool = views or saved
        if not pool:
            break
        candidate = rng.choice(pool)
        # One row per product; quantity carries repeats.
        if candidate.product_id in seen:
            continue
        seen.add(candidate.product_id)
        chosen.append(candidate)
    return chosen


def iter_cart_item_batches(
    config: CommerceConfig,
    planned: Sequence[PlannedCart],
    sources: CartSources,
    seed: int,
) -> Iterator[pl.DataFrame]:
    """Yield cart items in batches, grouped by cart.

    Args:
        config: Commerce configuration.
        planned: The planned carts.
        sources: Everything the carts can be filled from.
        seed: Run seed.

    Yields:
        Frames matching the cart items schema. A cart's items are never split
        across two frames.

    Raises:
        KeyError: If a cart names a persona with no cart profile.
    """
    rng = make_rng(seed, "cart_items")

    item_ids: list[int] = []
    cart_ids: list[int] = []
    customer_ids: list[int] = []
    product_ids: list[int] = []
    view_ids: list[int] = []
    wishlist_ids: list[int | None] = []
    quantities: list[int] = []
    prices: list[float] = []
    origins: list[str] = []
    added: list[datetime] = []
    removed: list[datetime | None] = []

    next_item_id = 1

    def flush() -> pl.DataFrame:
        """Build a frame from the accumulated rows and reset the buffers."""
        frame = build_frame(
            CART_ITEMS,
            {
                "cart_item_id": item_ids,
                "cart_id": cart_ids,
                "customer_id": customer_ids,
                "product_id": product_ids,
                "product_view_id": view_ids,
                "wishlist_id": wishlist_ids,
                "quantity": quantities,
                "unit_price": prices,
                "added_from": origins,
                "added_at": added,
                "removed_at": removed,
            },
        )
        for buffer in (
            item_ids,
            cart_ids,
            customer_ids,
            product_ids,
            view_ids,
            wishlist_ids,
            quantities,
            prices,
            origins,
            added,
            removed,
        ):
            buffer.clear()
        return frame

    for cart in planned:
        profile = persona_cart_profile(cart.persona_name)
        # Leave a second for the cart to be updated before the session closes.
        latest_add = cart.session_end - timedelta(seconds=1)

        for source in _pick_sources(rng, cart, sources, profile.wishlist_rate):
            # The add happens during this session, even when the product was
            # saved to the wishlist during an earlier one. The floor leaves
            # room for the cart to be opened a second before its first item.
            earliest = max(
                source.happened_at + timedelta(seconds=_ADD_DELAY_SECONDS[0]),
                cart.session_start + timedelta(seconds=CART_OPENED_LEAD_SECONDS),
            )
            if earliest > latest_add:
                # No room to add this before the session ends.
                continue

            delay = rng.randint(*_ADD_DELAY_SECONDS)
            added_at = min(max(source.happened_at + timedelta(seconds=delay), earliest), latest_add)

            removed_at: datetime | None = None
            if rng.random() < config.removal_rate:
                removed_at = min(
                    added_at + timedelta(seconds=rng.randint(*_REMOVE_DELAY_SECONDS)),
                    cart.session_end,
                )

            from_wishlist = source.wishlist_id is not None
            item_ids.append(next_item_id)
            cart_ids.append(cart.cart_id)
            customer_ids.append(cart.customer_id)
            product_ids.append(source.product_id)
            view_ids.append(source.product_view_id)
            wishlist_ids.append(source.wishlist_id)
            quantities.append(_quantity(rng, config))
            prices.append(sources.price_by_product.get(source.product_id, 0.0))
            origins.append(
                str(CartItemSource.WISHLIST if from_wishlist else CartItemSource.PRODUCT_VIEW)
            )
            added.append(added_at)
            removed.append(removed_at)
            next_item_id += 1

        if len(item_ids) >= config.batch_size:
            yield flush()

    if item_ids:
        yield flush()


def generate_cart_items(
    config: CommerceConfig,
    planned: Sequence[PlannedCart],
    sources: CartSources,
    seed: int,
) -> pl.DataFrame:
    """Generate the complete cart items dataset.

    Args:
        config: Commerce configuration.
        planned: The planned carts.
        sources: Everything the carts can be filled from.
        seed: Run seed.

    Returns:
        One row per distinct product in a cart, keyed by sequential
        ``cart_item_id``.

    Raises:
        KeyError: If a cart names a persona with no cart profile.
    """
    batches = list(iter_cart_item_batches(config, planned, sources, seed))
    return pl.concat(batches, how="vertical") if batches else empty_frame(CART_ITEMS)
