"""Generator for the customer addresses dataset.

Every customer receives between ``min_addresses`` and ``max_addresses``
addresses, and exactly one of them is marked primary. All addresses for a
customer sit in that customer's home city, so the city, state, and country
keys agree with the language and currency on the customer record.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import datetime, time, timedelta
from typing import Final

import polars as pl

from eds.config import CustomerConfig
from eds.core.frames import build_frame
from eds.core.random_streams import make_faker, make_rng
from eds.domains.retail.domain.customer.enums import AddressType
from eds.domains.retail.domain.customer.schema import CUSTOMER_ADDRESSES
from eds.domains.retail.generators.customers.customer_generator import (
    CustomerGeography,
    assign_home_cities,
    customer_id_batches,
)

__all__ = ["generate_addresses", "iter_address_batches"]

# The first address a customer adds is where they live; later ones are the
# other purposes a retailer records.
_PRIMARY_TYPE: Final[AddressType] = AddressType.HOME
_SECONDARY_TYPES: Final[tuple[AddressType, ...]] = (
    AddressType.WORK,
    AddressType.SHIPPING,
    AddressType.BILLING,
    AddressType.OTHER,
)
_SECONDARY_WEIGHTS: Final[tuple[int, ...]] = (35, 35, 25, 5)

# Addresses sit within roughly a city's radius of the city centroid.
_COORDINATE_JITTER: Final[float] = 0.08
_COORDINATE_PRECISION: Final[int] = 6

_LINE2_PROBABILITY: Final[float] = 0.35


def _jitter(rng: random.Random, value: float) -> float:
    """Offset a coordinate slightly so addresses do not stack on one point.

    Args:
        rng: Random source.
        value: The city centroid coordinate.

    Returns:
        The offset coordinate.
    """
    return round(
        value + rng.uniform(-_COORDINATE_JITTER, _COORDINATE_JITTER), _COORDINATE_PRECISION
    )


def iter_address_batches(
    config: CustomerConfig,
    geography: CustomerGeography,
    seed: int,
    locale: str = "en_US",
) -> Iterator[pl.DataFrame]:
    """Yield customer addresses in batches.

    Batches are aligned to customer id ranges, so a customer's addresses are
    never split across two frames.

    Args:
        config: Customer configuration.
        geography: The extracted geography lookup.
        seed: Run seed.
        locale: Faker locale for street addresses.

    Yields:
        Frames matching the customer addresses schema.
    """
    rng = make_rng(seed, "customer_addresses")
    faker = make_faker(seed, "customer_addresses", locale)
    home_cities = assign_home_cities(config, geography, seed)

    next_address_id = 1
    for id_range in customer_id_batches(config):
        address_ids: list[int] = []
        customer_ids: list[int] = []
        types: list[str] = []
        line1: list[str] = []
        line2: list[str | None] = []
        city_ids: list[int] = []
        state_ids: list[int] = []
        country_ids: list[int] = []
        postal_codes: list[str] = []
        primary_flags: list[bool] = []
        latitudes: list[float] = []
        longitudes: list[float] = []
        created: list[datetime] = []

        for customer_id in id_range:
            city_index = home_cities[customer_id - 1]
            count = rng.randint(config.min_addresses, config.max_addresses)
            primary_position = rng.randrange(count)

            for position in range(count):
                is_primary = position == primary_position
                address_type = (
                    _PRIMARY_TYPE
                    if is_primary
                    else rng.choices(_SECONDARY_TYPES, weights=_SECONDARY_WEIGHTS, k=1)[0]
                )

                address_ids.append(next_address_id)
                customer_ids.append(customer_id)
                types.append(str(address_type))
                line1.append(faker.street_address())
                line2.append(
                    faker.secondary_address() if rng.random() < _LINE2_PROBABILITY else None
                )
                city_ids.append(geography.city_ids[city_index])
                state_ids.append(geography.state_ids[city_index])
                country_ids.append(geography.country_ids[city_index])
                postal_codes.append(geography.postal_codes[city_index])
                primary_flags.append(is_primary)
                latitudes.append(_jitter(rng, geography.latitudes[city_index]))
                longitudes.append(_jitter(rng, geography.longitudes[city_index]))
                created.append(
                    datetime.combine(
                        config.earliest_registration_date
                        + timedelta(days=rng.randrange((config.reference_date - config.earliest_registration_date).days + 1)),
                        time(rng.randrange(24), rng.randrange(60)),
                    )
                )
                next_address_id += 1

        yield build_frame(
            CUSTOMER_ADDRESSES,
            {
                "address_id": address_ids,
                "customer_id": customer_ids,
                "address_type": types,
                "line1": line1,
                "line2": line2,
                "city_id": city_ids,
                "state_id": state_ids,
                "country_id": country_ids,
                "postal_code": postal_codes,
                "is_primary": primary_flags,
                "latitude": latitudes,
                "longitude": longitudes,
                "created_at": created,
            },
        )


def generate_addresses(
    config: CustomerConfig,
    geography: CustomerGeography,
    seed: int,
    locale: str = "en_US",
) -> pl.DataFrame:
    """Generate the complete customer addresses dataset.

    Args:
        config: Customer configuration.
        geography: The extracted geography lookup.
        seed: Run seed.
        locale: Faker locale for street addresses.

    Returns:
        Between one and ``max_addresses`` rows per customer, with exactly one
        primary address each.
    """
    batches = list(iter_address_batches(config, geography, seed, locale))
    return pl.concat(batches, how="vertical")
