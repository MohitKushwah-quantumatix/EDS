"""Price and cost generation for catalog products.

Retail prices are not uniformly distributed: within any category most items
cluster at the low end with a long tail of expensive ones. Sampling uniformly
between a floor and a ceiling would put as many $2,000 televisions as $200
ones in the catalog, which distorts every downstream revenue metric.

This module therefore samples **log-uniformly** inside a per-category band,
which reproduces that right-skew, then derives unit cost from a gross margin
band so that ``unit_cost < list_price`` always holds.
"""

from __future__ import annotations

import math
import random
from typing import Final, NamedTuple

__all__ = ["PriceBand", "PricePoint", "generate_price_point", "price_band_for"]


class PriceBand(NamedTuple):
    """Price and margin envelope for a product category.

    Attributes:
        min_price: Lowest plausible list price.
        max_price: Highest plausible list price.
        min_margin: Lowest gross margin as a fraction of list price.
        max_margin: Highest gross margin as a fraction of list price.
    """

    min_price: float
    max_price: float
    min_margin: float
    max_margin: float


class PricePoint(NamedTuple):
    """A generated cost and price pair.

    Attributes:
        unit_cost: What the retailer pays the supplier.
        list_price: What the customer pays before discounts.
    """

    unit_cost: float
    list_price: float


_DEFAULT_BAND: Final[PriceBand] = PriceBand(4.99, 499.00, 0.25, 0.55)

_BANDS: Final[dict[str, PriceBand]] = {
    "Electronics": PriceBand(9.99, 3_499.00, 0.08, 0.30),
    "Computers": PriceBand(29.99, 4_999.00, 0.06, 0.25),
    "Home & Kitchen": PriceBand(4.99, 1_299.00, 0.30, 0.60),
    "Clothing": PriceBand(6.99, 399.00, 0.45, 0.72),
    "Sports & Outdoors": PriceBand(7.99, 1_899.00, 0.30, 0.58),
    "Health & Beauty": PriceBand(2.99, 249.00, 0.40, 0.70),
    "Toys & Games": PriceBand(4.99, 349.00, 0.35, 0.62),
    "Grocery": PriceBand(0.79, 89.00, 0.15, 0.38),
    "Automotive": PriceBand(5.99, 2_499.00, 0.22, 0.48),
    "Books & Media": PriceBand(3.99, 129.00, 0.30, 0.50),
    "Office Products": PriceBand(1.99, 899.00, 0.28, 0.55),
    "Pet Supplies": PriceBand(2.99, 299.00, 0.32, 0.60),
    "Garden & Outdoor": PriceBand(6.99, 1_599.00, 0.30, 0.58),
    "Furniture": PriceBand(39.99, 2_999.00, 0.35, 0.65),
}


def price_band_for(category_name: str) -> PriceBand:
    """Return the price band for a top-level category.

    Args:
        category_name: Level-1 category name.

    Returns:
        The configured band, or a general-merchandise default when the
        category is not one of the known top-level categories.
    """
    return _BANDS.get(category_name, _DEFAULT_BAND)


def _round_to_charm_price(value: float) -> float:
    """Round a raw price to a realistic retail ending.

    Prices below $100 end in ``.99``; above that they end in ``.00`` at
    five-dollar steps, mirroring common retail practice.

    Args:
        value: Raw price.

    Returns:
        The rounded price, never less than ``0.99``.
    """
    if value < 100.0:
        return max(0.99, round(value) - 0.01)
    return max(0.99, float(round(value / 5.0) * 5))


def generate_price_point(rng: random.Random, band: PriceBand) -> PricePoint:
    """Sample a cost and price pair from a band.

    Args:
        rng: Random source.
        band: The category's price and margin envelope.

    Returns:
        A cost and price pair where ``unit_cost`` is strictly below
        ``list_price``.

    Raises:
        ValueError: If the band is not internally consistent.
    """
    if band.min_price <= 0 or band.max_price < band.min_price:
        raise ValueError(f"invalid price range in band: {band}")
    if not 0.0 <= band.min_margin <= band.max_margin < 1.0:
        raise ValueError(f"invalid margin range in band: {band}")

    raw_price = math.exp(rng.uniform(math.log(band.min_price), math.log(band.max_price)))
    list_price = _round_to_charm_price(raw_price)

    margin = rng.uniform(band.min_margin, band.max_margin)
    unit_cost = round(list_price * (1.0 - margin), 2)

    # Guard the invariant against rounding at the very bottom of the range.
    if unit_cost >= list_price:
        unit_cost = round(list_price * 0.5, 2)
    return PricePoint(unit_cost=max(0.01, unit_cost), list_price=list_price)
