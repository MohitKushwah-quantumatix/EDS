"""Generator for the inventory master dataset.

Inventory is the product-to-warehouse stocking matrix. Rather than stocking
every product in every warehouse - which would multiply the row count by the
warehouse count and is not how real networks operate - each product is stocked
in a deterministic sample of ``warehouses_per_product`` warehouses.

Only warehouses that are operationally usable hold stock; a closed warehouse
with inventory would be a business rule violation.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from typing import Final

import polars as pl

from eds.config import MasterDataConfig
from eds.core.frames import build_frame, empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.enums import WarehouseStatus
from eds.domains.retail.domain.inventory.schema import INVENTORY

__all__ = ["generate_inventory", "iter_inventory_batches", "stockable_warehouse_ids"]

_STOCKABLE_STATUSES: Final[frozenset[str]] = frozenset(
    {str(WarehouseStatus.ACTIVE), str(WarehouseStatus.MAINTENANCE)}
)

# Quantity on hand is drawn from a wide band: slow movers sit near zero,
# fast movers hold deep stock.
_QUANTITY_RANGE: Final[tuple[int, int]] = (0, 5_000)
_RESERVED_FRACTION_MAX: Final[float] = 0.25
_REORDER_POINT_RANGE: Final[tuple[int, int]] = (10, 500)
_REORDER_QUANTITY_MULTIPLIER: Final[tuple[float, float]] = (1.5, 4.0)


def stockable_warehouse_ids(warehouses: pl.DataFrame) -> list[int]:
    """Return the ids of warehouses that may hold stock.

    Args:
        warehouses: The generated warehouses dataset.

    Returns:
        Warehouse ids whose status is active or under maintenance, in dataset
        order.
    """
    stockable = warehouses.filter(pl.col("status").is_in(list(_STOCKABLE_STATUSES)))
    ids: list[int] = stockable["warehouse_id"].to_list()
    return ids


def _sample_warehouses(rng: random.Random, warehouse_ids: list[int], sample_size: int) -> list[int]:
    """Pick the warehouses a single product is stocked in.

    Args:
        rng: Random source.
        warehouse_ids: Warehouses eligible to hold stock.
        sample_size: How many to pick.

    Returns:
        A sample without replacement, or every eligible warehouse when
        ``sample_size`` meets or exceeds the pool size.
    """
    if sample_size >= len(warehouse_ids):
        return list(warehouse_ids)
    return rng.sample(warehouse_ids, sample_size)


def iter_inventory_batches(
    config: MasterDataConfig,
    products: pl.DataFrame,
    warehouses: pl.DataFrame,
    seed: int,
) -> Iterator[pl.DataFrame]:
    """Yield inventory rows in batches of roughly ``config.batch_size``.

    Args:
        config: Master data configuration.
        products: The generated products dataset.
        warehouses: The generated warehouses dataset.
        seed: Run seed.

    Yields:
        Frames matching the inventory schema.

    Raises:
        ValueError: If no warehouse is eligible to hold stock.
    """
    warehouse_ids = stockable_warehouse_ids(warehouses)
    if not warehouse_ids:
        raise ValueError(
            "cannot generate inventory: no warehouse has a stockable status "
            f"({sorted(_STOCKABLE_STATUSES)})"
        )

    rng = make_rng(seed, "inventory")
    product_ids: list[int] = products["product_id"].to_list()
    product_costs: list[float] = products["unit_cost"].to_list()
    sample_size = min(config.warehouses_per_product, len(warehouse_ids))

    inventory_ids: list[int] = []
    batch_product_ids: list[int] = []
    batch_warehouse_ids: list[int] = []
    on_hand: list[int] = []
    reserved: list[int] = []
    reorder_points: list[int] = []
    reorder_quantities: list[int] = []
    unit_costs: list[float] = []

    next_inventory_id = 1
    for product_id, unit_cost in zip(product_ids, product_costs, strict=True):
        for warehouse_id in _sample_warehouses(rng, warehouse_ids, sample_size):
            quantity = rng.randint(*_QUANTITY_RANGE)
            reorder_point = rng.randint(*_REORDER_POINT_RANGE)
            multiplier = rng.uniform(*_REORDER_QUANTITY_MULTIPLIER)

            inventory_ids.append(next_inventory_id)
            batch_product_ids.append(product_id)
            batch_warehouse_ids.append(warehouse_id)
            on_hand.append(quantity)
            reserved.append(int(quantity * rng.uniform(0.0, _RESERVED_FRACTION_MAX)))
            reorder_points.append(reorder_point)
            reorder_quantities.append(int(reorder_point * multiplier))
            unit_costs.append(unit_cost)
            next_inventory_id += 1

        if len(inventory_ids) >= config.batch_size:
            yield build_frame(
                INVENTORY,
                {
                    "inventory_id": inventory_ids,
                    "product_id": batch_product_ids,
                    "warehouse_id": batch_warehouse_ids,
                    "quantity_on_hand": on_hand,
                    "quantity_reserved": reserved,
                    "reorder_point": reorder_points,
                    "reorder_quantity": reorder_quantities,
                    "unit_cost": unit_costs,
                },
            )
            inventory_ids, batch_product_ids, batch_warehouse_ids = [], [], []
            on_hand, reserved, reorder_points = [], [], []
            reorder_quantities, unit_costs = [], []

    if inventory_ids:
        yield build_frame(
            INVENTORY,
            {
                "inventory_id": inventory_ids,
                "product_id": batch_product_ids,
                "warehouse_id": batch_warehouse_ids,
                "quantity_on_hand": on_hand,
                "quantity_reserved": reserved,
                "reorder_point": reorder_points,
                "reorder_quantity": reorder_quantities,
                "unit_cost": unit_costs,
            },
        )


def generate_inventory(
    config: MasterDataConfig,
    products: pl.DataFrame,
    warehouses: pl.DataFrame,
    seed: int,
) -> pl.DataFrame:
    """Generate the complete inventory dataset.

    Args:
        config: Master data configuration.
        products: The generated products dataset.
        warehouses: The generated warehouses dataset.
        seed: Run seed.

    Returns:
        One row per stocked product and warehouse pair.

    Raises:
        ValueError: If no warehouse is eligible to hold stock.
    """
    batches = list(iter_inventory_batches(config, products, warehouses, seed))
    return pl.concat(batches, how="vertical") if batches else empty_frame(INVENTORY)
