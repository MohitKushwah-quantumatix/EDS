"""Generators for the countries, states, and cities master datasets.

Countries and states come from curated real reference data; only cities are
synthesised. Identifiers are assigned sequentially in reference order, so the
same configuration always produces the same keys regardless of seed - the seed
only affects synthesised attributes.
"""

from __future__ import annotations

import random
from typing import Final

import polars as pl

from eds.config import MasterDataConfig
from eds.core.frames import build_frame
from eds.core.random_streams import make_faker, make_rng
from eds.domains.retail.domain.geography.schema import CITIES, COUNTRIES, STATES
from eds.domains.retail.generators.geography.reference import CountryReference, country_by_code

__all__ = ["generate_cities", "generate_countries", "generate_states"]

_DIGITS: Final[str] = "0123456789"
_LETTERS: Final[str] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_COORDINATE_PRECISION: Final[int] = 6


def _selected_countries(config: MasterDataConfig) -> tuple[CountryReference, ...]:
    """Resolve configured country codes to reference entries.

    Args:
        config: Master data configuration.

    Returns:
        Reference entries in configuration order.

    Raises:
        KeyError: If a configured country has no reference data.
    """
    return tuple(country_by_code(code) for code in config.countries)


def generate_countries(config: MasterDataConfig) -> pl.DataFrame:
    """Generate the countries dataset.

    Args:
        config: Master data configuration selecting the countries to include.

    Returns:
        One row per configured country, keyed by sequential ``country_id``.

    Raises:
        KeyError: If a configured country has no reference data.
    """
    countries = _selected_countries(config)
    return build_frame(
        COUNTRIES,
        {
            "country_id": [index for index, _ in enumerate(countries, start=1)],
            "country_code": [country.code for country in countries],
            "country_code_3": [country.code_3 for country in countries],
            "country_name": [country.name for country in countries],
            "currency_code": [country.currency_code for country in countries],
            "phone_code": [country.phone_code for country in countries],
            "region": [country.region for country in countries],
        },
    )


def generate_states(config: MasterDataConfig) -> pl.DataFrame:
    """Generate the states dataset for the configured countries.

    Args:
        config: Master data configuration.

    Returns:
        One row per subdivision, keyed by sequential ``state_id``.

    Raises:
        KeyError: If a configured country has no reference data.
    """
    state_ids: list[int] = []
    country_ids: list[int] = []
    codes: list[str] = []
    names: list[str] = []

    next_state_id = 1
    for country_id, country in enumerate(_selected_countries(config), start=1):
        for state in country.states:
            state_ids.append(next_state_id)
            country_ids.append(country_id)
            codes.append(state.code)
            names.append(state.name)
            next_state_id += 1

    return build_frame(
        STATES,
        {
            "state_id": state_ids,
            "country_id": country_ids,
            "state_code": codes,
            "state_name": names,
        },
    )


def _postal_code(template: str, rng: random.Random) -> str:
    """Render a postal code from a template.

    Args:
        template: Template where ``#`` is a digit and ``@`` an upper-case letter.
        rng: Random source.

    Returns:
        The rendered postal code.
    """
    return "".join(
        rng.choice(_DIGITS)
        if character == "#"
        else rng.choice(_LETTERS)
        if character == "@"
        else character
        for character in template
    )


def generate_cities(config: MasterDataConfig, seed: int, locale: str = "en_US") -> pl.DataFrame:
    """Generate the cities dataset.

    Each state receives ``cities_per_state`` cities with a postal code in the
    country's format and coordinates inside the country's bounding box.

    Args:
        config: Master data configuration.
        seed: Run seed.
        locale: Faker locale used for city names.

    Returns:
        One row per city, keyed by sequential ``city_id``.

    Raises:
        KeyError: If a configured country has no reference data.
    """
    rng = make_rng(seed, "cities")
    faker = make_faker(seed, "cities", locale)

    city_ids: list[int] = []
    state_ids: list[int] = []
    country_ids: list[int] = []
    names: list[str] = []
    postal_codes: list[str] = []
    latitudes: list[float] = []
    longitudes: list[float] = []
    timezones: list[str] = []

    next_city_id = 1
    next_state_id = 1
    for country_id, country in enumerate(_selected_countries(config), start=1):
        lat_min, lat_max = country.latitude_range
        lon_min, lon_max = country.longitude_range
        for _ in country.states:
            for _ in range(config.cities_per_state):
                city_ids.append(next_city_id)
                state_ids.append(next_state_id)
                country_ids.append(country_id)
                names.append(faker.city())
                postal_codes.append(_postal_code(country.postal_format, rng))
                latitudes.append(round(rng.uniform(lat_min, lat_max), _COORDINATE_PRECISION))
                longitudes.append(round(rng.uniform(lon_min, lon_max), _COORDINATE_PRECISION))
                timezones.append(rng.choice(country.timezones))
                next_city_id += 1
            next_state_id += 1

    return build_frame(
        CITIES,
        {
            "city_id": city_ids,
            "state_id": state_ids,
            "country_id": country_ids,
            "city_name": names,
            "postal_code": postal_codes,
            "latitude": latitudes,
            "longitude": longitudes,
            "timezone": timezones,
        },
    )
