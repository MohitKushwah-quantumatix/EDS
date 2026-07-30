"""Generator for the order status history dataset.

Under ADR-010 an order's progression lives in its own dataset rather than in a
field that gets overwritten, and under ADR-012 the order document itself is
immutable. This generator produces that progression.

Every order is ``CREATED``. Most go on to ``CONFIRMED``, and most of those to
``PROCESSING``. An order that stops early is complete data, not missing data -
the later stages belong to features that do not exist yet.

The random draws are taken as whole vectors up front and then attached as
columns, so the dataset is built with Polars expressions rather than a
row-by-row loop while staying reproducible from the seed.
"""

from __future__ import annotations

from collections.abc import Iterator

import polars as pl

from eds.config import OrderConfig
from eds.core.frames import empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.commerce.enums import ORDER_LIFECYCLE, OrderStatus
from eds.domains.retail.domain.commerce.schema import ORDER_STATUS_HISTORY

__all__ = [
    "generate_order_status_history",
    "iter_order_status_batches",
    "lifecycle_position",
]


def _stage_frame(
    orders: pl.DataFrame, status: OrderStatus, sequence: int, timestamps: pl.Expr
) -> pl.DataFrame:
    """Build one lifecycle stage for a set of orders.

    Args:
        orders: Orders that reached this stage.
        status: The stage being recorded.
        sequence: Position of the stage in the order's history.
        timestamps: Expression producing the moment the stage was reached.

    Returns:
        A frame of ``order_id``, ``status``, ``sequence``, ``status_timestamp``.
    """
    return orders.select(
        pl.col("order_id"),
        pl.lit(str(status)).alias("status"),
        pl.lit(sequence, dtype=pl.Int64).alias("sequence"),
        timestamps.alias("status_timestamp"),
    )


def iter_order_status_batches(
    config: OrderConfig, orders: pl.DataFrame, seed: int
) -> Iterator[pl.DataFrame]:
    """Yield order status history in batches.

    Args:
        config: Order configuration.
        orders: The generated orders dataset.
        seed: Run seed.

    Yields:
        Frames matching the order status history schema, ordered by order and
        then by sequence.
    """
    if orders.is_empty():
        return

    rng = make_rng(seed, "order_status_history")
    total = orders.height

    # One draw per order per decision, taken up front so the frame can be
    # assembled with expressions instead of a loop.
    advance_to_confirmed = [rng.random() for _ in range(total)]
    advance_to_processing = [rng.random() for _ in range(total)]
    confirm_delay = [
        rng.randint(config.min_confirm_minutes, config.max_confirm_minutes) for _ in range(total)
    ]
    processing_delay = [
        rng.randint(config.min_processing_minutes, config.max_processing_minutes)
        for _ in range(total)
    ]

    staged = orders.select("order_id", "created_at").with_columns(
        pl.Series("confirmed_roll", advance_to_confirmed, dtype=pl.Float64),
        pl.Series("processing_roll", advance_to_processing, dtype=pl.Float64),
        pl.Series("confirm_minutes", confirm_delay, dtype=pl.Int64),
        pl.Series("processing_minutes", processing_delay, dtype=pl.Int64),
    )
    staged = staged.with_columns(
        (pl.col("created_at") + pl.duration(minutes=pl.col("confirm_minutes"))).alias(
            "confirmed_at"
        )
    ).with_columns(
        (pl.col("confirmed_at") + pl.duration(minutes=pl.col("processing_minutes"))).alias(
            "processing_at"
        )
    )

    created = _stage_frame(staged, OrderStatus.CREATED, 1, pl.col("created_at"))

    confirmed_orders = staged.filter(pl.col("confirmed_roll") < config.confirmed_rate)
    confirmed = _stage_frame(confirmed_orders, OrderStatus.CONFIRMED, 2, pl.col("confirmed_at"))

    # Processing follows confirmation, so only confirmed orders are eligible.
    # The rate is expressed over all orders, so it is rescaled against the
    # share that were confirmed.
    eligible_share = config.confirmed_rate or 1.0
    processing_orders = confirmed_orders.filter(
        pl.col("processing_roll") < config.processing_rate / eligible_share
    )
    processing = _stage_frame(processing_orders, OrderStatus.PROCESSING, 3, pl.col("processing_at"))

    built = (
        pl.concat([created, confirmed, processing], how="vertical")
        .sort("order_id", "sequence")
        .with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("history_id"))
        .select("history_id", "order_id", "status", "sequence", "status_timestamp")
    )

    for offset in range(0, built.height, config.batch_size):
        yield built.slice(offset, config.batch_size)


def generate_order_status_history(
    config: OrderConfig, orders: pl.DataFrame, seed: int
) -> pl.DataFrame:
    """Generate the complete order status history dataset.

    Args:
        config: Order configuration.
        orders: The generated orders dataset.
        seed: Run seed.

    Returns:
        One row per lifecycle stage each order reached, keyed by sequential
        ``history_id``. Every order has at least a ``CREATED`` row.
    """
    batches = list(iter_order_status_batches(config, orders, seed))
    if not batches:
        return empty_frame(ORDER_STATUS_HISTORY)
    return pl.concat(batches, how="vertical")


def lifecycle_position(status: str) -> int:
    """Return a status's position in the lifecycle.

    Args:
        status: A lifecycle status name.

    Returns:
        The one-based position.

    Raises:
        KeyError: If the status is not part of the current lifecycle.
    """
    for position, member in enumerate(ORDER_LIFECYCLE, start=1):
        if str(member) == status:
            return position
    raise KeyError(
        f"Unknown order status: {status!r}. "
        f"Lifecycle: {tuple(str(member) for member in ORDER_LIFECYCLE)}"
    )
