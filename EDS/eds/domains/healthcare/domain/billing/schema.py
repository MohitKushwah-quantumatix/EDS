"""Schemas for the billing datasets.

Billing data references the encounter and patient datasets through
foreign keys.
"""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = [
    "BILLING",
    "CLAIMS",
    "BILLING_DATASETS",
    "billing_dataset_by_name",
    "billing_dataset_names",
]

BILLING = Dataset(
    name="billing",
    columns={
        "billing_id": pl.Int64(),
        "billing_number": pl.String(),
        "encounter_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "provider_id": pl.Int64(),
        "billing_code_id": pl.Int64(),
        "charge_amount": pl.Float64(),
        "discount_amount": pl.Float64(),
        "tax_amount": pl.Float64(),
        "total_amount": pl.Float64(),
        "billing_date": pl.Date(),
        "status": pl.String(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="billing_id",
    foreign_keys=(
        ForeignKey("encounter_id", "encounters", "encounter_id"),
        ForeignKey("patient_id", "patients", "patient_id"),
        ForeignKey("provider_id", "providers", "provider_id"),
        ForeignKey("billing_code_id", "billing_codes", "billing_code_id"),
    ),
    unique_columns=("billing_number",),
)

CLAIMS = Dataset(
    name="claims",
    columns={
        "claim_id": pl.Int64(),
        "claim_number": pl.String(),
        "billing_id": pl.Int64(),
        "insurance_plan_id": pl.Int64(),
        "patient_id": pl.Int64(),
        "claim_amount": pl.Float64(),
        "approved_amount": pl.Float64(),
        "denied_amount": pl.Float64(),
        "status": pl.String(),
        "submitted_date": pl.Date(),
        "processed_date": pl.Date(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="claim_id",
    foreign_keys=(
        ForeignKey("billing_id", "billing", "billing_id"),
        ForeignKey("insurance_plan_id", "insurance_plans", "insurance_plan_id"),
        ForeignKey("patient_id", "patients", "patient_id"),
    ),
    unique_columns=("claim_number",),
)

BILLING_DATASETS: tuple[Dataset, ...] = (
    BILLING,
    CLAIMS,
)

_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in BILLING_DATASETS}


def billing_dataset_names() -> tuple[str, ...]:
    """Return every billing dataset name in dependency order."""
    return tuple(_BY_NAME)


def billing_dataset_by_name(name: str) -> Dataset:
    """Look up a billing dataset declaration by name."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown billing dataset: {name!r}. Known datasets: {billing_dataset_names()}"
        ) from None
