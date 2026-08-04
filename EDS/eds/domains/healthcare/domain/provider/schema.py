"""Schemas for the provider master datasets.

Provider data references the F001 master data datasets through
``department_id`` and ``specialty_id``. Those foreign keys are declared
here in the same way F001 declares its own, so the shared referential
validator resolves them without any provider-specific code.
"""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = [
    "PROVIDERS",
    "PROVIDER_DEPARTMENTS",
    "PROVIDER_SPECIALTIES",
    "PROVIDER_DATASETS",
    "provider_dataset_by_name",
    "provider_dataset_names",
]

PROVIDERS = Dataset(
    name="providers",
    columns={
        "provider_id": pl.Int64(),
        "provider_number": pl.String(),
        "first_name": pl.String(),
        "last_name": pl.String(),
        "full_name": pl.String(),
        "provider_type": pl.String(),
        "specialty_id": pl.Int64(),
        "department_id": pl.Int64(),
        "license_number": pl.String(),
        "status": pl.String(),
        "hire_date": pl.Date(),
        "termination_date": pl.Date(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="provider_id",
    unique_columns=("provider_number", "license_number"),
)

PROVIDER_DEPARTMENTS = Dataset(
    name="provider_departments",
    columns={
        "provider_department_id": pl.Int64(),
        "provider_id": pl.Int64(),
        "department_id": pl.Int64(),
        "role": pl.String(),
        "is_primary": pl.Boolean(),
        "start_date": pl.Date(),
        "end_date": pl.Date(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="provider_department_id",
    foreign_keys=(
        ForeignKey("provider_id", "providers", "provider_id"),
        ForeignKey("department_id", "departments", "department_id"),
    ),
)

PROVIDER_SPECIALTIES = Dataset(
    name="provider_specialties",
    columns={
        "provider_specialty_id": pl.Int64(),
        "provider_id": pl.Int64(),
        "specialty_id": pl.Int64(),
        "certification_date": pl.Date(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="provider_specialty_id",
    foreign_keys=(
        ForeignKey("provider_id", "providers", "provider_id"),
        ForeignKey("specialty_id", "specialties", "specialty_id"),
    ),
)

PROVIDER_DATASETS: tuple[Dataset, ...] = (
    PROVIDERS,
    PROVIDER_DEPARTMENTS,
    PROVIDER_SPECIALTIES,
)

_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in PROVIDER_DATASETS}


def provider_dataset_names() -> tuple[str, ...]:
    """Return every provider dataset name in dependency order."""
    return tuple(_BY_NAME)


def provider_dataset_by_name(name: str) -> Dataset:
    """Look up a provider dataset declaration by name."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown provider dataset: {name!r}. Known datasets: {provider_dataset_names()}"
        ) from None
