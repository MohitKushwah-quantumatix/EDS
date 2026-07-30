"""Generator for the brands master dataset.

Brand names must be unique, so generated names are de-duplicated with a
numeric suffix rather than resampled - resampling would make the output
sensitive to collision order and therefore harder to reason about.
"""

from __future__ import annotations

from typing import Final

import polars as pl

from eds.config import MasterDataConfig
from eds.core.frames import build_frame, format_code
from eds.core.random_streams import make_faker, make_rng
from eds.domains.retail.domain.catalog.schema import BRANDS

__all__ = ["generate_brands"]

_PREMIUM_PROBABILITY: Final[float] = 0.22


def _unique_name(candidate: str, seen: set[str]) -> str:
    """Return a brand name not already present in ``seen``.

    Args:
        candidate: Proposed name.
        seen: Names already used. Updated in place with the returned name.

    Returns:
        ``candidate``, or ``candidate`` with a numeric suffix if it collides.
    """
    name = candidate
    suffix = 2
    while name in seen:
        name = f"{candidate} {suffix}"
        suffix += 1
    seen.add(name)
    return name


def generate_brands(
    config: MasterDataConfig,
    countries: pl.DataFrame,
    seed: int,
    locale: str = "en_US",
) -> pl.DataFrame:
    """Generate the brands dataset.

    Args:
        config: Master data configuration supplying ``brand_count``.
        countries: The generated countries dataset, used for brand origin.
        seed: Run seed.
        locale: Faker locale for company names.

    Returns:
        ``config.brand_count`` rows keyed by sequential ``brand_id``.

    Raises:
        ValueError: If ``countries`` is empty.
    """
    if countries.is_empty():
        raise ValueError("cannot generate brands: the countries dataset is empty")

    rng = make_rng(seed, "brands")
    faker = make_faker(seed, "brands", locale)
    country_ids: list[int] = countries["country_id"].to_list()

    brand_ids: list[int] = []
    codes: list[str] = []
    names: list[str] = []
    origins: list[int] = []
    premium_flags: list[bool] = []
    seen: set[str] = set()

    for brand_id in range(1, config.brand_count + 1):
        brand_ids.append(brand_id)
        codes.append(format_code("BRD", brand_id, width=5))
        names.append(_unique_name(faker.company(), seen))
        origins.append(rng.choice(country_ids))
        premium_flags.append(rng.random() < _PREMIUM_PROBABILITY)

    return build_frame(
        BRANDS,
        {
            "brand_id": brand_ids,
            "brand_code": codes,
            "brand_name": names,
            "country_id": origins,
            "is_premium": premium_flags,
        },
    )
