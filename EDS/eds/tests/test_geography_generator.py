"""Tests for the geography generators."""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import MasterDataConfig
from eds.generators.geography.generator import (
    generate_cities,
    generate_countries,
    generate_states,
)
from eds.generators.geography.reference import country_by_code, supported_countries

SEED = 1234


def config(**overrides: object) -> MasterDataConfig:
    """Build a master data configuration with overrides applied.

    Args:
        **overrides: Fields to override.

    Returns:
        The configuration.
    """
    return MasterDataConfig(**overrides)  # type: ignore[arg-type]


def test_countries_match_the_configured_list() -> None:
    """One row is emitted per configured country, in order."""
    frame = generate_countries(config(countries=("US", "CA")))

    assert frame["country_code"].to_list() == ["US", "CA"]
    assert frame["country_id"].to_list() == [1, 2]


def test_country_codes_are_real_iso_codes() -> None:
    """Alpha-2 and alpha-3 codes come from the curated reference data."""
    frame = generate_countries(config(countries=("GB",)))

    assert frame["country_code_3"].to_list() == ["GBR"]
    assert frame["currency_code"].to_list() == ["GBP"]


def test_unknown_country_is_rejected() -> None:
    """A country without reference data fails with the supported list."""
    with pytest.raises(KeyError, match="Supported countries"):
        generate_countries(config(countries=("ZZ",)))


def test_states_belong_to_their_country() -> None:
    """Every state points at a country that was generated."""
    settings = config(countries=("US", "CA"))
    countries = generate_countries(settings)
    states = generate_states(settings)

    assert set(states["country_id"].to_list()) <= set(countries["country_id"].to_list())


def test_state_count_matches_the_reference_data() -> None:
    """The number of states equals the curated subdivision count."""
    states = generate_states(config(countries=("US",)))

    assert states.height == len(country_by_code("US").states)


def test_state_codes_are_unique_within_a_country() -> None:
    """Subdivision codes do not repeat inside one country."""
    states = generate_states(config(countries=("US",)))

    assert states["state_code"].n_unique() == states.height


def test_cities_per_state_is_honoured() -> None:
    """City count is states multiplied by the configured density."""
    settings = config(countries=("GB",), cities_per_state=4)
    states = generate_states(settings)
    cities = generate_cities(settings, SEED)

    assert cities.height == states.height * 4


def test_cities_reference_valid_states_and_countries() -> None:
    """City foreign keys resolve against the generated parents."""
    settings = config(countries=("US", "GB"), cities_per_state=2)
    countries = generate_countries(settings)
    states = generate_states(settings)
    cities = generate_cities(settings, SEED)

    assert set(cities["state_id"].to_list()) <= set(states["state_id"].to_list())
    assert set(cities["country_id"].to_list()) <= set(countries["country_id"].to_list())


def test_city_country_matches_its_state_country() -> None:
    """The denormalised country on a city agrees with its state."""
    settings = config(countries=("US", "CA"), cities_per_state=2)
    states = generate_states(settings)
    cities = generate_cities(settings, SEED)

    joined = cities.join(states, on="state_id", how="inner", suffix="_state")

    assert joined.height == cities.height
    assert joined.filter(pl.col("country_id") != pl.col("country_id_state")).height == 0


def test_city_coordinates_fall_inside_the_country_box() -> None:
    """Generated coordinates respect the country's bounding box."""
    reference = country_by_code("AU")
    cities = generate_cities(config(countries=("AU",), cities_per_state=3), SEED)

    latitudes = cities["latitude"].to_list()
    longitudes = cities["longitude"].to_list()

    assert all(
        reference.latitude_range[0] <= lat <= reference.latitude_range[1] for lat in latitudes
    )
    assert all(
        reference.longitude_range[0] <= lon <= reference.longitude_range[1] for lon in longitudes
    )


def test_postal_codes_follow_the_country_format() -> None:
    """US postal codes are five digits, Canadian ones are alphanumeric."""
    us_cities = generate_cities(config(countries=("US",), cities_per_state=1), SEED)
    ca_cities = generate_cities(config(countries=("CA",), cities_per_state=1), SEED)

    assert all(len(code) == 5 and code.isdigit() for code in us_cities["postal_code"].to_list())
    assert all(len(code) == 7 and code[3] == " " for code in ca_cities["postal_code"].to_list())


def test_city_generation_is_deterministic() -> None:
    """The same seed reproduces the same cities."""
    settings = config(countries=("US",), cities_per_state=2)

    assert generate_cities(settings, SEED).equals(generate_cities(settings, SEED))


def test_city_generation_varies_with_the_seed() -> None:
    """A different seed produces different synthesised attributes."""
    settings = config(countries=("US",), cities_per_state=2)

    assert not generate_cities(settings, 1).equals(generate_cities(settings, 2))


def test_timezones_come_from_the_country() -> None:
    """Assigned timezones are drawn from the country's timezone list."""
    reference = country_by_code("US")
    cities = generate_cities(config(countries=("US",), cities_per_state=2), SEED)

    assert set(cities["timezone"].to_list()) <= set(reference.timezones)


def test_every_supported_country_generates() -> None:
    """All curated countries produce non-empty geography."""
    for code in supported_countries():
        settings = config(countries=(code,), cities_per_state=1)

        assert generate_states(settings).height > 0
        assert generate_cities(settings, SEED).height > 0
