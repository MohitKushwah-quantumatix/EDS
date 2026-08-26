"""Generator for the browsing sessions dataset.

A session's shape is driven by its customer's persona: how many sessions they
have, how long each runs, and how many pages they view. Technical attributes
are drawn coherently rather than independently - Safari never appears on
Android, and a mobile session never reports Windows - because incoherent
combinations are immediately obvious in a demo dashboard.

Session start times are sampled uniformly across the customer's tenure and
then sorted, so sessions spread naturally over the window instead of landing
on consecutive days. Seasonal shoppers are biased towards November and
December, matching their persona description.
"""

from __future__ import annotations

import random
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final

import polars as pl

from eds.config import CustomerConfig, JourneyConfig
from eds.core.frames import build_frame, empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.journey.enums import (
    Browser,
    DeviceType,
    ExitPage,
    LandingPage,
    OperatingSystem,
    PersonaName,
    TrafficSource,
)
from eds.domains.retail.domain.journey.schema import SESSIONS
from eds.domains.retail.generators.journey.persona_generator import persona_profile

__all__ = ["SessionLocations", "generate_sessions", "iter_session_batches"]

_DEVICES: Final[tuple[DeviceType, ...]] = (
    DeviceType.MOBILE,
    DeviceType.DESKTOP,
    DeviceType.TABLET,
)
_DEVICE_WEIGHTS: Final[tuple[int, ...]] = (65, 30, 5)

# Operating systems are constrained by device class.
_OS_BY_DEVICE: Final[dict[DeviceType, tuple[tuple[OperatingSystem, ...], tuple[int, ...]]]] = {
    DeviceType.MOBILE: ((OperatingSystem.ANDROID, OperatingSystem.IOS), (62, 38)),
    DeviceType.TABLET: ((OperatingSystem.IOS, OperatingSystem.ANDROID), (55, 45)),
    DeviceType.DESKTOP: (
        (OperatingSystem.WINDOWS, OperatingSystem.MACOS, OperatingSystem.LINUX),
        (72, 22, 6),
    ),
}

# Browsers are constrained by operating system: Safari is Apple-only.
_BROWSER_BY_OS: Final[dict[OperatingSystem, tuple[tuple[Browser, ...], tuple[int, ...]]]] = {
    OperatingSystem.ANDROID: (
        (Browser.CHROME, Browser.FIREFOX, Browser.OPERA, Browser.EDGE),
        (80, 8, 7, 5),
    ),
    OperatingSystem.IOS: (
        (Browser.SAFARI, Browser.CHROME, Browser.FIREFOX, Browser.EDGE),
        (75, 20, 3, 2),
    ),
    OperatingSystem.WINDOWS: (
        (Browser.CHROME, Browser.EDGE, Browser.FIREFOX, Browser.OPERA),
        (62, 28, 7, 3),
    ),
    OperatingSystem.MACOS: (
        (Browser.SAFARI, Browser.CHROME, Browser.FIREFOX, Browser.OPERA),
        (50, 40, 7, 3),
    ),
    OperatingSystem.LINUX: ((Browser.CHROME, Browser.FIREFOX, Browser.OPERA), (48, 45, 7)),
}

_TRAFFIC_SOURCES: Final[tuple[TrafficSource, ...]] = (
    TrafficSource.ORGANIC_SEARCH,
    TrafficSource.PAID_SEARCH,
    TrafficSource.REFERRAL,
    TrafficSource.DIRECT,
    TrafficSource.EMAIL_CAMPAIGN,
    TrafficSource.SOCIAL_MEDIA,
    TrafficSource.DISPLAY_ADS,
)
_TRAFFIC_WEIGHTS: Final[tuple[int, ...]] = (30, 14, 10, 22, 9, 10, 5)

_LANDING_PAGES: Final[tuple[LandingPage, ...]] = (
    LandingPage.HOMEPAGE,
    LandingPage.CATEGORY,
    LandingPage.SEARCH,
    LandingPage.PROMOTION,
    LandingPage.BRAND,
    LandingPage.CAMPAIGN,
)
_LANDING_WEIGHTS: Final[tuple[int, ...]] = (40, 20, 15, 10, 8, 7)

# A click from an email or display campaign lands on campaign content.
_CAMPAIGN_LANDING_PAGES: Final[tuple[LandingPage, ...]] = (
    LandingPage.CAMPAIGN,
    LandingPage.PROMOTION,
)
_CAMPAIGN_LANDING_WEIGHTS: Final[tuple[int, ...]] = (70, 30)
_CAMPAIGN_SOURCES: Final[frozenset[TrafficSource]] = frozenset(
    {TrafficSource.EMAIL_CAMPAIGN, TrafficSource.DISPLAY_ADS}
)

_EXIT_PAGES: Final[tuple[ExitPage, ...]] = (
    ExitPage.HOMEPAGE,
    ExitPage.CATEGORY,
    ExitPage.PRODUCT,
    ExitPage.SEARCH,
    ExitPage.PROMOTION,
)
_EXIT_WEIGHTS: Final[tuple[int, ...]] = (15, 25, 35, 15, 10)

# Landing page types that are also valid exit pages. BRAND and CAMPAIGN are
# not, so a bounce landing there exits elsewhere.
_EXIT_PAGE_VALUES: Final[frozenset[str]] = frozenset(member.value for member in ExitPage)

# Shopping peaks in the evening; the small hours are quiet.
_HOURS: Final[tuple[int, ...]] = tuple(range(24))
_HOUR_WEIGHTS: Final[tuple[int, ...]] = (
    2,
    1,
    1,
    1,
    1,
    2,
    4,
    7,
    9,
    10,
    11,
    12,
    13,
    12,
    11,
    11,
    12,
    15,
    19,
    22,
    24,
    20,
    12,
    5,
)

# A bounce is a glance, not a visit.
_BOUNCE_SECONDS: Final[tuple[int, int]] = (5, 90)
_DURATION_VARIATION: Final[tuple[float, float]] = (0.5, 1.6)
_MIN_SESSION_SECONDS: Final[int] = 1

_SEASONAL_MONTHS: Final[frozenset[int]] = frozenset({11, 12})
_SEASONAL_ATTEMPTS: Final[int] = 5

# Public address blocks used per country so an IP is plausible for its
# geography. Private and reserved ranges are deliberately excluded.
_IP_PREFIXES: Final[dict[str, tuple[int, ...]]] = {
    "US": (23, 24, 45, 63, 64, 66, 68, 71, 96, 98, 104, 174, 208),
    "CA": (24, 70, 99, 142, 173, 184, 206, 207),
    "GB": (2, 5, 25, 31, 51, 62, 78, 81, 86, 90, 109, 151, 176, 188),
    "DE": (5, 46, 62, 77, 78, 79, 80, 84, 85, 87, 88, 91, 93, 178, 217),
    "AU": (1, 27, 49, 58, 59, 101, 110, 120, 124, 144, 150, 203, 210, 220),
    "IN": (14, 27, 49, 59, 106, 111, 115, 117, 122, 125, 152, 157, 182, 202),
}
_DEFAULT_IP_PREFIXES: Final[tuple[int, ...]] = (45, 63, 66, 104)


@dataclass(frozen=True, slots=True)
class SessionLocations:
    """Where each customer browses from.

    A session is placed at the customer's primary address, so its geography
    keys resolve against F001 and agree with the customer's own record.

    Attributes:
        by_customer: Customer id to ``(country_id, state_id, city_id)``.
        country_code_by_id: Country id to ISO alpha-2 code, used to pick a
            plausible IP block.
    """

    by_customer: Mapping[int, tuple[int, int, int]]
    country_code_by_id: Mapping[int, str]

    @classmethod
    def from_frames(cls, addresses: pl.DataFrame, countries: pl.DataFrame) -> SessionLocations:
        """Build the lookup from the F002 addresses and F001 countries.

        Args:
            addresses: The customer addresses dataset.
            countries: The countries dataset.

        Returns:
            The extracted lookup.

        Raises:
            ValueError: If either dataset is empty, or no address is primary.
        """
        if addresses.is_empty():
            raise ValueError("cannot generate sessions: the customer addresses dataset is empty")
        if countries.is_empty():
            raise ValueError("cannot generate sessions: the countries dataset is empty")

        primary = addresses.filter(pl.col("is_primary").cast(pl.Boolean))
        if primary.is_empty():
            raise ValueError("cannot generate sessions: no customer has a primary address")

        by_customer = {
            customer_id: (country_id, state_id, city_id)
            for customer_id, country_id, state_id, city_id in zip(
                primary["customer_id"].to_list(),
                primary["country_id"].to_list(),
                primary["state_id"].to_list(),
                primary["city_id"].to_list(),
                strict=True,
            )
        }
        country_code_by_id = dict(
            zip(
                countries["country_id"].to_list(),
                countries["country_code"].to_list(),
                strict=True,
            )
        )
        return cls(by_customer=by_customer, country_code_by_id=country_code_by_id)


def _ip_address(rng: random.Random, country_code: str) -> str:
    """Generate a plausible public IPv4 address for a country.

    Args:
        rng: Random source.
        country_code: ISO alpha-2 code.

    Returns:
        A dotted-quad address.
    """
    prefixes = _IP_PREFIXES.get(country_code, _DEFAULT_IP_PREFIXES)
    return (
        f"{rng.choice(prefixes)}.{rng.randrange(256)}.{rng.randrange(256)}.{rng.randrange(1, 255)}"
    )


def _start_time(rng: random.Random, earliest: date, latest: date, seasonal: bool) -> datetime:
    """Sample a session start within the customer's active window.

    Args:
        rng: Random source.
        earliest: First eligible day.
        latest: Last eligible day.
        seasonal: Whether to bias towards the holiday months.

    Returns:
        A timestamp on an eligible day, with an evening-weighted hour.
    """
    span_days = (latest - earliest).days
    day = earliest
    for _ in range(_SEASONAL_ATTEMPTS if seasonal else 1):
        day = earliest + timedelta(days=rng.randrange(span_days + 1))
        if not seasonal or day.month in _SEASONAL_MONTHS:
            break
    hour = rng.choices(_HOURS, weights=_HOUR_WEIGHTS, k=1)[0]
    return datetime.combine(day, time(hour, rng.randrange(60), rng.randrange(60)))


def _device_stack(rng: random.Random) -> tuple[DeviceType, OperatingSystem, Browser]:
    """Pick a coherent device, operating system, and browser combination.

    Args:
        rng: Random source.

    Returns:
        The chosen stack.
    """
    device = rng.choices(_DEVICES, weights=_DEVICE_WEIGHTS, k=1)[0]
    systems, os_weights = _OS_BY_DEVICE[device]
    operating_system = rng.choices(systems, weights=os_weights, k=1)[0]
    browsers, browser_weights = _BROWSER_BY_OS[operating_system]
    return device, operating_system, rng.choices(browsers, weights=browser_weights, k=1)[0]


def _landing_page(rng: random.Random, source: TrafficSource) -> LandingPage:
    """Pick a landing page consistent with the traffic source.

    Args:
        rng: Random source.
        source: The session's traffic source.

    Returns:
        The landing page.
    """
    if source in _CAMPAIGN_SOURCES:
        return rng.choices(_CAMPAIGN_LANDING_PAGES, weights=_CAMPAIGN_LANDING_WEIGHTS, k=1)[0]
    return rng.choices(_LANDING_PAGES, weights=_LANDING_WEIGHTS, k=1)[0]


def iter_session_batches(
    customer_config: CustomerConfig,
    journey_config: JourneyConfig,
    personas: pl.DataFrame,
    customers: pl.DataFrame,
    locations: SessionLocations,
    seed: int,
) -> Iterator[pl.DataFrame]:
    """Yield sessions in batches, grouped by customer.

    Args:
        customer_config: Customer configuration, supplying the reference date.
        journey_config: Journey configuration.
        personas: The generated personas dataset.
        customers: The F002 customers dataset.
        locations: Where each customer browses from.
        seed: Run seed.

    Yields:
        Frames matching the sessions schema. A customer's sessions are never
        split across two frames.

    Raises:
        ValueError: If a customer has no primary address to browse from.
    """
    rng = make_rng(seed, "sessions")
    reference = customer_config.reference_date

    registration_by_customer = dict(
        zip(
            customers["customer_id"].to_list(),
            customers["registration_date"].to_list(),
            strict=True,
        )
    )

    persona_customer_ids: list[int] = personas["customer_id"].to_list()
    persona_names: list[str] = personas["persona_name"].to_list()
    frequencies: list[int] = personas["session_frequency"].to_list()
    average_minutes: list[float] = personas["average_session_minutes"].to_list()

    session_ids: list[int] = []
    customer_ids: list[int] = []
    names: list[str] = []
    devices: list[str] = []
    browsers: list[str] = []
    systems: list[str] = []
    sources: list[str] = []
    landings: list[str] = []
    exits: list[str] = []
    country_ids: list[int] = []
    state_ids: list[int] = []
    city_ids: list[int] = []
    addresses: list[str] = []
    starts: list[datetime] = []
    ends: list[datetime] = []
    durations: list[int] = []
    pages: list[int] = []
    bounces: list[bool] = []
    created: list[datetime] = []

    next_session_id = 1

    def flush() -> pl.DataFrame:
        """Build a frame from the accumulated rows and reset the buffers."""
        frame = build_frame(
            SESSIONS,
            {
                "session_id": session_ids,
                "customer_id": customer_ids,
                "persona_name": names,
                "device_type": devices,
                "browser": browsers,
                "operating_system": systems,
                "traffic_source": sources,
                "landing_page": landings,
                "exit_page": exits,
                "country_id": country_ids,
                "state_id": state_ids,
                "city_id": city_ids,
                "ip_address": addresses,
                "start_time": starts,
                "end_time": ends,
                "duration_seconds": durations,
                "pages_viewed": pages,
                "bounce": bounces,
                "created_at": created,
            },
        )
        for buffer in (
            session_ids,
            customer_ids,
            names,
            devices,
            browsers,
            systems,
            sources,
            landings,
            exits,
            country_ids,
            state_ids,
            city_ids,
            addresses,
            starts,
            ends,
            durations,
            pages,
            bounces,
            created,
        ):
            buffer.clear()
        return frame

    for index, customer_id in enumerate(persona_customer_ids):
        location = locations.by_customer.get(customer_id)
        if location is None:
            raise ValueError(
                f"cannot generate sessions: customer {customer_id} has no primary address"
            )
        country_id, state_id, city_id = location
        country_code = locations.country_code_by_id.get(country_id, "")

        registration = registration_by_customer[customer_id]
        earliest = registration
        if earliest > reference:
            continue

        persona = persona_names[index]
        profile = persona_profile(persona)
        seasonal = profile.name is PersonaName.SEASONAL_SHOPPER
        page_ceiling = min(profile.max_pages, journey_config.max_pages_viewed)
        centre_minutes = average_minutes[index]

        # Sort so a customer's sessions read chronologically.
        session_starts = sorted(
            _start_time(rng, earliest, reference, seasonal) for _ in range(frequencies[index])
        )

        for start in session_starts:
            device, operating_system, browser = _device_stack(rng)
            source = rng.choices(_TRAFFIC_SOURCES, weights=_TRAFFIC_WEIGHTS, k=1)[0]
            bounce = rng.random() < journey_config.bounce_rate

            if bounce:
                duration = rng.randint(*_BOUNCE_SECONDS)
                viewed = 1
            else:
                minutes = centre_minutes * rng.uniform(*_DURATION_VARIATION)
                duration = max(_MIN_SESSION_SECONDS, int(minutes * 60))
                viewed = rng.randint(2, page_ceiling)

            end = start + timedelta(seconds=duration)
            landing = _landing_page(rng, source)
            # A bounce ends where it started, whenever that page type is also
            # a valid exit page.
            exit_page = (
                ExitPage(landing.value)
                if bounce and landing.value in _EXIT_PAGE_VALUES
                else rng.choices(_EXIT_PAGES, weights=_EXIT_WEIGHTS, k=1)[0]
            )

            session_ids.append(next_session_id)
            customer_ids.append(customer_id)
            names.append(persona)
            devices.append(str(device))
            browsers.append(str(browser))
            systems.append(str(operating_system))
            sources.append(str(source))
            landings.append(str(landing))
            exits.append(str(exit_page))
            country_ids.append(country_id)
            state_ids.append(state_id)
            city_ids.append(city_id)
            addresses.append(_ip_address(rng, country_code))
            starts.append(start)
            ends.append(end)
            durations.append(duration)
            pages.append(viewed)
            bounces.append(bounce)
            created.append(end)
            next_session_id += 1

        if len(session_ids) >= journey_config.batch_size:
            yield flush()

    if session_ids:
        yield flush()


def generate_sessions(
    customer_config: CustomerConfig,
    journey_config: JourneyConfig,
    personas: pl.DataFrame,
    customers: pl.DataFrame,
    locations: SessionLocations,
    seed: int,
) -> pl.DataFrame:
    """Generate the complete sessions dataset.

    Args:
        customer_config: Customer configuration, supplying the reference date.
        journey_config: Journey configuration.
        personas: The generated personas dataset.
        customers: The F002 customers dataset.
        locations: Where each customer browses from.
        seed: Run seed.

    Returns:
        One row per browsing session, keyed by sequential ``session_id``.

    Raises:
        ValueError: If a customer has no primary address to browse from.
    """
    batches = list(
        iter_session_batches(customer_config, journey_config, personas, customers, locations, seed)
    )
    return pl.concat(batches, how="vertical") if batches else empty_frame(SESSIONS)
