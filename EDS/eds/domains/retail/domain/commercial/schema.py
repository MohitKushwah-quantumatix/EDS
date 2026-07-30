"""Schemas for the commercial master datasets.

These are small curated reference tables rather than randomly generated ones:
a retailer's payment methods, carriers, tax codes, and coupon programmes are
enumerable, so realism comes from a fixed catalogue.
"""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = [
    "COMMERCIAL_DATASETS",
    "COUPON_TYPES",
    "PAYMENT_METHODS",
    "RETURN_REASONS",
    "SHIPPING_METHODS",
    "TAX_CODES",
]

PAYMENT_METHODS = Dataset(
    name="payment_methods",
    columns={
        "payment_method_id": pl.Int64(),
        "method_code": pl.String(),
        "method_name": pl.String(),
        "method_type": pl.String(),
        "processing_fee_pct": pl.Float64(),
        "requires_authorization": pl.Boolean(),
        "is_active": pl.Boolean(),
    },
    primary_key="payment_method_id",
    unique_columns=("method_code",),
)

SHIPPING_METHODS = Dataset(
    name="shipping_methods",
    columns={
        "shipping_method_id": pl.Int64(),
        "method_code": pl.String(),
        "method_name": pl.String(),
        "carrier_name": pl.String(),
        "service_level": pl.String(),
        "min_transit_days": pl.Int64(),
        "max_transit_days": pl.Int64(),
        "base_cost": pl.Float64(),
        "cost_per_kg": pl.Float64(),
        "is_active": pl.Boolean(),
    },
    primary_key="shipping_method_id",
    unique_columns=("method_code",),
)

TAX_CODES = Dataset(
    name="tax_codes",
    columns={
        "tax_code_id": pl.Int64(),
        "tax_code": pl.String(),
        "tax_description": pl.String(),
        "tax_rate_pct": pl.Float64(),
        "country_id": pl.Int64(),
        "is_active": pl.Boolean(),
    },
    primary_key="tax_code_id",
    foreign_keys=(ForeignKey("country_id", "countries", "country_id"),),
)

COUPON_TYPES = Dataset(
    name="coupon_types",
    columns={
        "coupon_type_id": pl.Int64(),
        "coupon_code_prefix": pl.String(),
        "coupon_name": pl.String(),
        "discount_type": pl.String(),
        "discount_value": pl.Float64(),
        "min_order_value": pl.Float64(),
        "max_discount_value": pl.Float64(),
        "is_active": pl.Boolean(),
    },
    primary_key="coupon_type_id",
    unique_columns=("coupon_code_prefix",),
)

RETURN_REASONS = Dataset(
    name="return_reasons",
    columns={
        "return_reason_id": pl.Int64(),
        "reason_code": pl.String(),
        "reason_name": pl.String(),
        "is_customer_fault": pl.Boolean(),
        "requires_inspection": pl.Boolean(),
        "is_active": pl.Boolean(),
    },
    primary_key="return_reason_id",
    unique_columns=("reason_code", "reason_name"),
)

COMMERCIAL_DATASETS: tuple[Dataset, ...] = (
    PAYMENT_METHODS,
    SHIPPING_METHODS,
    TAX_CODES,
    COUPON_TYPES,
    RETURN_REASONS,
)
