"""Generator for the orders dataset.

An order is an immutable business document created from a successful
checkout. Two architecture rules shape it:

* **ADR-007.** Every financial value is *copied* from the checkout, never
  recalculated. The order carries the figures the customer agreed to.
* **ADR-012.** The document is written once. ``current_status`` is a
  denormalised convenience derived from the order's status history, not the
  source of truth, and :func:`apply_current_status` is what sets it.

Generation is expression-based rather than row-by-row: the whole dataset is
one Polars pipeline over the successful checkouts.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Final

import polars as pl

from eds.config import OrderConfig
from eds.core.frames import empty_frame
from eds.domains.retail.domain.commerce.enums import CheckoutStatus, OrderStatus
from eds.domains.retail.domain.commerce.schema import ORDERS

__all__ = [
    "ORDER_NUMBER_SEQUENCE_WIDTH",
    "apply_current_status",
    "generate_orders",
    "iter_order_batches",
    "order_number_expression",
]

#: Zero-padded width of the sequence in ``ORD-YYYYMMDD-000001``.
ORDER_NUMBER_SEQUENCE_WIDTH: Final[int] = 6


def order_number_expression(prefix: str) -> pl.Expr:
    """Build the business order number.

    The number is ``<prefix>-YYYYMMDD-NNNNNN``, where the sequence restarts
    each day and counts orders in the order they were created. Because the
    orders are sorted deterministically before this runs, the same input
    always yields the same numbers.

    Args:
        prefix: Leading token, such as ``"ORD"``.

    Returns:
        An expression producing the order number.
    """
    sequence = pl.int_range(pl.len(), dtype=pl.UInt32).over("order_date") + 1
    return pl.concat_str(
        [
            pl.lit(prefix),
            pl.col("order_date").dt.strftime("%Y%m%d"),
            sequence.cast(pl.String).str.zfill(ORDER_NUMBER_SEQUENCE_WIDTH),
        ],
        separator="-",
    ).alias("order_number")


def _successful(checkouts: pl.DataFrame) -> pl.DataFrame:
    """Select the checkouts that become orders, in a deterministic order.

    Args:
        checkouts: The F005 checkout dataset.

    Returns:
        Successful checkouts sorted by completion then identifier.
    """
    return checkouts.filter(pl.col("checkout_status") == str(CheckoutStatus.SUCCESS)).sort(
        "completed_at", "checkout_id"
    )


def iter_order_batches(config: OrderConfig, checkouts: pl.DataFrame) -> Iterator[pl.DataFrame]:
    """Yield orders in batches, one per successful checkout.

    Args:
        config: Order configuration.
        checkouts: The F005 checkout dataset.

    Yields:
        Frames matching the orders schema, with ``current_status`` set to
        ``CREATED``. :func:`apply_current_status` replaces it once the status
        history exists.
    """
    eligible = _successful(checkouts)
    if eligible.is_empty():
        return

    lead = timedelta(seconds=config.order_lead_seconds)
    built = (
        eligible.with_columns(
            (pl.col("completed_at") + lead).alias("created_at"),
        )
        .with_columns(
            pl.col("created_at").dt.date().alias("order_date"),
            pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("order_id"),
            pl.lit(str(OrderStatus.CREATED)).alias("current_status"),
        )
        .with_columns(order_number_expression(config.order_number_prefix))
        .select(
            "order_id",
            "order_number",
            "checkout_id",
            "cart_id",
            "customer_id",
            "session_id",
            "shipping_address_id",
            "billing_address_id",
            "current_status",
            # Copied verbatim from the checkout under ADR-007.
            "subtotal",
            "shipping_cost",
            "tax_amount",
            "discount_amount",
            "total_amount",
            "order_date",
            "created_at",
        )
    )

    for offset in range(0, built.height, config.batch_size):
        yield built.slice(offset, config.batch_size)


def generate_orders(config: OrderConfig, checkouts: pl.DataFrame) -> pl.DataFrame:
    """Generate the complete orders dataset.

    Args:
        config: Order configuration.
        checkouts: The F005 checkout dataset.

    Returns:
        One row per successful checkout, keyed by sequential ``order_id``,
        with ``current_status`` set to ``CREATED``.
    """
    batches = list(iter_order_batches(config, checkouts))
    return pl.concat(batches, how="vertical") if batches else empty_frame(ORDERS)


def apply_current_status(orders: pl.DataFrame, status_history: pl.DataFrame) -> pl.DataFrame:
    """Set each order's current status from its latest history row.

    ADR-012 makes the history the source of truth and ``current_status`` a
    derived convenience, so this reads the history rather than the other way
    round.

    Args:
        orders: The generated orders dataset.
        status_history: The generated order status history.

    Returns:
        The orders with ``current_status`` replaced by the status of their
        highest-sequence history row.
    """
    if orders.is_empty():
        return orders

    latest = (
        status_history.sort("order_id", "sequence")
        .group_by("order_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest_status"))
    )
    return (
        orders.join(latest, on="order_id", how="left")
        .with_columns(
            pl.col("latest_status").fill_null(pl.col("current_status")).alias("current_status")
        )
        .drop("latest_status")
        .select(orders.columns)
    )
