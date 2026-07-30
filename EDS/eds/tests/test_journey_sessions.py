"""Tests for the browsing session generator."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

import polars as pl
import pytest

from eds.config import CustomerConfig, JourneyConfig
from eds.domain.journey.enums import (
    Browser,
    DeviceType,
    ExitPage,
    LandingPage,
    OperatingSystem,
    PersonaName,
    TrafficSource,
)
from eds.generators.customer_data import CustomerData
from eds.generators.journey.persona_generator import generate_personas
from eds.generators.journey.session_generator import (
    SessionLocations,
    generate_sessions,
    iter_session_batches,
)
from eds.generators.master_data import MasterData

SEED = 707

APPLE_SYSTEMS = {str(OperatingSystem.IOS), str(OperatingSystem.MACOS)}
MOBILE_SYSTEMS = {str(OperatingSystem.ANDROID), str(OperatingSystem.IOS)}
DESKTOP_SYSTEMS = {
    str(OperatingSystem.WINDOWS),
    str(OperatingSystem.MACOS),
    str(OperatingSystem.LINUX),
}


@pytest.fixture
def customers(customer_data: CustomerData) -> pl.DataFrame:
    """Return the generated customers frame."""
    return customer_data["customers"]


@pytest.fixture
def journey_config() -> JourneyConfig:
    """Return a journey configuration with a small batch size."""
    return JourneyConfig(batch_size=60)


@pytest.fixture
def personas(
    small_customer_config: CustomerConfig,
    journey_config: JourneyConfig,
    customers: pl.DataFrame,
) -> pl.DataFrame:
    """Return generated personas for the fixture customers."""
    return generate_personas(small_customer_config, journey_config, customers, SEED)


@pytest.fixture
def sessions(
    small_customer_config: CustomerConfig,
    journey_config: JourneyConfig,
    personas: pl.DataFrame,
    customers: pl.DataFrame,
    session_locations: SessionLocations,
) -> pl.DataFrame:
    """Return generated sessions for the fixture customers."""
    return generate_sessions(
        small_customer_config, journey_config, personas, customers, session_locations, SEED
    )


def test_locations_require_addresses(journey_upstream: dict[str, pl.DataFrame]) -> None:
    """Sessions cannot be placed without customer addresses."""
    with pytest.raises(ValueError, match="customer addresses dataset is empty"):
        SessionLocations.from_frames(
            journey_upstream["customer_addresses"].clear(), journey_upstream["countries"]
        )


def test_locations_require_countries(journey_upstream: dict[str, pl.DataFrame]) -> None:
    """An empty countries dataset stops generation."""
    with pytest.raises(ValueError, match="countries dataset is empty"):
        SessionLocations.from_frames(
            journey_upstream["customer_addresses"], journey_upstream["countries"].clear()
        )


def test_locations_require_a_primary_address(
    journey_upstream: dict[str, pl.DataFrame],
) -> None:
    """Without a primary address there is no place to browse from."""
    addresses = journey_upstream["customer_addresses"].with_columns(
        pl.lit(False).alias("is_primary")
    )

    with pytest.raises(ValueError, match="no customer has a primary address"):
        SessionLocations.from_frames(addresses, journey_upstream["countries"])


def test_session_ids_are_unique_and_sequential(sessions: pl.DataFrame) -> None:
    """Session ids form a dense sequence starting at one."""
    assert sessions["session_id"].to_list() == list(range(1, sessions.height + 1))


def test_session_count_matches_persona_frequency(
    sessions: pl.DataFrame, personas: pl.DataFrame
) -> None:
    """Each customer has exactly the number of sessions their persona implies."""
    actual = sessions.group_by("customer_id").len().rename({"len": "actual"})
    joined = personas.select("customer_id", "session_frequency").join(
        actual, on="customer_id", how="left"
    )
    filled = joined.with_columns(pl.col("actual").fill_null(0))

    assert filled.filter(pl.col("actual") != pl.col("session_frequency")).height == 0


def test_every_session_belongs_to_a_known_customer(
    sessions: pl.DataFrame, customers: pl.DataFrame
) -> None:
    """Sessions never reference an unknown customer."""
    assert set(sessions["customer_id"].to_list()) <= set(customers["customer_id"].to_list())


def test_session_geography_matches_the_primary_address(
    sessions: pl.DataFrame, journey_upstream: dict[str, pl.DataFrame]
) -> None:
    """A session is placed at the customer's primary address."""
    primary = journey_upstream["customer_addresses"].filter(pl.col("is_primary"))
    joined = sessions.join(
        primary.select("customer_id", "country_id", "state_id", "city_id"),
        on="customer_id",
        how="inner",
        suffix="_address",
    )

    assert joined.height == sessions.height
    for column in ("country_id", "state_id", "city_id"):
        assert joined.filter(pl.col(column) != pl.col(f"{column}_address")).height == 0


def test_session_geography_resolves_against_master_data(
    sessions: pl.DataFrame, master_data: MasterData
) -> None:
    """Geography keys point at real F001 rows."""
    assert set(sessions["city_id"].to_list()) <= set(master_data["cities"]["city_id"].to_list())
    assert set(sessions["state_id"].to_list()) <= set(master_data["states"]["state_id"].to_list())
    assert set(sessions["country_id"].to_list()) <= set(
        master_data["countries"]["country_id"].to_list()
    )


@pytest.mark.parametrize(
    ("column", "enum"),
    [
        ("device_type", DeviceType),
        ("browser", Browser),
        ("operating_system", OperatingSystem),
        ("traffic_source", TrafficSource),
        ("landing_page", LandingPage),
        ("exit_page", ExitPage),
        ("persona_name", PersonaName),
    ],
)
def test_categorical_columns_use_declared_values(
    sessions: pl.DataFrame, column: str, enum: type[StrEnum]
) -> None:
    """Every categorical column draws from its declared enum."""
    known = {str(member) for member in enum}

    assert set(sessions[column].to_list()) <= known


def test_landing_and_exit_pages_always_exist(sessions: pl.DataFrame) -> None:
    """Neither page is ever null."""
    assert sessions["landing_page"].null_count() == 0
    assert sessions["exit_page"].null_count() == 0


def test_device_distribution_is_approximately_as_specified(
    sessions: pl.DataFrame,
) -> None:
    """Devices follow the documented 65/30/5 split."""
    share = {
        row["device_type"]: row["count"] / sessions.height
        for row in sessions["device_type"].value_counts().to_dicts()
    }

    assert share[str(DeviceType.MOBILE)] == pytest.approx(0.65, abs=0.05)
    assert share[str(DeviceType.DESKTOP)] == pytest.approx(0.30, abs=0.05)
    assert share[str(DeviceType.TABLET)] == pytest.approx(0.05, abs=0.03)


def test_operating_system_matches_the_device_class(sessions: pl.DataFrame) -> None:
    """A mobile session never reports a desktop operating system."""
    mobile = sessions.filter(pl.col("device_type") == str(DeviceType.MOBILE))
    desktop = sessions.filter(pl.col("device_type") == str(DeviceType.DESKTOP))

    assert set(mobile["operating_system"].to_list()) <= MOBILE_SYSTEMS
    assert set(desktop["operating_system"].to_list()) <= DESKTOP_SYSTEMS


def test_safari_only_appears_on_apple_systems(sessions: pl.DataFrame) -> None:
    """Safari never runs on Android, Windows, or Linux."""
    safari = sessions.filter(pl.col("browser") == str(Browser.SAFARI))

    assert set(safari["operating_system"].to_list()) <= APPLE_SYSTEMS


def test_bounce_rate_is_approximately_configured(sessions: pl.DataFrame) -> None:
    """Roughly a quarter of sessions bounce."""
    assert sessions["bounce"].sum() / sessions.height == pytest.approx(0.25, abs=0.05)


def test_bounce_sessions_view_one_page(sessions: pl.DataFrame) -> None:
    """A bounce views exactly one page."""
    bounced = sessions.filter(pl.col("bounce"))

    assert set(bounced["pages_viewed"].to_list()) == {1}


def test_non_bounce_sessions_view_between_two_and_the_maximum(
    sessions: pl.DataFrame, journey_config: JourneyConfig
) -> None:
    """A non-bounce views two to twenty-five pages."""
    engaged = sessions.filter(~pl.col("bounce"))
    pages = engaged["pages_viewed"].to_list()

    assert min(pages) >= 2
    assert max(pages) <= journey_config.max_pages_viewed


def test_page_ceiling_respects_the_configuration(
    small_customer_config: CustomerConfig,
    personas: pl.DataFrame,
    customers: pl.DataFrame,
    session_locations: SessionLocations,
) -> None:
    """Lowering the configured maximum lowers the observed maximum."""
    config = JourneyConfig(max_pages_viewed=5, batch_size=60)
    capped = generate_sessions(
        small_customer_config, config, personas, customers, session_locations, SEED
    )

    assert max(capped["pages_viewed"].to_list()) <= 5


def test_duration_is_positive_and_matches_the_timestamps(
    sessions: pl.DataFrame,
) -> None:
    """Duration is consistent with start and end times."""
    assert sessions.filter(pl.col("duration_seconds") <= 0).height == 0
    mismatched = sessions.filter(
        (pl.col("end_time") - pl.col("start_time")).dt.total_seconds() != pl.col("duration_seconds")
    )

    assert mismatched.height == 0


def test_end_time_is_always_after_start_time(sessions: pl.DataFrame) -> None:
    """Sessions never end before they begin."""
    assert sessions.filter(pl.col("end_time") <= pl.col("start_time")).height == 0


def test_sessions_start_after_registration(sessions: pl.DataFrame, customers: pl.DataFrame) -> None:
    """No session predates its customer's registration."""
    joined = sessions.join(customers.select("customer_id", "registration_date"), on="customer_id")

    assert joined.filter(pl.col("start_time").dt.date() <= pl.col("registration_date")).height == 0


def test_sessions_fall_within_the_five_year_window(
    sessions: pl.DataFrame, small_customer_config: CustomerConfig
) -> None:
    """Every session sits inside the configured window."""
    earliest = small_customer_config.reference_date - timedelta(days=5 * 365)
    dates = [value.date() for value in sessions["start_time"].to_list()]

    assert min(dates) >= earliest
    assert max(dates) <= small_customer_config.reference_date


def test_sessions_are_chronological_per_customer(sessions: pl.DataFrame) -> None:
    """A customer's sessions are emitted in time order."""
    for (_,), group in sessions.group_by("customer_id"):
        starts = group["start_time"].to_list()
        assert starts == sorted(starts)


def test_sessions_do_not_land_on_consecutive_days(sessions: pl.DataFrame) -> None:
    """Sessions spread across the window rather than bunching day by day."""
    busiest = (
        sessions.with_columns(pl.col("start_time").dt.date().alias("day"))
        .group_by("customer_id", "day")
        .len()
    )
    distinct_days = busiest.group_by("customer_id").len()["len"].to_list()
    per_customer = sessions.group_by("customer_id").len()["len"].to_list()

    # Nearly every session falls on its own day.
    assert sum(distinct_days) / sum(per_customer) > 0.95


def test_seasonal_shoppers_concentrate_in_the_holidays(
    sessions: pl.DataFrame,
) -> None:
    """Seasonal shoppers browse mostly in November and December."""
    seasonal = sessions.filter(pl.col("persona_name") == str(PersonaName.SEASONAL_SHOPPER))
    if seasonal.is_empty():
        pytest.skip("no seasonal shoppers in this sample")

    holiday = seasonal.filter(pl.col("start_time").dt.month().is_in([11, 12]))
    others = sessions.filter(pl.col("persona_name") != str(PersonaName.SEASONAL_SHOPPER))
    baseline = others.filter(pl.col("start_time").dt.month().is_in([11, 12]))

    assert holiday.height / seasonal.height > baseline.height / others.height


def test_ip_addresses_are_well_formed_ipv4(sessions: pl.DataFrame) -> None:
    """Every address is a dotted quad with octets in range."""
    for address in sessions["ip_address"].to_list():
        octets = address.split(".")
        assert len(octets) == 4
        assert all(octet.isdigit() and 0 <= int(octet) <= 255 for octet in octets)


def test_ip_addresses_avoid_private_ranges(sessions: pl.DataFrame) -> None:
    """Generated addresses look like public internet traffic."""
    for address in sessions["ip_address"].to_list():
        first, second = (int(part) for part in address.split(".")[:2])
        assert first not in {0, 10, 127}
        assert not (first == 192 and second == 168)
        assert not (first == 172 and 16 <= second <= 31)


def test_batching_does_not_change_the_output(
    small_customer_config: CustomerConfig,
    personas: pl.DataFrame,
    customers: pl.DataFrame,
    session_locations: SessionLocations,
) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = generate_sessions(
        small_customer_config,
        JourneyConfig(batch_size=13),
        personas,
        customers,
        session_locations,
        SEED,
    )
    large = generate_sessions(
        small_customer_config,
        JourneyConfig(batch_size=100_000),
        personas,
        customers,
        session_locations,
        SEED,
    )

    assert small.equals(large)


def test_batches_never_split_a_customer(
    small_customer_config: CustomerConfig,
    personas: pl.DataFrame,
    customers: pl.DataFrame,
    session_locations: SessionLocations,
) -> None:
    """A customer's sessions always land in one frame."""
    seen: set[int] = set()

    for batch in iter_session_batches(
        small_customer_config,
        JourneyConfig(batch_size=40),
        personas,
        customers,
        session_locations,
        SEED,
    ):
        customers_in_batch = set(batch["customer_id"].to_list())
        assert not (customers_in_batch & seen)
        seen |= customers_in_batch


def test_generation_is_deterministic(
    small_customer_config: CustomerConfig,
    journey_config: JourneyConfig,
    personas: pl.DataFrame,
    customers: pl.DataFrame,
    session_locations: SessionLocations,
) -> None:
    """The same seed reproduces the same sessions."""
    first = generate_sessions(
        small_customer_config, journey_config, personas, customers, session_locations, SEED
    )
    second = generate_sessions(
        small_customer_config, journey_config, personas, customers, session_locations, SEED
    )

    assert first.equals(second)


def test_generation_varies_with_the_seed(
    small_customer_config: CustomerConfig,
    journey_config: JourneyConfig,
    personas: pl.DataFrame,
    customers: pl.DataFrame,
    session_locations: SessionLocations,
) -> None:
    """A different seed produces different sessions."""
    first = generate_sessions(
        small_customer_config, journey_config, personas, customers, session_locations, 1
    )
    second = generate_sessions(
        small_customer_config, journey_config, personas, customers, session_locations, 2
    )

    assert not first.equals(second)


def test_missing_primary_address_is_reported(
    small_customer_config: CustomerConfig,
    journey_config: JourneyConfig,
    personas: pl.DataFrame,
    customers: pl.DataFrame,
    journey_upstream: dict[str, pl.DataFrame],
) -> None:
    """A customer without a primary address stops generation."""
    addresses = journey_upstream["customer_addresses"].filter(pl.col("customer_id") != 1)
    locations = SessionLocations.from_frames(addresses, journey_upstream["countries"])

    with pytest.raises(ValueError, match="has no primary address"):
        generate_sessions(
            small_customer_config, journey_config, personas, customers, locations, SEED
        )
