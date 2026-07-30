"""Tests for the customer persona generator."""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import CustomerConfig, JourneyConfig
from eds.domain.journey.enums import PersonaName
from eds.generators.customer_data import CustomerData
from eds.generators.journey.persona_generator import (
    PERSONA_PROFILES,
    generate_personas,
    iter_persona_batches,
    persona_profile,
)

SEED = 606


@pytest.fixture
def customers(customer_data: CustomerData) -> pl.DataFrame:
    """Return the generated customers frame."""
    return customer_data["customers"]


@pytest.fixture
def journey_config() -> JourneyConfig:
    """Return a journey configuration with a small batch size."""
    return JourneyConfig(batch_size=40)


@pytest.fixture
def customer_config(small_customer_config: CustomerConfig) -> CustomerConfig:
    """Return the customer configuration used to build the fixtures."""
    return small_customer_config


def test_six_personas_are_supported() -> None:
    """The catalogue matches the six documented personas."""
    assert len(PERSONA_PROFILES) == 6
    assert {profile.name for profile in PERSONA_PROFILES} == set(PersonaName)


def test_every_profile_has_a_description() -> None:
    """Each persona carries a human-readable description."""
    assert all(profile.description.strip() for profile in PERSONA_PROFILES)


def test_profile_bounds_are_ordered() -> None:
    """Session and duration ranges are not inverted."""
    for profile in PERSONA_PROFILES:
        assert profile.min_sessions <= profile.max_sessions
        assert profile.min_minutes <= profile.max_minutes


def test_profile_lookup_by_name() -> None:
    """A persona name resolves to its profile."""
    assert persona_profile(str(PersonaName.RESEARCHER)).max_pages == 25


def test_unknown_profile_lookup_raises() -> None:
    """An unsupported persona fails with the supported list."""
    with pytest.raises(KeyError, match="Supported personas"):
        persona_profile("TIME_TRAVELLER")


def test_one_persona_per_customer(
    customer_config: CustomerConfig, journey_config: JourneyConfig, customers: pl.DataFrame
) -> None:
    """Every customer receives exactly one persona."""
    personas = generate_personas(customer_config, journey_config, customers, SEED)

    assert personas.height == customers.height
    assert personas["customer_id"].n_unique() == customers.height
    assert set(personas["customer_id"].to_list()) == set(customers["customer_id"].to_list())


def test_persona_ids_are_unique(
    customer_config: CustomerConfig, journey_config: JourneyConfig, customers: pl.DataFrame
) -> None:
    """Persona ids form a primary key."""
    personas = generate_personas(customer_config, journey_config, customers, SEED)

    assert personas["persona_id"].n_unique() == personas.height


def test_persona_names_are_declared_values(
    customer_config: CustomerConfig, journey_config: JourneyConfig, customers: pl.DataFrame
) -> None:
    """Only the six supported personas appear."""
    personas = generate_personas(customer_config, journey_config, customers, SEED)

    assert set(personas["persona_name"].to_list()) <= {str(member) for member in PersonaName}


def test_persona_distribution_is_approximately_as_specified(
    customer_config: CustomerConfig, customers: pl.DataFrame
) -> None:
    """Personas follow the documented 25/20/20/20/10/5 split."""
    many = pl.concat(
        [customers.with_columns(pl.col("customer_id") + offset * 10_000) for offset in range(50)]
    )
    personas = generate_personas(customer_config, JourneyConfig(), many, SEED)
    share = {
        row["persona_name"]: row["count"] / personas.height
        for row in personas["persona_name"].value_counts().to_dicts()
    }

    assert share[str(PersonaName.WINDOW_SHOPPER)] == pytest.approx(0.25, abs=0.03)
    assert share[str(PersonaName.RESEARCHER)] == pytest.approx(0.20, abs=0.03)
    assert share[str(PersonaName.BARGAIN_HUNTER)] == pytest.approx(0.20, abs=0.03)
    assert share[str(PersonaName.LOYAL_CUSTOMER)] == pytest.approx(0.20, abs=0.03)
    assert share[str(PersonaName.IMPULSE_BUYER)] == pytest.approx(0.10, abs=0.02)
    assert share[str(PersonaName.SEASONAL_SHOPPER)] == pytest.approx(0.05, abs=0.02)


def test_trait_scores_are_probabilities(
    customer_config: CustomerConfig, journey_config: JourneyConfig, customers: pl.DataFrame
) -> None:
    """Every trait score sits between zero and one."""
    personas = generate_personas(customer_config, journey_config, customers, SEED)

    for column in (
        "purchase_intent",
        "price_sensitivity",
        "brand_loyalty",
        "research_depth",
        "wishlist_probability",
        "cart_probability",
        "purchase_probability",
    ):
        assert personas.filter((pl.col(column) < 0) | (pl.col(column) > 1)).height == 0, column


def test_purchase_probability_never_exceeds_cart_probability(
    customer_config: CustomerConfig, journey_config: JourneyConfig, customers: pl.DataFrame
) -> None:
    """A purchase requires a cart, so the derived probability is bounded."""
    personas = generate_personas(customer_config, journey_config, customers, SEED)

    assert personas.filter(pl.col("purchase_probability") > pl.col("cart_probability")).height == 0


def test_average_duration_falls_inside_the_persona_profile(
    customer_config: CustomerConfig, journey_config: JourneyConfig, customers: pl.DataFrame
) -> None:
    """Each customer's average session length respects their persona's band."""
    personas = generate_personas(customer_config, journey_config, customers, SEED)

    for profile in PERSONA_PROFILES:
        subset = personas.filter(pl.col("persona_name") == str(profile.name))
        if subset.is_empty():
            continue
        minutes = subset["average_session_minutes"].to_list()
        assert min(minutes) >= profile.min_minutes
        assert max(minutes) <= profile.max_minutes


def test_session_frequency_never_exceeds_the_persona_maximum(
    customer_config: CustomerConfig, journey_config: JourneyConfig, customers: pl.DataFrame
) -> None:
    """Tenure scaling only ever reduces the nominal session count."""
    personas = generate_personas(customer_config, journey_config, customers, SEED)

    for profile in PERSONA_PROFILES:
        subset = personas.filter(pl.col("persona_name") == str(profile.name))
        if subset.is_empty():
            continue
        assert max(subset["session_frequency"].to_list()) <= profile.max_sessions


def test_session_frequency_is_never_negative(
    customer_config: CustomerConfig, journey_config: JourneyConfig, customers: pl.DataFrame
) -> None:
    """A customer cannot have a negative number of sessions."""
    personas = generate_personas(customer_config, journey_config, customers, SEED)

    assert personas.filter(pl.col("session_frequency") < 0).height == 0


def test_longer_tenure_implies_more_sessions(
    customer_config: CustomerConfig, journey_config: JourneyConfig, customers: pl.DataFrame
) -> None:
    """Session counts scale with how long the customer has been registered."""
    personas = generate_personas(customer_config, journey_config, customers, SEED)
    joined = (
        personas.join(customers.select("customer_id", "registration_date"), on="customer_id")
        .filter(pl.col("persona_name") == str(PersonaName.WINDOW_SHOPPER))
        .sort("registration_date")
    )
    half = joined.height // 2

    oldest: list[int] = joined.head(half)["session_frequency"].to_list()
    newest: list[int] = joined.tail(half)["session_frequency"].to_list()

    assert sum(oldest) / half > sum(newest) / half


def test_batching_does_not_change_the_output(
    customer_config: CustomerConfig, customers: pl.DataFrame
) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = generate_personas(customer_config, JourneyConfig(batch_size=7), customers, SEED)
    large = generate_personas(customer_config, JourneyConfig(batch_size=10_000), customers, SEED)

    assert small.equals(large)


def test_batch_sizes_follow_configuration(
    customer_config: CustomerConfig, customers: pl.DataFrame
) -> None:
    """Batches are emitted at the configured size."""
    config = JourneyConfig(batch_size=50)

    sizes = [
        batch.height
        for batch in iter_persona_batches(customer_config, config, customers.head(120), SEED)
    ]

    assert sizes == [50, 50, 20]


def test_generation_is_deterministic(
    customer_config: CustomerConfig, journey_config: JourneyConfig, customers: pl.DataFrame
) -> None:
    """The same seed reproduces the same personas."""
    assert generate_personas(customer_config, journey_config, customers, SEED).equals(
        generate_personas(customer_config, journey_config, customers, SEED)
    )


def test_generation_varies_with_the_seed(
    customer_config: CustomerConfig, journey_config: JourneyConfig, customers: pl.DataFrame
) -> None:
    """A different seed produces different personas."""
    assert not generate_personas(customer_config, journey_config, customers, 1).equals(
        generate_personas(customer_config, journey_config, customers, 2)
    )


def test_personas_require_customers(
    customer_config: CustomerConfig, journey_config: JourneyConfig, customers: pl.DataFrame
) -> None:
    """Personas cannot be generated without customers."""
    with pytest.raises(ValueError, match="customers dataset is empty"):
        generate_personas(customer_config, journey_config, customers.clear(), SEED)
