"""Generator for the shipment items dataset.

A shipment item is an order line that physically moved. Split shipments and
backorders are out of scope, so every line of a shipped order goes out in that
order's single shipment, at the quantity the order recorded.

Nothing here is drawn: the items are a join between the shipments and the
order lines they cover, which is what ADR-009 asks for. The generator takes no
seed for the same reason.
"""

from __future__ import annotations

from collections.abc import Iterator

import polars as pl

from eds.config import ShipmentConfig
from eds.core.frames import empty_frame
from eds.domains.retail.domain.commerce.schema import SHIPMENT_ITEMS

__all__ = ["generate_shipment_items", "iter_shipment_item_batches"]


def iter_shipment_item_batches(
    config: ShipmentConfig, shipments: pl.DataFrame, order_lines: pl.DataFrame
) -> Iterator[pl.DataFrame]:
    """Yield shipment items in batches, one per shipped order line.

    Args:
        config: Shipment configuration.
        shipments: The generated shipments dataset.
        order_lines: The F006 order lines dataset.

    Yields:
        Frames matching the shipment items schema, ordered by shipment and
        then by order line.
    """
    if shipments.is_empty():
        return

    built = (
        shipments.select("shipment_id", "order_id", "created_at")
        .join(
            order_lines.select("order_line_id", "order_id", "product_id", "quantity"),
            on="order_id",
            how="inner",
        )
        .sort("shipment_id", "order_line_id")
        .with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("shipment_item_id"))
        .select(
            "shipment_item_id",
            "shipment_id",
            "order_line_id",
            "product_id",
            # Copied from the order line: no partial shipments in F008.
            "quantity",
            "created_at",
        )
    )

    for offset in range(0, built.height, config.batch_size):
        yield built.slice(offset, config.batch_size)


def generate_shipment_items(
    config: ShipmentConfig, shipments: pl.DataFrame, order_lines: pl.DataFrame
) -> pl.DataFrame:
    """Generate the complete shipment items dataset.

    Args:
        config: Shipment configuration.
        shipments: The generated shipments dataset.
        order_lines: The F006 order lines dataset.

    Returns:
        One row per order line of every shipped order, keyed by sequential
        ``shipment_item_id``. A shipment whose order has no lines - every item
        having been removed before checkout - carries no items.
    """
    batches = list(iter_shipment_item_batches(config, shipments, order_lines))
    return pl.concat(batches, how="vertical") if batches else empty_frame(SHIPMENT_ITEMS)
