"""Schemas for the supply chain master datasets."""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = ["SUPPLIERS", "SUPPLY_CHAIN_DATASETS", "WAREHOUSES"]

SUPPLIERS = Dataset(
    name="suppliers",
    columns={
        "supplier_id": pl.Int64(),
        "supplier_code": pl.String(),
        "supplier_name": pl.String(),
        "country_id": pl.Int64(),
        "city_id": pl.Int64(),
        "tier": pl.String(),
        "contact_email": pl.String(),
        "contact_phone": pl.String(),
        "lead_time_days": pl.Int64(),
        "reliability_score": pl.Float64(),
        "is_active": pl.Boolean(),
    },
    primary_key="supplier_id",
    foreign_keys=(
        ForeignKey("country_id", "countries", "country_id"),
        ForeignKey("city_id", "cities", "city_id"),
    ),
    unique_columns=("supplier_code",),
)

WAREHOUSES = Dataset(
    name="warehouses",
    columns={
        "warehouse_id": pl.Int64(),
        "warehouse_code": pl.String(),
        "warehouse_name": pl.String(),
        "city_id": pl.Int64(),
        "state_id": pl.Int64(),
        "country_id": pl.Int64(),
        "capacity_units": pl.Int64(),
        "status": pl.String(),
        "latitude": pl.Float64(),
        "longitude": pl.Float64(),
    },
    primary_key="warehouse_id",
    foreign_keys=(
        ForeignKey("city_id", "cities", "city_id"),
        ForeignKey("state_id", "states", "state_id"),
        ForeignKey("country_id", "countries", "country_id"),
    ),
    unique_columns=("warehouse_code",),
)

SUPPLY_CHAIN_DATASETS: tuple[Dataset, ...] = (SUPPLIERS, WAREHOUSES)
