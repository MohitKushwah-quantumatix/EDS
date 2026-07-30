"""Schemas for the product catalog master datasets.

``categories`` is self-referencing: a level-1 category has a null parent, and
products attach only to leaf categories.
"""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = ["BRANDS", "CATALOG_DATASETS", "CATEGORIES", "PRODUCTS"]

CATEGORIES = Dataset(
    name="categories",
    columns={
        "category_id": pl.Int64(),
        "parent_category_id": pl.Int64(),
        "category_code": pl.String(),
        "category_name": pl.String(),
        "category_path": pl.String(),
        "level": pl.Int64(),
        "is_leaf": pl.Boolean(),
    },
    primary_key="category_id",
    foreign_keys=(ForeignKey("parent_category_id", "categories", "category_id", nullable=True),),
    unique_columns=("category_code", "category_path"),
)

BRANDS = Dataset(
    name="brands",
    columns={
        "brand_id": pl.Int64(),
        "brand_code": pl.String(),
        "brand_name": pl.String(),
        "country_id": pl.Int64(),
        "is_premium": pl.Boolean(),
    },
    primary_key="brand_id",
    foreign_keys=(ForeignKey("country_id", "countries", "country_id"),),
    unique_columns=("brand_code", "brand_name"),
)

PRODUCTS = Dataset(
    name="products",
    columns={
        "product_id": pl.Int64(),
        "sku": pl.String(),
        "product_name": pl.String(),
        "category_id": pl.Int64(),
        "brand_id": pl.Int64(),
        "supplier_id": pl.Int64(),
        "tax_code_id": pl.Int64(),
        "unit_of_measure": pl.String(),
        "unit_cost": pl.Float64(),
        "list_price": pl.Float64(),
        "currency_code": pl.String(),
        "weight_kg": pl.Float64(),
        "length_cm": pl.Float64(),
        "width_cm": pl.Float64(),
        "height_cm": pl.Float64(),
        "status": pl.String(),
        "is_returnable": pl.Boolean(),
    },
    primary_key="product_id",
    foreign_keys=(
        ForeignKey("category_id", "categories", "category_id"),
        ForeignKey("brand_id", "brands", "brand_id"),
        ForeignKey("supplier_id", "suppliers", "supplier_id"),
        ForeignKey("tax_code_id", "tax_codes", "tax_code_id"),
    ),
    unique_columns=("sku",),
)

CATALOG_DATASETS: tuple[Dataset, ...] = (CATEGORIES, BRANDS, PRODUCTS)
