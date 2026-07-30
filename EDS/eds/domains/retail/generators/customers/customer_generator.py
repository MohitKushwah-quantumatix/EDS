"""Generator for the customers master dataset.

Each customer is anchored to a **home city** drawn from the F001 geography
datasets. That single assignment drives the customer's language, currency, and
timezone, and is reused by the address and preference generators so all four
customer datasets agree with one another.

The assignment is a pure function of ``(config, geography, seed)``, so any
generator can recompute it instead of threading state between modules.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final

import polars as pl

from eds.config import CustomerConfig
from eds.core.frames import build_frame, format_code
from eds.core.random_streams import make_faker, make_rng
from eds.domains.retail.domain.customer.enums import (
    AcquisitionChannel,
    CustomerSegment,
    CustomerStatus,
    Gender,
    LifecycleStage,
    RegistrationSource,
)
from eds.domains.retail.domain.customer.schema import CUSTOMERS

__all__ = [
    "CustomerGeography",
    "assign_home_cities",
    "customer_id_batches",
    "generate_customers",
    "iter_customer_batches",
    "lifecycle_stage",
]

_SEGMENTS: Final[tuple[CustomerSegment, ...]] = (
    CustomerSegment.NEW,
    CustomerSegment.REGULAR,
    CustomerSegment.PREMIUM,
    CustomerSegment.VIP,
)
_SEGMENT_WEIGHTS: Final[tuple[int, ...]] = (35, 40, 20, 5)

_STATUSES: Final[tuple[CustomerStatus, ...]] = (
    CustomerStatus.ACTIVE,
    CustomerStatus.INACTIVE,
    CustomerStatus.SUSPENDED,
    CustomerStatus.CLOSED,
)
_STATUS_WEIGHTS: Final[tuple[int, ...]] = (94, 3, 2, 1)

_SOURCES: Final[tuple[RegistrationSource, ...]] = (
    RegistrationSource.WEB,
    RegistrationSource.ANDROID_APP,
    RegistrationSource.IOS_APP,
    RegistrationSource.PARTNER_PORTAL,
)
_SOURCE_WEIGHTS: Final[tuple[int, ...]] = (45, 25, 22, 8)

_CHANNELS: Final[tuple[AcquisitionChannel, ...]] = (
    AcquisitionChannel.ORGANIC_SEARCH,
    AcquisitionChannel.PAID_SEARCH,
    AcquisitionChannel.SOCIAL_MEDIA,
    AcquisitionChannel.EMAIL_CAMPAIGN,
    AcquisitionChannel.REFERRAL,
    AcquisitionChannel.DIRECT,
)
_CHANNEL_WEIGHTS: Final[tuple[int, ...]] = (28, 18, 20, 12, 12, 10)

_GENDERS: Final[tuple[Gender, ...]] = (
    Gender.FEMALE,
    Gender.MALE,
    Gender.NON_BINARY,
    Gender.UNDISCLOSED,
)
_GENDER_WEIGHTS: Final[tuple[int, ...]] = (48, 48, 2, 2)

_EMAIL_VERIFIED_RATE: Final[float] = 0.92
_MOBILE_VERIFIED_RATE: Final[float] = 0.90

# Risk score is normally distributed with a low mean, so most customers are
# low risk and the high-risk tail is thin.
_RISK_MEAN: Final[float] = 25.0
_RISK_STDDEV: Final[float] = 15.0
_RISK_MIN: Final[float] = 0.0
_RISK_MAX: Final[float] = 100.0

_MIN_AGE_YEARS: Final[int] = 18
_MAX_AGE_YEARS: Final[int] = 85

# An account younger than this is still being onboarded.
_ONBOARDING_DAYS: Final[int] = 90

_EMAIL_DOMAINS: Final[tuple[str, ...]] = (
    "example.com",
    "example.net",
    "example.org",
    "mail.example",
    "inbox.example",
)

# Country to BCP 47 language tag. Every country F001 supports is covered.
_LANGUAGE_BY_COUNTRY: Final[dict[str, str]] = {
    "US": "en-US",
    "CA": "en-CA",
    "GB": "en-GB",
    "DE": "de-DE",
    "AU": "en-AU",
    "IN": "en-IN",
}
_DEFAULT_LANGUAGE: Final[str] = "en-US"


@dataclass(frozen=True, slots=True)
class CustomerGeography:
    """Lookup columns extracted from the F001 geography datasets.

    Extracting these once avoids re-reading Polars columns per batch.

    Attributes:
        city_ids: Every city identifier.
        state_ids: State identifier for each city, same order.
        country_ids: Country identifier for each city, same order.
        postal_codes: Postal code for each city, same order.
        latitudes: Latitude for each city, same order.
        longitudes: Longitude for each city, same order.
        timezones: Timezone for each city, same order.
        country_code_by_id: Country identifier to ISO alpha-2 code.
        currency_by_country_id: Country identifier to ISO 4217 currency code.
    """

    city_ids: list[int]
    state_ids: list[int]
    country_ids: list[int]
    postal_codes: list[str]
    latitudes: list[float]
    longitudes: list[float]
    timezones: list[str]
    country_code_by_id: dict[int, str]
    currency_by_country_id: dict[int, str]

    @classmethod
    def from_frames(
        cls, cities: pl.DataFrame, states: pl.DataFrame, countries: pl.DataFrame
    ) -> CustomerGeography:
        """Build the lookup from generated geography frames.

        Args:
            cities: The F001 cities dataset.
            states: The F001 states dataset, used to confirm it is populated.
            countries: The F001 countries dataset.

        Returns:
            The extracted lookup.

        Raises:
            ValueError: If any geography dataset is empty, which would leave
                customer addresses with nothing to reference.
        """
        if cities.is_empty():
            raise ValueError("cannot generate customers: the cities dataset is empty")
        if states.is_empty():
            raise ValueError("cannot generate customers: the states dataset is empty")
        if countries.is_empty():
            raise ValueError("cannot generate customers: the countries dataset is empty")

        country_ids: list[int] = countries["country_id"].to_list()
        return cls(
            city_ids=cities["city_id"].to_list(),
            state_ids=cities["state_id"].to_list(),
            country_ids=cities["country_id"].to_list(),
            postal_codes=cities["postal_code"].to_list(),
            latitudes=cities["latitude"].to_list(),
            longitudes=cities["longitude"].to_list(),
            timezones=cities["timezone"].to_list(),
            country_code_by_id=dict(
                zip(country_ids, countries["country_code"].to_list(), strict=True)
            ),
            currency_by_country_id=dict(
                zip(country_ids, countries["currency_code"].to_list(), strict=True)
            ),
        )

    def language_for_city(self, city_index: int) -> str:
        """Return the language tag for the country a city sits in.

        Args:
            city_index: Index into the city columns.

        Returns:
            A BCP 47 language tag.
        """
        code = self.country_code_by_id.get(self.country_ids[city_index], "")
        return _LANGUAGE_BY_COUNTRY.get(code, _DEFAULT_LANGUAGE)

    def currency_for_city(self, city_index: int) -> str:
        """Return the currency code for the country a city sits in.

        Args:
            city_index: Index into the city columns.

        Returns:
            An ISO 4217 currency code.
        """
        return self.currency_by_country_id.get(self.country_ids[city_index], "USD")


def assign_home_cities(
    config: CustomerConfig, geography: CustomerGeography, seed: int
) -> list[int]:
    """Assign each customer a home city.

    The result indexes into :class:`CustomerGeography`'s parallel columns. It
    is a pure function of the arguments, so the customer, address, and
    preference generators can each recompute it and agree.

    Args:
        config: Customer configuration supplying ``customer_count``.
        geography: The extracted geography lookup.
        seed: Run seed.

    Returns:
        One city index per customer, ordered by customer id.
    """
    rng = make_rng(seed, "customer_home_city")
    city_count = len(geography.city_ids)
    return [rng.randrange(city_count) for _ in range(config.customer_count)]


def customer_id_batches(config: CustomerConfig) -> Iterator[range]:
    """Yield contiguous customer id ranges of at most ``batch_size``.

    Args:
        config: Customer configuration.

    Yields:
        Ranges of customer ids, starting at 1.
    """
    start = 1
    end = config.customer_count + 1
    while start < end:
        stop = min(start + config.batch_size, end)
        yield range(start, stop)
        start = stop


def _unique_value(candidate: str, seen: set[str], fallback: str) -> str:
    """Return a value not already in ``seen``.

    Args:
        candidate: Preferred value.
        seen: Values already used. Updated in place with the returned value.
        fallback: Guaranteed-unique value used if ``candidate`` collides.

    Returns:
        The accepted value.
    """
    value = candidate if candidate not in seen else fallback
    seen.add(value)
    return value


def _registration_date(rng: random.Random, config: CustomerConfig) -> date:
    """Sample a registration date within the configured window.

    Args:
        rng: Random source.
        config: Customer configuration.

    Returns:
        A date between the earliest allowed date and the reference date.
    """
    span_days = (config.reference_date - config.earliest_registration_date).days
    return config.earliest_registration_date + timedelta(days=rng.randrange(span_days + 1))


def _date_of_birth(rng: random.Random, config: CustomerConfig) -> date:
    """Sample a date of birth for an adult customer.

    Args:
        rng: Random source.
        config: Customer configuration, supplying the reference date.

    Returns:
        A date between 85 and 18 years before the reference date.
    """
    age_days = rng.randrange(_MIN_AGE_YEARS * 365, _MAX_AGE_YEARS * 365)
    return config.reference_date - timedelta(days=age_days)


def _risk_score(rng: random.Random) -> float:
    """Sample a risk score from a clamped normal distribution.

    Args:
        rng: Random source.

    Returns:
        A score between 0 and 100, rounded to two decimals.
    """
    raw = rng.gauss(_RISK_MEAN, _RISK_STDDEV)
    return round(min(_RISK_MAX, max(_RISK_MIN, raw)), 2)


def lifecycle_stage(status: CustomerStatus, registration: date, reference: date) -> LifecycleStage:
    """Derive the lifecycle stage from account status and tenure.

    Deriving rather than sampling keeps the stage consistent with the status
    reported next to it: a closed account is never reported as onboarding.

    Args:
        status: The account status.
        registration: When the customer registered.
        reference: The dataset's as-of date.

    Returns:
        The lifecycle stage.
    """
    if status is CustomerStatus.CLOSED:
        return LifecycleStage.CHURNED
    if status is CustomerStatus.SUSPENDED:
        return LifecycleStage.AT_RISK
    if status is CustomerStatus.INACTIVE:
        return LifecycleStage.DORMANT
    if (reference - registration).days <= _ONBOARDING_DAYS:
        return LifecycleStage.ONBOARDING
    return LifecycleStage.ACTIVE


def iter_customer_batches(
    config: CustomerConfig,
    geography: CustomerGeography,
    seed: int,
    locale: str = "en_US",
) -> Iterator[pl.DataFrame]:
    """Yield customers in batches of ``config.batch_size``.

    Args:
        config: Customer configuration.
        geography: The extracted geography lookup.
        seed: Run seed.
        locale: Faker locale for names.

    Yields:
        Frames matching the customers schema. The final batch may be smaller.
    """
    rng = make_rng(seed, "customers")
    faker = make_faker(seed, "customers", locale)
    home_cities = assign_home_cities(config, geography, seed)

    seen_emails: set[str] = set()
    seen_phones: set[str] = set()

    for id_range in customer_id_batches(config):
        customer_ids: list[int] = []
        numbers: list[str] = []
        first_names: list[str] = []
        last_names: list[str] = []
        full_names: list[str] = []
        genders: list[str] = []
        births: list[date] = []
        emails: list[str] = []
        phones: list[str] = []
        registrations: list[date] = []
        statuses: list[str] = []
        email_verified: list[bool] = []
        mobile_verified: list[bool] = []
        languages: list[str] = []
        currencies: list[str] = []
        segments: list[str] = []
        sources: list[str] = []
        channels: list[str] = []
        risk_scores: list[float] = []
        stages: list[str] = []
        created: list[datetime] = []
        updated: list[datetime] = []

        for customer_id in id_range:
            city_index = home_cities[customer_id - 1]
            gender = rng.choices(_GENDERS, weights=_GENDER_WEIGHTS, k=1)[0]
            first = (
                faker.first_name_female() if gender is Gender.FEMALE else faker.first_name_male()
            )
            last = faker.last_name()
            status = rng.choices(_STATUSES, weights=_STATUS_WEIGHTS, k=1)[0]
            registered = _registration_date(rng, config)

            local_part = f"{first}.{last}".lower().replace(" ", "").replace("'", "")
            domain = rng.choice(_EMAIL_DOMAINS)
            email = _unique_value(
                f"{local_part}@{domain}",
                seen_emails,
                f"{local_part}.{customer_id}@{domain}",
            )
            phone = _unique_value(
                faker.numerify("+1-###-###-####"),
                seen_phones,
                f"+1-999-{customer_id // 10_000:03d}-{customer_id % 10_000:04d}",
            )

            registered_at = datetime.combine(
                registered, time(rng.randrange(24), rng.randrange(60), rng.randrange(60))
            )

            customer_ids.append(customer_id)
            numbers.append(format_code("CUST", customer_id, width=8))
            first_names.append(first)
            last_names.append(last)
            full_names.append(f"{first} {last}")
            genders.append(str(gender))
            births.append(_date_of_birth(rng, config))
            emails.append(email)
            phones.append(phone)
            registrations.append(registered)
            statuses.append(str(status))
            email_verified.append(rng.random() < _EMAIL_VERIFIED_RATE)
            mobile_verified.append(rng.random() < _MOBILE_VERIFIED_RATE)
            languages.append(geography.language_for_city(city_index))
            currencies.append(geography.currency_for_city(city_index))
            segments.append(str(rng.choices(_SEGMENTS, weights=_SEGMENT_WEIGHTS, k=1)[0]))
            sources.append(str(rng.choices(_SOURCES, weights=_SOURCE_WEIGHTS, k=1)[0]))
            channels.append(str(rng.choices(_CHANNELS, weights=_CHANNEL_WEIGHTS, k=1)[0]))
            risk_scores.append(_risk_score(rng))
            stages.append(str(lifecycle_stage(status, registered, config.reference_date)))
            created.append(registered_at)
            updated.append(registered_at + timedelta(days=rng.randrange(0, 400)))

        yield build_frame(
            CUSTOMERS,
            {
                "customer_id": customer_ids,
                "customer_number": numbers,
                "first_name": first_names,
                "last_name": last_names,
                "full_name": full_names,
                "gender": genders,
                "date_of_birth": births,
                "email": emails,
                "phone": phones,
                "registration_date": registrations,
                "status": statuses,
                "email_verified": email_verified,
                "mobile_verified": mobile_verified,
                "preferred_language": languages,
                "preferred_currency": currencies,
                "customer_segment": segments,
                "registration_source": sources,
                "acquisition_channel": channels,
                "risk_score": risk_scores,
                "lifecycle_stage": stages,
                "created_at": created,
                "updated_at": updated,
            },
        )


def generate_customers(
    config: CustomerConfig,
    geography: CustomerGeography,
    seed: int,
    locale: str = "en_US",
) -> pl.DataFrame:
    """Generate the complete customers dataset.

    Args:
        config: Customer configuration.
        geography: The extracted geography lookup.
        seed: Run seed.
        locale: Faker locale for names.

    Returns:
        ``config.customer_count`` rows keyed by sequential ``customer_id``.
    """
    batches = list(iter_customer_batches(config, geography, seed, locale))
    return pl.concat(batches, how="vertical")
