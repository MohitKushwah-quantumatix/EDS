"""Tests for the customer profile generator."""

from __future__ import annotations

from enum import StrEnum

import polars as pl
import pytest

from eds.config import CustomerConfig
from eds.domain.customer.enums import (
    AcquisitionChannel,
    CustomerSegment,
    CustomerStatus,
    Gender,
    LifecycleStage,
    RegistrationSource,
)
from eds.generators.customers.customer_generator import (
    CustomerGeography,
    assign_home_cities,
    customer_id_batches,
    generate_customers,
    iter_customer_batches,
)
from eds.generators.master_data import MasterData

SEED = 5150


@pytest.fixture
def settings() -> CustomerConfig:
    """Return a small customer configuration."""
    return CustomerConfig(customer_count=250, batch_size=100)


def test_geography_requires_cities(master_data: MasterData) -> None:
    """Customers cannot be placed without a city to live in."""
    with pytest.raises(ValueError, match="cities dataset is empty"):
        CustomerGeography.from_frames(
            master_data["cities"].clear(), master_data["states"], master_data["countries"]
        )


def test_geography_requires_states(master_data: MasterData) -> None:
    """An empty states dataset stops generation."""
    with pytest.raises(ValueError, match="states dataset is empty"):
        CustomerGeography.from_frames(
            master_data["cities"], master_data["states"].clear(), master_data["countries"]
        )


def test_geography_requires_countries(master_data: MasterData) -> None:
    """An empty countries dataset stops generation."""
    with pytest.raises(ValueError, match="countries dataset is empty"):
        CustomerGeography.from_frames(
            master_data["cities"], master_data["states"], master_data["countries"].clear()
        )


def test_home_city_assignment_is_deterministic(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """The shared city assignment is a pure function of its inputs."""
    first = assign_home_cities(settings, customer_geography, SEED)
    second = assign_home_cities(settings, customer_geography, SEED)

    assert first == second
    assert len(first) == settings.customer_count


def test_home_city_assignment_varies_with_seed(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """A different seed places customers differently."""
    assert assign_home_cities(settings, customer_geography, 1) != assign_home_cities(
        settings, customer_geography, 2
    )


def test_customer_id_batches_cover_every_id() -> None:
    """Batching partitions the id space exactly once."""
    config = CustomerConfig(customer_count=25, batch_size=10)

    ids = [customer_id for batch in customer_id_batches(config) for customer_id in batch]

    assert ids == list(range(1, 26))


def test_customer_id_batches_respect_batch_size() -> None:
    """No batch exceeds the configured size."""
    config = CustomerConfig(customer_count=25, batch_size=10)

    sizes = [len(batch) for batch in customer_id_batches(config)]

    assert sizes == [10, 10, 5]


def test_customer_count_and_sequential_ids(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """Exactly the configured number of customers is produced."""
    customers = generate_customers(settings, customer_geography, SEED)

    assert customers.height == settings.customer_count
    assert customers["customer_id"].to_list() == list(range(1, settings.customer_count + 1))


def test_identity_columns_are_unique(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """Email, phone, and customer number are natural keys."""
    customers = generate_customers(settings, customer_geography, SEED)

    for column in ("customer_number", "email", "phone"):
        assert customers[column].n_unique() == customers.height, column


def test_full_name_matches_its_parts(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """The denormalised full name agrees with first and last name."""
    customers = generate_customers(settings, customer_geography, SEED)

    mismatched = customers.filter(
        pl.col("full_name") != pl.col("first_name") + pl.lit(" ") + pl.col("last_name")
    )

    assert mismatched.height == 0


def test_batching_does_not_change_the_output(
    customer_geography: CustomerGeography,
) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = CustomerConfig(customer_count=60, batch_size=7)
    large = CustomerConfig(customer_count=60, batch_size=10_000)

    assert generate_customers(small, customer_geography, SEED).equals(
        generate_customers(large, customer_geography, SEED)
    )


def test_batch_sizes_follow_configuration(
    customer_geography: CustomerGeography,
) -> None:
    """Batches are emitted at the configured size."""
    config = CustomerConfig(customer_count=25, batch_size=10)

    sizes = [batch.height for batch in iter_customer_batches(config, customer_geography, SEED)]

    assert sizes == [10, 10, 5]


def test_generation_is_deterministic(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """The same seed reproduces the same customers."""
    assert generate_customers(settings, customer_geography, SEED).equals(
        generate_customers(settings, customer_geography, SEED)
    )


def test_generation_varies_with_the_seed(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """A different seed produces different customers."""
    assert not generate_customers(settings, customer_geography, 1).equals(
        generate_customers(settings, customer_geography, 2)
    )


@pytest.mark.parametrize(
    ("column", "enum"),
    [
        ("gender", Gender),
        ("status", CustomerStatus),
        ("customer_segment", CustomerSegment),
        ("registration_source", RegistrationSource),
        ("acquisition_channel", AcquisitionChannel),
        ("lifecycle_stage", LifecycleStage),
    ],
)
def test_enum_columns_use_declared_values(
    settings: CustomerConfig,
    customer_geography: CustomerGeography,
    column: str,
    enum: type[StrEnum],
) -> None:
    """Every categorical column draws from its declared enum."""
    customers = generate_customers(settings, customer_geography, SEED)
    known = {str(member) for member in enum}

    assert set(customers[column].to_list()) <= known


def test_registration_dates_fall_inside_the_window(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """Registration covers the configured number of years and no more."""
    customers = generate_customers(settings, customer_geography, SEED)
    dates = customers["registration_date"].to_list()

    assert min(dates) >= settings.earliest_registration_date
    assert max(dates) <= settings.reference_date


def test_customers_are_adults_at_the_reference_date(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """No customer is under eighteen."""
    customers = generate_customers(settings, customer_geography, SEED)
    oldest_allowed_birth = settings.reference_date.replace(year=settings.reference_date.year - 18)

    assert max(customers["date_of_birth"].to_list()) <= oldest_allowed_birth


def test_risk_scores_are_bounded_and_low_on_average(
    customer_geography: CustomerGeography,
) -> None:
    """Risk is clamped to 0-100 with a mean near 25 and a thin high tail."""
    config = CustomerConfig(customer_count=4_000, batch_size=1_000)
    scores = generate_customers(config, customer_geography, SEED)["risk_score"].to_list()

    assert min(scores) >= 0.0
    assert max(scores) <= 100.0
    assert 22.0 <= sum(scores) / len(scores) <= 28.0
    assert sum(1 for score in scores if score > 75) / len(scores) < 0.05


def test_segment_distribution_is_approximately_as_specified(
    customer_geography: CustomerGeography,
) -> None:
    """Segments follow the documented 35/40/20/5 split."""
    config = CustomerConfig(customer_count=6_000, batch_size=2_000)
    customers = generate_customers(config, customer_geography, SEED)
    share = {
        row["customer_segment"]: row["count"] / config.customer_count
        for row in customers["customer_segment"].value_counts().to_dicts()
    }

    assert share[str(CustomerSegment.NEW)] == pytest.approx(0.35, abs=0.03)
    assert share[str(CustomerSegment.REGULAR)] == pytest.approx(0.40, abs=0.03)
    assert share[str(CustomerSegment.PREMIUM)] == pytest.approx(0.20, abs=0.03)
    assert share[str(CustomerSegment.VIP)] == pytest.approx(0.05, abs=0.02)


def test_status_and_verification_rates_match_the_specification(
    customer_geography: CustomerGeography,
) -> None:
    """Status, email, and mobile verification follow the documented rates."""
    config = CustomerConfig(customer_count=6_000, batch_size=2_000)
    customers = generate_customers(config, customer_geography, SEED)
    total = customers.height

    active = customers.filter(pl.col("status") == str(CustomerStatus.ACTIVE)).height
    assert active / total == pytest.approx(0.94, abs=0.02)
    assert customers["email_verified"].sum() / total == pytest.approx(0.92, abs=0.02)
    assert customers["mobile_verified"].sum() / total == pytest.approx(0.90, abs=0.02)


def test_lifecycle_stage_never_contradicts_status(
    customer_geography: CustomerGeography,
) -> None:
    """A closed account is churned; a suspended one is at risk."""
    config = CustomerConfig(customer_count=3_000, batch_size=1_000)
    customers = generate_customers(config, customer_geography, SEED)

    closed = customers.filter(pl.col("status") == str(CustomerStatus.CLOSED))
    suspended = customers.filter(pl.col("status") == str(CustomerStatus.SUSPENDED))

    assert set(closed["lifecycle_stage"].to_list()) <= {str(LifecycleStage.CHURNED)}
    assert set(suspended["lifecycle_stage"].to_list()) <= {str(LifecycleStage.AT_RISK)}


def test_language_and_currency_come_from_the_home_country(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """A US-only master dataset yields US language and currency."""
    customers = generate_customers(settings, customer_geography, SEED)

    assert set(customers["preferred_language"].to_list()) == {"en-US"}
    assert set(customers["preferred_currency"].to_list()) == {"USD"}


def test_updated_at_is_never_before_created_at(
    settings: CustomerConfig, customer_geography: CustomerGeography
) -> None:
    """Audit timestamps are chronologically ordered."""
    customers = generate_customers(settings, customer_geography, SEED)

    assert customers.filter(pl.col("updated_at") < pl.col("created_at")).height == 0
