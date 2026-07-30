"""Schema for the inventory master dataset.

Inventory is the product-to-warehouse stocking matrix. Its row count is
``product_count * warehouses_per_product``, so it is normally the largest
master dataset.
"""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = ["INVENTORY", "INVENTORY_DATASETS"]

INVENTORY = Dataset(
    name="inventory",
    columns={
        "inventory_id": pl.Int64(),
        "product_id": pl.Int64(),
        "warehouse_id": pl.Int64(),
        "quantity_on_hand": pl.Int64(),
        "quantity_reserved": pl.Int64(),
        "reorder_point": pl.Int64(),
        "reorder_quantity": pl.Int64(),
        "unit_cost": pl.Float64(),
    },
    primary_key="inventory_id",
    foreign_keys=(
        ForeignKey("product_id", "products", "product_id"),
        ForeignKey("warehouse_id", "warehouses", "warehouse_id"),
    ),
)

INVENTORY_DATASETS: tuple[Dataset, ...] = (INVENTORY,)
