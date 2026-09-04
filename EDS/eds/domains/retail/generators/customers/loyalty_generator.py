"""Generator for the customer loyalty dataset.

Exactly one loyalty record is produced per customer. Tier follows the
documented distribution, while the points balance is derived from **tenure**
multiplied by a tier rate, so longer-standing customers generally hold more
points - as the specification requires.

Loyalty status is derived from account status rather than sampled: a closed
account never carries an active membership.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Final

import polars as pl

from eds.config import CustomerConfig
from eds.core.frames import build_frame, format_code
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.customer.enums import CustomerStatus, LoyaltyStatus, LoyaltyTier
from eds.domains.retail.domain.customer.schema import CUSTOMER_LOYALTY

__all__ = ["generate_loyalty", "iter_loyalty_batches"]

_TIERS: Final[tuple[LoyaltyTier, ...]] = (
    LoyaltyTier.BRONZE,
    LoyaltyTier.SILVER,
    LoyaltyTier.GOLD,
    LoyaltyTier.PLATINUM,
)
_TIER_WEIGHTS: Final[tuple[int, ...]] = (60, 25, 10, 5)

# Points earned per year of membership, by tier. Higher tiers spend more, so
# they accrue faster as well as starting higher.
_POINTS_PER_YEAR: Final[dict[LoyaltyTier, int]] = {
    LoyaltyTier.BRONZE: 250,
    LoyaltyTier.SILVER: 900,
    LoyaltyTier.GOLD: 2_400,
    LoyaltyTier.PLATINUM: 6_000,
}
_POINTS_VARIATION: Final[tuple[float, float]] = (0.6, 1.4)

# Enrolment happens at registration or shortly after.
_MAX_ENROLMENT_LAG_DAYS: Final[int] = 120

_INACTIVE_PROBABILITY: Final[float] = 0.05

_DAYS_PER_YEAR: Final[float] = 365.25


def _loyalty_status(rng: random.Random, customer_status: str) -> LoyaltyStatus:
    """Derive membership status from the customer's account status.

    Args:
        rng: Random source.
        customer_status: The customer's account status.

    Returns:
        The loyalty membership status.
    """
    if customer_status == str(CustomerStatus.CLOSED):
        return LoyaltyStatus.CLOSED
    if customer_status in {str(CustomerStatus.SUSPENDED), str(CustomerStatus.INACTIVE)}:
        return LoyaltyStatus.INACTIVE
    if rng.random() < _INACTIVE_PROBABILITY:
        return LoyaltyStatus.INACTIVE
    return LoyaltyStatus.ACTIVE


def _points_balance(rng: random.Random, tier: LoyaltyTier, tenure_days: int) -> int:
    """Derive a points balance from membership tenure and tier.

    Args:
        rng: Random source.
        tier: The membership tier.
        tenure_days: Days since enrolment.

    Returns:
        A non-negative points balance.
    """
    years = max(0.0, tenure_days / _DAYS_PER_YEAR)
    rate = _POINTS_PER_YEAR[tier]
    return max(0, int(years * rate * rng.uniform(*_POINTS_VARIATION)))


def iter_loyalty_batches(
    config: CustomerConfig, customers: pl.DataFrame, seed: int
) -> Iterator[pl.DataFrame]:
    """Yield loyalty records in batches.

    Args:
        config: Customer configuration.
        customers: The generated customers dataset, supplying registration
            dates and account statuses.
        seed: Run seed.

    Yields:
        Frames matching the customer loyalty schema.

    Raises:
        ValueError: If ``customers`` is empty.
    """
    if customers.is_empty():
        raise ValueError("cannot generate loyalty records: the customers dataset is empty")

    rng = make_rng(seed, "customer_loyalty")
    customer_ids: list[int] = customers["customer_id"].to_list()
    registrations: list[date] = customers["registration_date"].to_list()
    statuses: list[str] = customers["status"].to_list()

    total = len(customer_ids)
    for start in range(0, total, config.batch_size):
        stop = min(start + config.batch_size, total)

        loyalty_ids: list[int] = []
        batch_customer_ids: list[int] = []
        numbers: list[str] = []
        tiers: list[str] = []
        points: list[int] = []
        enrolments: list[date] = []
        batch_statuses: list[str] = []

        for index in range(start, stop):
            customer_id = customer_ids[index]
            tier = rng.choices(_TIERS, weights=_TIER_WEIGHTS, k=1)[0]
            enrolled = registrations[index] + timedelta(
                days=rng.randrange(_MAX_ENROLMENT_LAG_DAYS + 1)
            )
            if enrolled > config.reference_date:
                enrolled = config.reference_date
            tenure_days = (config.reference_date - enrolled).days

            loyalty_ids.append(customer_id)
            batch_customer_ids.append(customer_id)
            numbers.append(format_code("LOY", customer_id, width=8))
            tiers.append(str(tier))
            points.append(_points_balance(rng, tier, tenure_days))
            enrolments.append(enrolled)
            batch_statuses.append(str(_loyalty_status(rng, statuses[index])))

        yield build_frame(
            CUSTOMER_LOYALTY,
            {
                "loyalty_id": loyalty_ids,
                "customer_id": batch_customer_ids,
                "loyalty_number": numbers,
                "tier": tiers,
                "points_balance": points,
                "enrollment_date": enrolments,
                "status": batch_statuses,
                "effective_date": [config.reference_date] * len(loyalty_ids),
                "end_date": [None] * len(loyalty_ids),
            },
        )


def generate_loyalty(config: CustomerConfig, customers: pl.DataFrame, seed: int) -> pl.DataFrame:
    """Generate the complete customer loyalty dataset.

    Args:
        config: Customer configuration.
        customers: The generated customers dataset.
        seed: Run seed.

    Returns:
        Exactly one row per customer.

    Raises:
        ValueError: If ``customers`` is empty.
    """
    batches = list(iter_loyalty_batches(config, customers, seed))
    return pl.concat(batches, how="vertical")
