"""Generator for the customer preferences dataset.

Exactly one preference record is produced per customer. Language and currency
are taken from the customer's home city so they match the customer record, and
the timezone comes from that same city.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

import polars as pl

from eds.config import CustomerConfig
from eds.core.frames import build_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.customer.schema import CUSTOMER_PREFERENCES
from eds.domains.retail.generators.customers.customer_generator import (
    CustomerGeography,
    assign_home_cities,
    customer_id_batches,
)

__all__ = ["generate_preferences", "iter_preference_batches"]

# Opt-in rates: email is the broadest channel, SMS the most guarded.
_EMAIL_OPT_IN_RATE: Final[float] = 0.68
_SMS_OPT_IN_RATE: Final[float] = 0.41
_PUSH_OPT_IN_RATE: Final[float] = 0.54


def iter_preference_batches(
    config: CustomerConfig, geography: CustomerGeography, seed: int
) -> Iterator[pl.DataFrame]:
    """Yield customer preferences in batches.

    Args:
        config: Customer configuration.
        geography: The extracted geography lookup.
        seed: Run seed.

    Yields:
        Frames matching the customer preferences schema.
    """
    rng = make_rng(seed, "customer_preferences")
    home_cities = assign_home_cities(config, geography, seed)

    for id_range in customer_id_batches(config):
        preference_ids: list[int] = []
        customer_ids: list[int] = []
        email_opt_in: list[bool] = []
        sms_opt_in: list[bool] = []
        push_opt_in: list[bool] = []
        languages: list[str] = []
        currencies: list[str] = []
        timezones: list[str] = []

        for customer_id in id_range:
            city_index = home_cities[customer_id - 1]

            # One preference record per customer, so the identifier can share
            # the customer id rather than needing its own counter.
            preference_ids.append(customer_id)
            customer_ids.append(customer_id)
            email_opt_in.append(rng.random() < _EMAIL_OPT_IN_RATE)
            sms_opt_in.append(rng.random() < _SMS_OPT_IN_RATE)
            push_opt_in.append(rng.random() < _PUSH_OPT_IN_RATE)
            languages.append(geography.language_for_city(city_index))
            currencies.append(geography.currency_for_city(city_index))
            timezones.append(geography.timezones[city_index])

        yield build_frame(
            CUSTOMER_PREFERENCES,
            {
                "preference_id": preference_ids,
                "customer_id": customer_ids,
                "email_opt_in": email_opt_in,
                "sms_opt_in": sms_opt_in,
                "push_opt_in": push_opt_in,
                "preferred_language": languages,
                "preferred_currency": currencies,
                "timezone": timezones,
            },
        )


def generate_preferences(
    config: CustomerConfig, geography: CustomerGeography, seed: int
) -> pl.DataFrame:
    """Generate the complete customer preferences dataset.

    Args:
        config: Customer configuration.
        geography: The extracted geography lookup.
        seed: Run seed.

    Returns:
        Exactly one row per customer.
    """
    batches = list(iter_preference_batches(config, geography, seed))
    return pl.concat(batches, how="vertical")
