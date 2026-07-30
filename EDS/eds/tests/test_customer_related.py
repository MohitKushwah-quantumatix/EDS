"""Tests for the address, preference, and loyalty generators."""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import CustomerConfig
from eds.domain.customer.enums import AddressType, CustomerStatus, LoyaltyStatus, LoyaltyTier
from eds.generators.customers.address_generator import generate_addresses, iter_address_batches
from eds.generators.customers.customer_generator import CustomerGeography, generate_customers
from eds.generators.customers.loyalty_generator import generate_loyalty
from eds.generators.customers.preference_generator import generate_preferences
from eds.generators.master_data import MasterData

SEED = 8080


@pytest.fixture
def settings() -> CustomerConfig:
    """Return a small customer configuration."""
    return CustomerConfig(customer_count=200, batch_size=75)


@pytest.fixture
def customers(settings: CustomerConfig, customer_geography: CustomerGeography) -> pl.DataFrame:
    """Return a generated customers frame."""
    return generate_customers(settings, customer_geography, SEED)


def test_every_customer_has_at_least_one_address(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """No customer is left without an address."""
    addresses = generate_addresses(settings, customer_geography, SEED)

    assert addresses["customer_id"].n_unique() == settings.customer_count


def test_address_count_respects_the_configured_bounds(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """Address counts stay within min and max."""
    addresses = generate_addresses(settings, customer_geography, SEED)
    counts = addresses.group_by("customer_id").len()["len"].to_list()

    assert min(counts) >= settings.min_addresses
    assert max(counts) <= settings.max_addresses


def test_exactly_one_primary_address_per_customer(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """The primary address rule holds for every customer."""
    addresses = generate_addresses(settings, customer_geography, SEED)
    primaries = addresses.group_by("customer_id").agg(pl.col("is_primary").sum().alias("n"))

    assert primaries.filter(pl.col("n") != 1).height == 0


def test_primary_address_is_the_home_address(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """The primary address is always typed as home."""
    addresses = generate_addresses(settings, customer_geography, SEED)
    primary = addresses.filter(pl.col("is_primary"))

    assert set(primary["address_type"].to_list()) == {str(AddressType.HOME)}


def test_address_types_are_declared_values(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """Every address type comes from the enum."""
    addresses = generate_addresses(settings, customer_geography, SEED)

    assert set(addresses["address_type"].to_list()) <= {str(m) for m in AddressType}


def test_address_ids_are_unique_and_sequential(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """Address ids form a dense sequence starting at one."""
    addresses = generate_addresses(settings, customer_geography, SEED)

    assert addresses["address_id"].to_list() == list(range(1, addresses.height + 1))


def test_addresses_reference_real_geography(
    settings: CustomerConfig,
    customer_geography: CustomerGeography,
    master_data: MasterData,
) -> None:
    """City, state, and country keys all resolve against F001 output."""
    addresses = generate_addresses(settings, customer_geography, SEED)

    assert set(addresses["city_id"].to_list()) <= set(master_data["cities"]["city_id"].to_list())
    assert set(addresses["state_id"].to_list()) <= set(master_data["states"]["state_id"].to_list())
    assert set(addresses["country_id"].to_list()) <= set(
        master_data["countries"]["country_id"].to_list()
    )


def test_address_geography_is_internally_consistent(
    settings: CustomerConfig,
    customer_geography: CustomerGeography,
    master_data: MasterData,
) -> None:
    """An address's state and country match those of its city."""
    addresses = generate_addresses(settings, customer_geography, SEED)
    joined = addresses.join(master_data["cities"], on="city_id", how="inner", suffix="_city")

    assert joined.height == addresses.height
    assert joined.filter(pl.col("state_id") != pl.col("state_id_city")).height == 0
    assert joined.filter(pl.col("country_id") != pl.col("country_id_city")).height == 0


def test_address_batches_never_split_a_customer(
    customer_geography: CustomerGeography,
) -> None:
    """A customer's addresses always land in one batch."""
    config = CustomerConfig(customer_count=40, batch_size=10)

    for batch in iter_address_batches(config, customer_geography, SEED):
        primaries = batch.group_by("customer_id").agg(pl.col("is_primary").sum().alias("n"))
        assert primaries.filter(pl.col("n") != 1).height == 0


def test_addresses_are_deterministic(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """The same seed reproduces the same addresses."""
    assert generate_addresses(settings, customer_geography, SEED).equals(
        generate_addresses(settings, customer_geography, SEED)
    )


def test_single_address_configuration_is_honoured(
    customer_geography: CustomerGeography,
) -> None:
    """With max_addresses of one, every customer has exactly one."""
    config = CustomerConfig(customer_count=50, min_addresses=1, max_addresses=1)
    addresses = generate_addresses(config, customer_geography, SEED)

    assert addresses.height == config.customer_count
    assert addresses["is_primary"].all()


def test_one_preference_record_per_customer(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """Preferences cover every customer exactly once."""
    preferences = generate_preferences(settings, customer_geography, SEED)

    assert preferences.height == settings.customer_count
    assert preferences["customer_id"].n_unique() == settings.customer_count


def test_preference_timezone_comes_from_the_home_city(
    settings: CustomerConfig,
    customer_geography: CustomerGeography,
    master_data: MasterData,
) -> None:
    """Timezones are real values drawn from the cities dataset."""
    preferences = generate_preferences(settings, customer_geography, SEED)

    assert set(preferences["timezone"].to_list()) <= set(
        master_data["cities"]["timezone"].to_list()
    )


def test_preferences_agree_with_the_customer_record(
    settings: CustomerConfig, customer_geography: CustomerGeography, customers: pl.DataFrame
) -> None:
    """Language and currency match the customer's own values."""
    preferences = generate_preferences(settings, customer_geography, SEED)
    joined = customers.join(preferences, on="customer_id", how="inner", suffix="_pref")

    assert (
        joined.filter(pl.col("preferred_language") != pl.col("preferred_language_pref")).height == 0
    )
    assert (
        joined.filter(pl.col("preferred_currency") != pl.col("preferred_currency_pref")).height == 0
    )


def test_preferences_are_deterministic(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """The same seed reproduces the same preferences."""
    assert generate_preferences(settings, customer_geography, SEED).equals(
        generate_preferences(settings, customer_geography, SEED)
    )


def test_one_loyalty_record_per_customer(settings: CustomerConfig, customers: pl.DataFrame) -> None:
    """Loyalty covers every customer exactly once."""
    loyalty = generate_loyalty(settings, customers, SEED)

    assert loyalty.height == customers.height
    assert loyalty["customer_id"].n_unique() == customers.height
    assert loyalty["loyalty_number"].n_unique() == customers.height


def test_loyalty_tiers_are_declared_values(
    settings: CustomerConfig, customers: pl.DataFrame
) -> None:
    """Tiers come from the enum."""
    loyalty = generate_loyalty(settings, customers, SEED)

    assert set(loyalty["tier"].to_list()) <= {str(member) for member in LoyaltyTier}


def test_loyalty_tier_distribution_is_approximately_as_specified(
    customer_geography: CustomerGeography,
) -> None:
    """Tiers follow the documented 60/25/10/5 split."""
    config = CustomerConfig(customer_count=6_000, batch_size=2_000)
    many = generate_customers(config, customer_geography, SEED)
    loyalty = generate_loyalty(config, many, SEED)
    share = {
        row["tier"]: row["count"] / config.customer_count
        for row in loyalty["tier"].value_counts().to_dicts()
    }

    assert share[str(LoyaltyTier.BRONZE)] == pytest.approx(0.60, abs=0.03)
    assert share[str(LoyaltyTier.SILVER)] == pytest.approx(0.25, abs=0.03)
    assert share[str(LoyaltyTier.GOLD)] == pytest.approx(0.10, abs=0.02)
    assert share[str(LoyaltyTier.PLATINUM)] == pytest.approx(0.05, abs=0.02)


def test_points_are_non_negative(settings: CustomerConfig, customers: pl.DataFrame) -> None:
    """A points balance is never negative."""
    loyalty = generate_loyalty(settings, customers, SEED)

    assert loyalty.filter(pl.col("points_balance") < 0).height == 0


def test_longer_standing_customers_hold_more_points(
    customer_geography: CustomerGeography,
) -> None:
    """Points rise with tenure, as the specification requires."""
    config = CustomerConfig(customer_count=4_000, batch_size=2_000)
    many = generate_customers(config, customer_geography, SEED)
    loyalty = generate_loyalty(config, many, SEED)

    # Compare within one tier so the tier's earning rate cannot explain the gap.
    joined = (
        loyalty.join(many.select("customer_id", "registration_date"), on="customer_id")
        .filter(pl.col("tier") == str(LoyaltyTier.BRONZE))
        .sort("registration_date")
    )
    half = joined.height // 2

    longest_standing: list[int] = joined.head(half)["points_balance"].to_list()
    newest: list[int] = joined.tail(half)["points_balance"].to_list()

    assert sum(longest_standing) / half > sum(newest) / half


def test_enrollment_never_precedes_registration(
    settings: CustomerConfig, customers: pl.DataFrame
) -> None:
    """A customer cannot enrol before they registered."""
    loyalty = generate_loyalty(settings, customers, SEED)
    joined = loyalty.join(customers.select("customer_id", "registration_date"), on="customer_id")

    assert joined.filter(pl.col("enrollment_date") < pl.col("registration_date")).height == 0


def test_closed_customers_have_closed_memberships(
    customer_geography: CustomerGeography,
) -> None:
    """Loyalty status never contradicts account status."""
    config = CustomerConfig(customer_count=3_000, batch_size=1_000)
    many = generate_customers(config, customer_geography, SEED)
    loyalty = generate_loyalty(config, many, SEED)
    joined = many.join(loyalty, on="customer_id", how="inner", suffix="_loyalty")

    closed = joined.filter(pl.col("status") == str(CustomerStatus.CLOSED))

    assert set(closed["status_loyalty"].to_list()) <= {str(LoyaltyStatus.CLOSED)}


def test_loyalty_requires_customers(settings: CustomerConfig, customers: pl.DataFrame) -> None:
    """Loyalty cannot be generated without customers."""
    with pytest.raises(ValueError, match="customers dataset is empty"):
        generate_loyalty(settings, customers.clear(), SEED)
