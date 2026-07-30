"""Generator for the customer personas dataset.

Every customer receives exactly one persona drawn from the documented
distribution. The persona's behaviour profile then fixes two numbers the
session generator depends on:

* ``session_frequency`` - how many sessions this customer actually has.
* ``average_session_minutes`` - the centre of their session duration.

Storing the *actual* session count rather than a nominal rate means the two
datasets can be checked against each other directly: a test asserts the row
count per customer in ``sessions`` equals ``session_frequency``.

Session counts are scaled by **tenure**. A customer who registered last month
has not had five years in which to browse, so their count is reduced towards
the floor. Without this the dataset would imply every customer joined on day
one.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import date, datetime
from typing import Final, NamedTuple

import polars as pl

from eds.config import CustomerConfig, JourneyConfig
from eds.core.frames import build_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.journey.enums import PersonaName
from eds.domains.retail.domain.journey.schema import CUSTOMER_PERSONAS

__all__ = [
    "PERSONA_PROFILES",
    "PersonaProfile",
    "generate_personas",
    "iter_persona_batches",
    "persona_profile",
]


class PersonaProfile(NamedTuple):
    """The behaviour envelope for one persona.

    Attributes:
        name: The persona.
        description: Human-readable summary used in the dataset.
        min_sessions: Fewest sessions over the full window.
        max_sessions: Most sessions over the full window.
        min_minutes: Shortest average session length, in minutes.
        max_minutes: Longest average session length, in minutes.
        purchase_intent: Range for how ready to buy the customer is.
        price_sensitivity: Range for how strongly price drives them.
        brand_loyalty: Range for how strongly brand drives them.
        research_depth: Range for how much comparison they do.
        wishlist_probability: Range for the wishlist propensity.
        cart_probability: Range for the add-to-cart propensity.
        purchase_ratio: Fraction of carts that convert. Purchase probability
            is derived from this so it can never exceed cart probability.
        max_pages: Upper bound on pages viewed in one non-bounce session.
    """

    name: PersonaName
    description: str
    min_sessions: int
    max_sessions: int
    min_minutes: float
    max_minutes: float
    purchase_intent: tuple[float, float]
    price_sensitivity: tuple[float, float]
    brand_loyalty: tuple[float, float]
    research_depth: tuple[float, float]
    wishlist_probability: tuple[float, float]
    cart_probability: tuple[float, float]
    purchase_ratio: tuple[float, float]
    max_pages: int


PERSONA_PROFILES: Final[tuple[PersonaProfile, ...]] = (
    PersonaProfile(
        name=PersonaName.WINDOW_SHOPPER,
        description="Visits frequently, looks around, rarely purchases.",
        min_sessions=5,
        max_sessions=15,
        min_minutes=10.0,
        max_minutes=20.0,
        purchase_intent=(0.05, 0.20),
        price_sensitivity=(0.40, 0.70),
        brand_loyalty=(0.20, 0.50),
        research_depth=(0.30, 0.60),
        wishlist_probability=(0.25, 0.45),
        cart_probability=(0.10, 0.25),
        purchase_ratio=(0.10, 0.30),
        max_pages=12,
    ),
    PersonaProfile(
        name=PersonaName.RESEARCHER,
        description="Long sessions, many product comparisons, very analytical.",
        min_sessions=10,
        max_sessions=20,
        min_minutes=20.0,
        max_minutes=45.0,
        purchase_intent=(0.35, 0.60),
        price_sensitivity=(0.50, 0.80),
        brand_loyalty=(0.30, 0.60),
        research_depth=(0.80, 1.00),
        wishlist_probability=(0.35, 0.60),
        cart_probability=(0.30, 0.50),
        purchase_ratio=(0.35, 0.60),
        max_pages=25,
    ),
    PersonaProfile(
        name=PersonaName.BARGAIN_HUNTER,
        description="Searches extensively, responds to discounts, price conscious.",
        min_sessions=6,
        max_sessions=15,
        min_minutes=10.0,
        max_minutes=25.0,
        purchase_intent=(0.40, 0.65),
        price_sensitivity=(0.85, 1.00),
        brand_loyalty=(0.10, 0.35),
        research_depth=(0.60, 0.85),
        wishlist_probability=(0.40, 0.65),
        cart_probability=(0.35, 0.55),
        purchase_ratio=(0.40, 0.65),
        max_pages=18,
    ),
    PersonaProfile(
        name=PersonaName.LOYAL_CUSTOMER,
        description="Returns regularly, shops familiar brands, high purchase likelihood.",
        min_sessions=4,
        max_sessions=10,
        min_minutes=8.0,
        max_minutes=18.0,
        purchase_intent=(0.65, 0.90),
        price_sensitivity=(0.20, 0.50),
        brand_loyalty=(0.80, 1.00),
        research_depth=(0.20, 0.50),
        wishlist_probability=(0.20, 0.40),
        cart_probability=(0.55, 0.80),
        purchase_ratio=(0.70, 0.90),
        max_pages=12,
    ),
    PersonaProfile(
        name=PersonaName.IMPULSE_BUYER,
        description="Very short decision cycle, few page views, quick purchase.",
        min_sessions=1,
        max_sessions=5,
        min_minutes=2.0,
        max_minutes=8.0,
        purchase_intent=(0.60, 0.85),
        price_sensitivity=(0.10, 0.40),
        brand_loyalty=(0.30, 0.60),
        research_depth=(0.05, 0.25),
        wishlist_probability=(0.05, 0.20),
        cart_probability=(0.50, 0.75),
        purchase_ratio=(0.75, 0.95),
        max_pages=6,
    ),
    PersonaProfile(
        name=PersonaName.SEASONAL_SHOPPER,
        description="Mostly inactive, highly active during holidays.",
        min_sessions=0,
        max_sessions=5,
        min_minutes=5.0,
        max_minutes=15.0,
        purchase_intent=(0.30, 0.55),
        price_sensitivity=(0.50, 0.80),
        brand_loyalty=(0.30, 0.60),
        research_depth=(0.30, 0.60),
        wishlist_probability=(0.25, 0.45),
        cart_probability=(0.25, 0.45),
        purchase_ratio=(0.40, 0.65),
        max_pages=12,
    ),
)

_PERSONA_WEIGHTS: Final[tuple[int, ...]] = (25, 20, 20, 20, 10, 5)

_BY_NAME: Final[dict[str, PersonaProfile]] = {
    str(profile.name): profile for profile in PERSONA_PROFILES
}

# A customer with no tenure still browses a little; a customer with the full
# window browses at their persona's nominal rate.
_TENURE_FLOOR: Final[float] = 0.25
_DAYS_PER_YEAR: Final[int] = 365


def persona_profile(name: str) -> PersonaProfile:
    """Look up a behaviour profile by persona name.

    Args:
        name: Persona name, such as ``"RESEARCHER"``.

    Returns:
        The matching profile.

    Raises:
        KeyError: If the persona is not one of the supported six.
    """
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown persona: {name!r}. Supported personas: {tuple(_BY_NAME)}"
        ) from None


def _tenure_weight(registration: date, reference: date, window_years: int) -> float:
    """Scale a session count by how long the customer has been registered.

    Args:
        registration: When the customer registered.
        reference: The dataset's as-of date.
        window_years: The session window in years.

    Returns:
        A multiplier between the tenure floor and 1.0.
    """
    span_days = window_years * _DAYS_PER_YEAR
    tenure_days = max(0, (reference - registration).days)
    fraction = min(1.0, tenure_days / span_days)
    return _TENURE_FLOOR + (1.0 - _TENURE_FLOOR) * fraction


def _sample(rng: random.Random, bounds: tuple[float, float]) -> float:
    """Sample a trait score from an inclusive range.

    Args:
        rng: Random source.
        bounds: Lower and upper bound.

    Returns:
        A value rounded to four decimals.
    """
    return round(rng.uniform(*bounds), 4)


def iter_persona_batches(
    customer_config: CustomerConfig,
    journey_config: JourneyConfig,
    customers: pl.DataFrame,
    seed: int,
) -> Iterator[pl.DataFrame]:
    """Yield personas in batches, one per customer.

    Args:
        customer_config: Customer configuration, supplying the reference date.
        journey_config: Journey configuration, supplying the session window.
        customers: The F002 customers dataset.
        seed: Run seed.

    Yields:
        Frames matching the customer personas schema.

    Raises:
        ValueError: If ``customers`` is empty.
    """
    if customers.is_empty():
        raise ValueError("cannot generate personas: the customers dataset is empty")

    rng = make_rng(seed, "customer_personas")
    profiles = list(PERSONA_PROFILES)

    customer_ids: list[int] = customers["customer_id"].to_list()
    registrations: list[date] = customers["registration_date"].to_list()
    created_timestamps: list[datetime] = customers["created_at"].to_list()

    total = len(customer_ids)
    for start in range(0, total, journey_config.batch_size):
        stop = min(start + journey_config.batch_size, total)

        persona_ids: list[int] = []
        batch_customer_ids: list[int] = []
        names: list[str] = []
        intents: list[float] = []
        price_sensitivities: list[float] = []
        brand_loyalties: list[float] = []
        research_depths: list[float] = []
        frequencies: list[int] = []
        durations: list[float] = []
        wishlist: list[float] = []
        cart: list[float] = []
        purchase: list[float] = []
        descriptions: list[str] = []
        created: list[datetime] = []

        for index in range(start, stop):
            profile = rng.choices(profiles, weights=_PERSONA_WEIGHTS, k=1)[0]
            nominal = rng.randint(profile.min_sessions, profile.max_sessions)
            weight = _tenure_weight(
                registrations[index],
                customer_config.reference_date,
                journey_config.session_years,
            )
            cart_probability = _sample(rng, profile.cart_probability)

            persona_ids.append(customer_ids[index])
            batch_customer_ids.append(customer_ids[index])
            names.append(str(profile.name))
            intents.append(_sample(rng, profile.purchase_intent))
            price_sensitivities.append(_sample(rng, profile.price_sensitivity))
            brand_loyalties.append(_sample(rng, profile.brand_loyalty))
            research_depths.append(_sample(rng, profile.research_depth))
            frequencies.append(max(0, round(nominal * weight)))
            durations.append(round(rng.uniform(profile.min_minutes, profile.max_minutes), 1))
            wishlist.append(_sample(rng, profile.wishlist_probability))
            cart.append(cart_probability)
            # Derived, not sampled: a purchase requires a cart, so the
            # purchase probability can never exceed the cart probability.
            purchase.append(round(cart_probability * rng.uniform(*profile.purchase_ratio), 4))
            descriptions.append(profile.description)
            created.append(created_timestamps[index])

        yield build_frame(
            CUSTOMER_PERSONAS,
            {
                "persona_id": persona_ids,
                "customer_id": batch_customer_ids,
                "persona_name": names,
                "purchase_intent": intents,
                "price_sensitivity": price_sensitivities,
                "brand_loyalty": brand_loyalties,
                "research_depth": research_depths,
                "session_frequency": frequencies,
                "average_session_minutes": durations,
                "wishlist_probability": wishlist,
                "cart_probability": cart,
                "purchase_probability": purchase,
                "description": descriptions,
                "created_at": created,
            },
        )


def generate_personas(
    customer_config: CustomerConfig,
    journey_config: JourneyConfig,
    customers: pl.DataFrame,
    seed: int,
) -> pl.DataFrame:
    """Generate the complete customer personas dataset.

    Args:
        customer_config: Customer configuration, supplying the reference date.
        journey_config: Journey configuration.
        customers: The F002 customers dataset.
        seed: Run seed.

    Returns:
        Exactly one row per customer.

    Raises:
        ValueError: If ``customers`` is empty.
    """
    batches = list(iter_persona_batches(customer_config, journey_config, customers, seed))
    return pl.concat(batches, how="vertical")
