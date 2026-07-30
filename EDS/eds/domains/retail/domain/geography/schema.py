"""Schemas for the geography master datasets.

Postal codes are carried as a column on ``cities`` rather than as a separate
dataset, matching the F001 output list.
"""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = ["CITIES", "COUNTRIES", "GEOGRAPHY_DATASETS", "STATES"]

COUNTRIES = Dataset(
    name="countries",
    columns={
        "country_id": pl.Int64(),
        "country_code": pl.String(),
        "country_code_3": pl.String(),
        "country_name": pl.String(),
        "currency_code": pl.String(),
        "phone_code": pl.String(),
        "region": pl.String(),
    },
    primary_key="country_id",
    unique_columns=("country_code", "country_code_3", "country_name"),
)

STATES = Dataset(
    name="states",
    columns={
        "state_id": pl.Int64(),
        "country_id": pl.Int64(),
        "state_code": pl.String(),
        "state_name": pl.String(),
    },
    primary_key="state_id",
    foreign_keys=(ForeignKey("country_id", "countries", "country_id"),),
)

CITIES = Dataset(
    name="cities",
    columns={
        "city_id": pl.Int64(),
        "state_id": pl.Int64(),
        "country_id": pl.Int64(),
        "city_name": pl.String(),
        "postal_code": pl.String(),
        "latitude": pl.Float64(),
        "longitude": pl.Float64(),
        "timezone": pl.String(),
    },
    primary_key="city_id",
    foreign_keys=(
        ForeignKey("state_id", "states", "state_id"),
        ForeignKey("country_id", "countries", "country_id"),
    ),
)

GEOGRAPHY_DATASETS: tuple[Dataset, ...] = (COUNTRIES, STATES, CITIES)
