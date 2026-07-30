"""Generator for the order lines dataset.

An order line is the cart item the customer actually paid for. Lines come
only from **active** cart items - those with no ``removed_at`` - belonging to
the order's own cart, which is the same rule F005 applies when it computes the
checkout subtotal. Because both sides use that rule, the lines reconcile with
the order's copied totals rather than needing to be forced to agree.

Nothing is sampled here: the product, quantity, and price all come from the
cart item, in line with ADR-001 and ADR-009. Generation is a single Polars
join, not a row loop.
"""

from __future__ import annotations

from collections.abc import Iterator

import polars as pl

from eds.config import OrderConfig
from eds.core.frames import empty_frame
from eds.domains.retail.domain.commerce.schema import ORDER_LINES

__all__ = ["active_cart_items", "generate_order_lines", "iter_order_line_batches"]


def active_cart_items(cart_items: pl.DataFrame) -> pl.DataFrame:
    """Return the cart items still in the cart at checkout.

    Args:
        cart_items: The F004 cart items dataset.

    Returns:
        The rows with no ``removed_at``.
    """
    return cart_items.filter(pl.col("removed_at").is_null())


def iter_order_line_batches(
    config: OrderConfig, orders: pl.DataFrame, cart_items: pl.DataFrame
) -> Iterator[pl.DataFrame]:
    """Yield order lines in batches.

    Args:
        config: Order configuration.
        orders: The generated orders dataset.
        cart_items: The F004 cart items dataset.

    Yields:
        Frames matching the order lines schema.
    """
    if orders.is_empty():
        return

    built = (
        orders.select("order_id", "cart_id", pl.col("created_at").alias("order_created_at"))
        .join(
            active_cart_items(cart_items).select(
                "cart_id", "cart_item_id", "product_id", "quantity", "unit_price"
            ),
            on="cart_id",
            how="inner",
        )
        # Sort by the cart item so the same input always numbers lines the
        # same way, whatever order the join happened to produce.
        .sort("order_id", "cart_item_id")
        .with_columns(
            pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("order_line_id"),
            (pl.col("quantity") * pl.col("unit_price")).round(2).alias("line_total"),
            pl.col("order_created_at").alias("created_at"),
        )
        .select(
            "order_line_id",
            "order_id",
            "product_id",
            "quantity",
            "unit_price",
            "line_total",
            "created_at",
        )
    )

    for offset in range(0, built.height, config.batch_size):
        yield built.slice(offset, config.batch_size)


def generate_order_lines(
    config: OrderConfig, orders: pl.DataFrame, cart_items: pl.DataFrame
) -> pl.DataFrame:
    """Generate the complete order lines dataset.

    An order whose cart items were all removed has no lines. Its subtotal is
    zero, so the reconciliation still holds.

    Args:
        config: Order configuration.
        orders: The generated orders dataset.
        cart_items: The F004 cart items dataset.

    Returns:
        One row per active cart item of every ordered cart, keyed by
        sequential ``order_line_id``.
    """
    batches = list(iter_order_line_batches(config, orders, cart_items))
    return pl.concat(batches, how="vertical") if batches else empty_frame(ORDER_LINES)
