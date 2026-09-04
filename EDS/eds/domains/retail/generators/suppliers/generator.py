"""Generator for the suppliers master dataset.

Every supplier is anchored to a real city, and therefore to that city's state
and country, so supplier geography is referentially correct by construction.
Lead time and reliability are correlated with the commercial tier: strategic
suppliers ship faster and more reliably than transactional ones.
"""

from __future__ import annotations

import random
from typing import Final

import polars as pl

from eds.config import MasterDataConfig
from eds.core.frames import build_frame, format_code
from eds.core.random_streams import make_faker, make_rng
from eds.domains.retail.domain.enums import SupplierTier
from eds.domains.retail.domain.supply_chain.schema import SUPPLIERS

__all__ = ["generate_suppliers"]

_TIERS: Final[tuple[SupplierTier, ...]] = (
    SupplierTier.STRATEGIC,
    SupplierTier.PREFERRED,
    SupplierTier.STANDARD,
    SupplierTier.TRANSACTIONAL,
)

# Relative frequency of each tier: most suppliers are standard or below.
_TIER_WEIGHTS: Final[tuple[int, ...]] = (1, 3, 8, 4)

# Lead time (days) and reliability bounds per tier, best tier first.
_TIER_LEAD_TIME: Final[dict[SupplierTier, tuple[int, int]]] = {
    SupplierTier.STRATEGIC: (2, 7),
    SupplierTier.PREFERRED: (5, 14),
    SupplierTier.STANDARD: (10, 25),
    SupplierTier.TRANSACTIONAL: (18, 45),
}
_TIER_RELIABILITY: Final[dict[SupplierTier, tuple[float, float]]] = {
    SupplierTier.STRATEGIC: (0.94, 0.999),
    SupplierTier.PREFERRED: (0.88, 0.97),
    SupplierTier.STANDARD: (0.78, 0.93),
    SupplierTier.TRANSACTIONAL: (0.60, 0.85),
}

_INACTIVE_PROBABILITY: Final[float] = 0.06


def _pick_city(
    rng: random.Random, city_ids: list[int], city_country_ids: list[int]
) -> tuple[int, int]:
    """Pick a city uniformly at random.

    Args:
        rng: Random source.
        city_ids: All city identifiers.
        city_country_ids: Country identifier for each city, same order.

    Returns:
        The chosen ``(city_id, country_id)`` pair.
    """
    index = rng.randrange(len(city_ids))
    return city_ids[index], city_country_ids[index]


def generate_suppliers(
    config: MasterDataConfig,
    cities: pl.DataFrame,
    seed: int,
    reference_date: date,
    locale: str = "en_US",
) -> pl.DataFrame:
    """Generate the suppliers dataset.

    Args:
        config: Master data configuration supplying ``supplier_count``.
        cities: The generated cities dataset, used to anchor supplier location.
        seed: Run seed.
        locale: Faker locale for company names and contact details.

    Returns:
        ``config.supplier_count`` rows keyed by sequential ``supplier_id``.

    Raises:
        ValueError: If ``cities`` is empty, leaving nowhere to place suppliers.
    """
    if cities.is_empty():
        raise ValueError("cannot generate suppliers: the cities dataset is empty")

    rng = make_rng(seed, "suppliers")
    faker = make_faker(seed, "suppliers", locale)

    city_ids: list[int] = cities["city_id"].to_list()
    city_country_ids: list[int] = cities["country_id"].to_list()

    supplier_ids: list[int] = []
    codes: list[str] = []
    names: list[str] = []
    country_ids: list[int] = []
    chosen_city_ids: list[int] = []
    tiers: list[str] = []
    emails: list[str] = []
    phones: list[str] = []
    lead_times: list[int] = []
    reliability: list[float] = []
    active_flags: list[bool] = []
    effective_dates: list[date] = []
    end_dates: list[date | None] = []

    for supplier_id in range(1, config.supplier_count + 1):
        tier = rng.choices(_TIERS, weights=_TIER_WEIGHTS, k=1)[0]
        city_id, country_id = _pick_city(rng, city_ids, city_country_ids)
        lead_low, lead_high = _TIER_LEAD_TIME[tier]
        reliability_low, reliability_high = _TIER_RELIABILITY[tier]
        company = faker.company()

        supplier_ids.append(supplier_id)
        codes.append(format_code("SUP", supplier_id))
        names.append(company)
        country_ids.append(country_id)
        chosen_city_ids.append(city_id)
        tiers.append(str(tier))
        emails.append(f"orders@{faker.domain_name()}")
        phones.append(faker.numerify("+1-###-###-####"))
        lead_times.append(rng.randint(lead_low, lead_high))
        reliability.append(round(rng.uniform(reliability_low, reliability_high), 4))
        active_flags.append(rng.random() >= _INACTIVE_PROBABILITY)
        effective_dates.append(reference_date)
        end_dates.append(None)

    return build_frame(
        SUPPLIERS,
        {
            "supplier_id": supplier_ids,
            "supplier_code": codes,
            "supplier_name": names,
            "country_id": country_ids,
            "city_id": chosen_city_ids,
            "tier": tiers,
            "contact_email": emails,
            "contact_phone": phones,
            "lead_time_days": lead_times,
            "reliability_score": reliability,
            "is_active": active_flags,
            "effective_date": effective_dates,
            "end_date": end_dates,
        },
    )
