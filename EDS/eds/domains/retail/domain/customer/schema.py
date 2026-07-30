"""Schemas for the customer master datasets.

Customer data references the F001 geography datasets through
``city_id``, ``state_id``, and ``country_id``. Those foreign keys are declared
here in the same way F001 declares its own, so the shared referential
validator resolves them without any customer-specific code.
"""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = [
    "CUSTOMERS",
    "CUSTOMER_ADDRESSES",
    "CUSTOMER_DATASETS",
    "CUSTOMER_LOYALTY",
    "CUSTOMER_PREFERENCES",
    "customer_dataset_by_name",
    "customer_dataset_names",
]

CUSTOMERS = Dataset(
    name="customers",
    columns={
        "customer_id": pl.Int64(),
        "customer_number": pl.String(),
        "first_name": pl.String(),
        "last_name": pl.String(),
        "full_name": pl.String(),
        "gender": pl.String(),
        "date_of_birth": pl.Date(),
        "email": pl.String(),
        "phone": pl.String(),
        "registration_date": pl.Date(),
        "status": pl.String(),
        "email_verified": pl.Boolean(),
        "mobile_verified": pl.Boolean(),
        "preferred_language": pl.String(),
        "preferred_currency": pl.String(),
        "customer_segment": pl.String(),
        "registration_source": pl.String(),
        "acquisition_channel": pl.String(),
        "risk_score": pl.Float64(),
        "lifecycle_stage": pl.String(),
        "created_at": pl.Datetime("us"),
        "updated_at": pl.Datetime("us"),
    },
    primary_key="customer_id",
    unique_columns=("customer_number", "email", "phone"),
)

CUSTOMER_ADDRESSES = Dataset(
    name="customer_addresses",
    columns={
        "address_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "address_type": pl.String(),
        "line1": pl.String(),
        "line2": pl.String(),
        "city_id": pl.Int64(),
        "state_id": pl.Int64(),
        "country_id": pl.Int64(),
        "postal_code": pl.String(),
        "is_primary": pl.Boolean(),
        "latitude": pl.Float64(),
        "longitude": pl.Float64(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="address_id",
    foreign_keys=(
        ForeignKey("customer_id", "customers", "customer_id"),
        ForeignKey("city_id", "cities", "city_id"),
        ForeignKey("state_id", "states", "state_id"),
        ForeignKey("country_id", "countries", "country_id"),
    ),
)

CUSTOMER_PREFERENCES = Dataset(
    name="customer_preferences",
    columns={
        "preference_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "email_opt_in": pl.Boolean(),
        "sms_opt_in": pl.Boolean(),
        "push_opt_in": pl.Boolean(),
        "preferred_language": pl.String(),
        "preferred_currency": pl.String(),
        "timezone": pl.String(),
    },
    primary_key="preference_id",
    foreign_keys=(ForeignKey("customer_id", "customers", "customer_id"),),
    unique_columns=("customer_id",),
)

CUSTOMER_LOYALTY = Dataset(
    name="customer_loyalty",
    columns={
        "loyalty_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "loyalty_number": pl.String(),
        "tier": pl.String(),
        "points_balance": pl.Int64(),
        "enrollment_date": pl.Date(),
        "status": pl.String(),
    },
    primary_key="loyalty_id",
    foreign_keys=(ForeignKey("customer_id", "customers", "customer_id"),),
    unique_columns=("customer_id", "loyalty_number"),
)

CUSTOMER_DATASETS: tuple[Dataset, ...] = (
    CUSTOMERS,
    CUSTOMER_ADDRESSES,
    CUSTOMER_PREFERENCES,
    CUSTOMER_LOYALTY,
)

_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in CUSTOMER_DATASETS}


def customer_dataset_names() -> tuple[str, ...]:
    """Return every customer dataset name in dependency order."""
    return tuple(_BY_NAME)


def customer_dataset_by_name(name: str) -> Dataset:
    """Look up a customer dataset declaration by name.

    Args:
        name: Dataset name, such as ``"customer_addresses"``.

    Returns:
        The matching dataset declaration.

    Raises:
        KeyError: If no customer dataset with that name is registered.
    """
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown customer dataset: {name!r}. Known datasets: {customer_dataset_names()}"
        ) from None
