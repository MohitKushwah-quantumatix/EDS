"""Generator for the wishlists dataset.

Every wishlist entry originates from a product view the customer actually
made, so a wishlist can never contain a product the customer never saw.

Wishlist usage is modelled in two stages, which is what keeps it to the small
minority of customers the specification expects:

* **Adoption.** Most people never use a wishlist at all. Each customer is
  first decided to be a wishlist user or not, from a per-persona adoption
  rate. Only adopters go on to the second stage.
* **Adding.** For an adopter, each product view is a chance to add, scaled
  from the persona's own ``wishlist_probability`` recorded in F003.1.

A single per-view probability could not produce the documented outcome: with
around eighty views per customer, any rate high enough to fill a wishlist
would give almost every customer one.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import polars as pl

from eds.config import EngagementConfig
from eds.core.frames import build_frame, empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.journey.schema import WISHLISTS
from eds.domains.retail.generators.journey.product_view_generator import persona_engagement_profile

__all__ = ["generate_wishlists", "iter_wishlist_batches"]

# A wishlist entry is saved a moment after the product page was opened.
_MIN_DELAY_SECONDS: Final[int] = 1


@dataclass(frozen=True, slots=True)
class _Customer:
    """The per-customer inputs the wishlist stage needs."""

    persona_name: str
    wishlist_probability: float


def _customer_inputs(personas: pl.DataFrame) -> dict[int, _Customer]:
    """Extract persona name and propensity for each customer.

    Args:
        personas: The F003.1 customer personas dataset.

    Returns:
        Customer id to its persona inputs.
    """
    return {
        customer_id: _Customer(persona_name, probability)
        for customer_id, persona_name, probability in zip(
            personas["customer_id"].to_list(),
            personas["persona_name"].to_list(),
            personas["wishlist_probability"].to_list(),
            strict=True,
        )
    }


def iter_wishlist_batches(
    config: EngagementConfig,
    personas: pl.DataFrame,
    product_views: pl.DataFrame,
    sessions: pl.DataFrame,
    seed: int,
) -> Iterator[pl.DataFrame]:
    """Yield wishlist entries in batches.

    Args:
        config: Engagement configuration.
        personas: The F003.1 customer personas dataset.
        product_views: The generated product views dataset.
        sessions: The F003.1 sessions dataset, used to keep entries inside
            the session they were saved during.
        seed: Run seed.

    Yields:
        Frames matching the wishlists schema.

    Raises:
        KeyError: If a customer names a persona with no engagement profile.
    """
    rng = make_rng(seed, "wishlists")
    inputs = _customer_inputs(personas)

    session_end: dict[int, datetime] = dict(
        zip(sessions["session_id"].to_list(), sessions["end_time"].to_list(), strict=True)
    )

    # Adoption is decided once per customer, before any product view is seen.
    adopters: dict[int, bool] = {}
    for customer_id in sorted(inputs):
        profile = persona_engagement_profile(inputs[customer_id].persona_name)
        adopters[customer_id] = rng.random() < profile.wishlist_adoption

    wishlist_ids: list[int] = []
    customer_ids: list[int] = []
    view_ids: list[int] = []
    product_ids: list[int] = []
    sources: list[str] = []
    timestamps: list[datetime] = []
    created: list[datetime] = []

    next_wishlist_id = 1
    # A customer may add any given product only once.
    seen: set[tuple[int, int]] = set()

    def flush() -> pl.DataFrame:
        """Build a frame from the accumulated rows and reset the buffers."""
        frame = build_frame(
            WISHLISTS,
            {
                "wishlist_id": wishlist_ids,
                "customer_id": customer_ids,
                "product_view_id": view_ids,
                "product_id": product_ids,
                "added_from_source": sources,
                "timestamp": timestamps,
                "created_at": created,
            },
        )
        for buffer in (
            wishlist_ids,
            customer_ids,
            view_ids,
            product_ids,
            sources,
            timestamps,
            created,
        ):
            buffer.clear()
        return frame

    for view_id, customer_id, session_id, product_id, source, moment, duration in zip(
        product_views["product_view_id"].to_list(),
        product_views["customer_id"].to_list(),
        product_views["session_id"].to_list(),
        product_views["product_id"].to_list(),
        product_views["view_source"].to_list(),
        product_views["timestamp"].to_list(),
        product_views["view_duration_seconds"].to_list(),
        strict=True,
    ):
        if not adopters.get(customer_id, False):
            continue

        key = (customer_id, product_id)
        if key in seen:
            continue

        propensity = inputs[customer_id].wishlist_probability
        if rng.random() >= propensity * config.wishlist_view_rate:
            continue

        seen.add(key)
        # Saved while still on the product page, and never after the session.
        saved_at = moment + timedelta(seconds=max(_MIN_DELAY_SECONDS, duration))
        ends_at = session_end.get(session_id)
        if ends_at is not None and saved_at > ends_at:
            saved_at = ends_at

        wishlist_ids.append(next_wishlist_id)
        customer_ids.append(customer_id)
        view_ids.append(view_id)
        product_ids.append(product_id)
        sources.append(source)
        timestamps.append(saved_at)
        created.append(saved_at)
        next_wishlist_id += 1

        if len(wishlist_ids) >= config.batch_size:
            yield flush()

    if wishlist_ids:
        yield flush()


def generate_wishlists(
    config: EngagementConfig,
    personas: pl.DataFrame,
    product_views: pl.DataFrame,
    sessions: pl.DataFrame,
    seed: int,
) -> pl.DataFrame:
    """Generate the complete wishlists dataset.

    Args:
        config: Engagement configuration.
        personas: The F003.1 customer personas dataset.
        product_views: The generated product views dataset.
        sessions: The F003.1 sessions dataset.
        seed: Run seed.

    Returns:
        One row per saved product, keyed by sequential ``wishlist_id``, with
        no customer holding the same product twice.

    Raises:
        KeyError: If a customer names a persona with no engagement profile.
    """
    batches = list(iter_wishlist_batches(config, personas, product_views, sessions, seed))
    return pl.concat(batches, how="vertical") if batches else empty_frame(WISHLISTS)
