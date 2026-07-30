"""Generator for the shopping carts dataset.

Cart creation happens in two stages, because a cart's own columns depend on
the items it ends up holding:

* :func:`plan_carts` decides which sessions start a cart, and with what status
  and target size. It reads the persona's ``cart_probability`` recorded in
  F003.1, so a loyal customer fills a cart more often than a window shopper.
* :func:`build_carts` turns the plan plus the generated items into rows. Doing
  it this way means ``item_count`` is counted from the items rather than
  asserted alongside them, and ``created_at`` and ``updated_at`` bracket the
  real add and remove times.

A bounced session never starts a cart: the customer viewed one page and left.
"""

from __future__ import annotations

import random
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import polars as pl

from eds.config import CommerceConfig
from eds.core.frames import build_frame, empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.commerce.enums import CartStatus
from eds.domains.retail.domain.commerce.schema import SHOPPING_CARTS
from eds.domains.retail.domain.journey.enums import PersonaName

__all__ = [
    "CART_OPENED_LEAD_SECONDS",
    "CART_SIZE_WEIGHTS",
    "PERSONA_CART_PROFILES",
    "PersonaCartProfile",
    "PlannedCart",
    "build_carts",
    "generate_carts",
    "persona_cart_profile",
    "plan_carts",
]


@dataclass(frozen=True, slots=True)
class PersonaCartProfile:
    """How one persona fills and finishes a cart.

    Attributes:
        size_weights: Relative frequency of cart sizes one through five,
            where five is the "five or more" bucket.
        status_weights: Relative frequency of abandoned, checked out, and
            active, in that order.
        wishlist_rate: Chance an item is added from the wishlist rather than
            straight from a product view.
    """

    size_weights: tuple[int, ...]
    status_weights: tuple[int, ...]
    wishlist_rate: float


_STATUSES: Final[tuple[CartStatus, ...]] = (
    CartStatus.ABANDONED,
    CartStatus.CHECKED_OUT,
    CartStatus.ACTIVE,
)

#: The overall cart size split the specification suggests, used as the
#: reference the per-persona weights vary around.
CART_SIZE_WEIGHTS: Final[tuple[int, ...]] = (55, 25, 12, 5, 3)

#: Per-persona cart behaviour. Sizes and statuses vary around the documented
#: overall splits so the persona guidance is visible without pulling the
#: marginal distributions away from their targets.
PERSONA_CART_PROFILES: Final[dict[str, PersonaCartProfile]] = {
    # "Largest carts. Frequently wishlists before cart."
    str(PersonaName.RESEARCHER): PersonaCartProfile(
        size_weights=(30, 28, 22, 12, 8),
        status_weights=(65, 30, 5),
        wishlist_rate=0.35,
    ),
    # "Occasional carts. Mostly abandoned."
    str(PersonaName.WINDOW_SHOPPER): PersonaCartProfile(
        size_weights=(65, 22, 8, 3, 2),
        status_weights=(80, 15, 5),
        wishlist_rate=0.18,
    ),
    # "Higher cart rate. Frequently promotion-driven."
    str(PersonaName.BARGAIN_HUNTER): PersonaCartProfile(
        size_weights=(45, 28, 15, 7, 5),
        status_weights=(63, 32, 5),
        wishlist_rate=0.20,
    ),
    # "Highest checkout probability. Moderate cart size."
    str(PersonaName.LOYAL_CUSTOMER): PersonaCartProfile(
        size_weights=(48, 28, 15, 6, 3),
        status_weights=(30, 65, 5),
        wishlist_rate=0.15,
    ),
    # "Small carts. High checkout probability. Rare wishlist."
    str(PersonaName.IMPULSE_BUYER): PersonaCartProfile(
        size_weights=(75, 18, 5, 1, 1),
        status_weights=(42, 53, 5),
        wishlist_rate=0.03,
    ),
    # "Lowest activity."
    str(PersonaName.SEASONAL_SHOPPER): PersonaCartProfile(
        size_weights=(58, 25, 11, 4, 2),
        status_weights=(60, 35, 5),
        wishlist_rate=0.12,
    ),
}

_SIZE_BUCKETS: Final[tuple[int, ...]] = (1, 2, 3, 4, 5)

#: A cart is opened this many seconds before its first item lands in it. The
#: item generator keeps the same lead clear at the start of the session.
CART_OPENED_LEAD_SECONDS: Final[int] = 1


@dataclass(frozen=True, slots=True)
class PlannedCart:
    """A cart that will be filled, before its items exist.

    Attributes:
        cart_id: The identifier the cart will carry.
        customer_id: Owning customer.
        session_id: The session the cart was started in.
        persona_name: The customer's persona, driving item selection.
        status: Where the cart ends up.
        target_size: How many distinct products to try to add.
        session_start: The moment the session opens.
        session_end: The moment the session closes.
    """

    cart_id: int
    customer_id: int
    session_id: int
    persona_name: str
    status: CartStatus
    target_size: int
    session_start: datetime
    session_end: datetime


def persona_cart_profile(persona_name: str) -> PersonaCartProfile:
    """Look up the cart profile for a persona.

    Args:
        persona_name: Persona name, such as ``"LOYAL_CUSTOMER"``.

    Returns:
        The matching profile.

    Raises:
        KeyError: If the persona has no cart profile.
    """
    try:
        return PERSONA_CART_PROFILES[persona_name]
    except KeyError:
        raise KeyError(
            f"Unknown persona: {persona_name!r}. Supported personas: {tuple(PERSONA_CART_PROFILES)}"
        ) from None


def _target_size(rng: random.Random, profile: PersonaCartProfile, config: CommerceConfig) -> int:
    """Decide how many distinct products a cart aims to hold.

    Args:
        rng: Random source.
        profile: The persona's cart profile.
        config: Global commerce bounds.

    Returns:
        A size of at least one, bounded by ``max_cart_items``. The top bucket
        represents "five or more" and is spread across the remaining room.
    """
    bucket = rng.choices(_SIZE_BUCKETS, weights=profile.size_weights, k=1)[0]
    if bucket < _SIZE_BUCKETS[-1]:
        return min(bucket, config.max_cart_items)
    return rng.randint(min(bucket, config.max_cart_items), config.max_cart_items)


def plan_carts(
    config: CommerceConfig,
    sessions: pl.DataFrame,
    personas: pl.DataFrame,
    seed: int,
) -> list[PlannedCart]:
    """Decide which sessions start a cart.

    Args:
        config: Commerce configuration.
        sessions: The F003.1 sessions dataset.
        personas: The F003.1 customer personas dataset, supplying each
            customer's cart propensity.
        seed: Run seed.

    Returns:
        One planned cart per session that starts one, in session order.

    Raises:
        KeyError: If a session names a persona with no cart profile.
    """
    rng = make_rng(seed, "shopping_carts")

    propensity: dict[int, float] = dict(
        zip(
            personas["customer_id"].to_list(),
            personas["cart_probability"].to_list(),
            strict=True,
        )
    )

    planned: list[PlannedCart] = []
    next_cart_id = 1
    for session_id, customer_id, persona_name, bounce, start_time, end_time in zip(
        sessions["session_id"].to_list(),
        sessions["customer_id"].to_list(),
        sessions["persona_name"].to_list(),
        sessions["bounce"].to_list(),
        sessions["start_time"].to_list(),
        sessions["end_time"].to_list(),
        strict=True,
    ):
        profile = persona_cart_profile(persona_name)
        # A bounce is a single page view; nothing reaches a cart from it.
        if bounce:
            continue
        chance = propensity.get(customer_id, 0.0) * config.cart_session_rate
        if rng.random() >= chance:
            continue

        planned.append(
            PlannedCart(
                cart_id=next_cart_id,
                customer_id=customer_id,
                session_id=session_id,
                persona_name=persona_name,
                status=rng.choices(_STATUSES, weights=profile.status_weights, k=1)[0],
                target_size=_target_size(rng, profile, config),
                session_start=start_time,
                session_end=end_time,
            )
        )
        next_cart_id += 1
    return planned


def build_carts(
    planned: Sequence[PlannedCart], cart_items: pl.DataFrame, batch_size: int
) -> Iterator[pl.DataFrame]:
    """Yield cart rows built from the plan and the items that were added.

    A planned cart that ended up with no items is dropped, because every cart
    must contain at least one item.

    Args:
        planned: The planned carts.
        cart_items: The generated cart items.
        batch_size: Rows per emitted frame.

    Yields:
        Frames matching the shopping carts schema.
    """
    counts: dict[int, int] = {}
    earliest: dict[int, datetime] = {}
    latest: dict[int, datetime] = {}

    for cart_id, added_at, removed_at in zip(
        cart_items["cart_id"].to_list(),
        cart_items["added_at"].to_list(),
        cart_items["removed_at"].to_list(),
        strict=True,
    ):
        counts[cart_id] = counts.get(cart_id, 0) + 1
        if cart_id not in earliest or added_at < earliest[cart_id]:
            earliest[cart_id] = added_at
        touched = removed_at if removed_at is not None else added_at
        if cart_id not in latest or touched > latest[cart_id]:
            latest[cart_id] = touched

    cart_ids: list[int] = []
    customer_ids: list[int] = []
    session_ids: list[int] = []
    statuses: list[str] = []
    item_counts: list[int] = []
    created: list[datetime] = []
    updated: list[datetime] = []

    def flush() -> pl.DataFrame:
        """Build a frame from the accumulated rows and reset the buffers."""
        frame = build_frame(
            SHOPPING_CARTS,
            {
                "cart_id": cart_ids,
                "customer_id": customer_ids,
                "session_id": session_ids,
                "cart_status": statuses,
                "item_count": item_counts,
                "created_at": created,
                "updated_at": updated,
            },
        )
        for buffer in (
            cart_ids,
            customer_ids,
            session_ids,
            statuses,
            item_counts,
            created,
            updated,
        ):
            buffer.clear()
        return frame

    for cart in planned:
        count = counts.get(cart.cart_id, 0)
        if count == 0:
            continue

        opened = earliest[cart.cart_id] - timedelta(seconds=CART_OPENED_LEAD_SECONDS)
        cart_ids.append(cart.cart_id)
        customer_ids.append(cart.customer_id)
        session_ids.append(cart.session_id)
        statuses.append(str(cart.status))
        item_counts.append(count)
        created.append(opened)
        updated.append(latest[cart.cart_id])

        if len(cart_ids) >= batch_size:
            yield flush()

    if cart_ids:
        yield flush()


def generate_carts(
    planned: Sequence[PlannedCart], cart_items: pl.DataFrame, batch_size: int
) -> pl.DataFrame:
    """Build the complete shopping carts dataset.

    Args:
        planned: The planned carts.
        cart_items: The generated cart items.
        batch_size: Rows per intermediate frame.

    Returns:
        One row per cart that holds at least one item.
    """
    batches = list(build_carts(planned, cart_items, batch_size))
    return pl.concat(batches, how="vertical") if batches else empty_frame(SHOPPING_CARTS)
