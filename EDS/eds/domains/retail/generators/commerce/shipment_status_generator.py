"""Generator for the shipment status history dataset.

Under ADR-010 a shipment's progression lives in its own dataset rather than in
a field that gets overwritten, and under ADR-012 the shipment document itself
is immutable. This generator produces that progression, and it owns the whole
timeline: ``shipped_at`` and ``delivered_at`` are read back off the history
rather than computed twice.

Every shipment is ``CREATED``, ``PACKED`` and ``SHIPPED``. Most go on to
``IN_TRANSIT``, and most of those to ``DELIVERED``. A shipment that stops early
is complete data, not missing data - it is simply still on its way when the
simulated window ends.

The random draws are taken as whole vectors up front and then attached as
columns, so the dataset is built with Polars expressions rather than a
row-by-row loop while staying reproducible from the seed.
"""

from __future__ import annotations

from collections.abc import Iterator

import polars as pl

from eds.config import ShipmentConfig
from eds.core.frames import empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.commerce.enums import SHIPMENT_LIFECYCLE, ShipmentStatus
from eds.domains.retail.domain.commerce.schema import SHIPMENT_STATUS_HISTORY

__all__ = [
    "generate_shipment_status_history",
    "iter_shipment_status_batches",
    "shipment_lifecycle_position",
]


def _stage_frame(
    shipments: pl.DataFrame, status: ShipmentStatus, sequence: int, timestamps: pl.Expr
) -> pl.DataFrame:
    """Build one lifecycle stage for a set of shipments.

    Args:
        shipments: Shipments that reached this stage.
        status: The stage being recorded.
        sequence: Position of the stage in the shipment's history.
        timestamps: Expression producing the moment the stage was reached.

    Returns:
        A frame of ``shipment_id``, ``status``, ``sequence``,
        ``status_timestamp``.
    """
    return shipments.select(
        pl.col("shipment_id"),
        pl.lit(str(status)).alias("status"),
        pl.lit(sequence, dtype=pl.Int64).alias("sequence"),
        timestamps.alias("status_timestamp"),
    )


def iter_shipment_status_batches(
    config: ShipmentConfig, shipments: pl.DataFrame, seed: int
) -> Iterator[pl.DataFrame]:
    """Yield shipment status history in batches.

    Args:
        config: Shipment configuration.
        shipments: The generated shipments dataset.
        seed: Run seed.

    Yields:
        Frames matching the shipment status history schema, ordered by
        shipment and then by sequence.
    """
    if shipments.is_empty():
        return

    rng = make_rng(seed, "shipment_status_history")
    total = shipments.height

    # One draw per shipment per decision, taken up front so the frame can be
    # assembled with expressions instead of a loop.
    progress_roll = [rng.random() for _ in range(total)]
    pack_delay = [
        rng.randint(config.min_pack_minutes, config.max_pack_minutes) for _ in range(total)
    ]
    dispatch_delay = [
        rng.randint(config.min_dispatch_minutes, config.max_dispatch_minutes) for _ in range(total)
    ]
    transit_delay = [
        rng.randint(config.min_transit_hours, config.max_transit_hours) for _ in range(total)
    ]
    delivery_delay = [
        rng.randint(config.min_delivery_hours, config.max_delivery_hours) for _ in range(total)
    ]

    staged = (
        shipments.select("shipment_id", "created_at")
        .with_columns(
            pl.Series("progress_roll", progress_roll, dtype=pl.Float64),
            pl.Series("pack_minutes", pack_delay, dtype=pl.Int64),
            pl.Series("dispatch_minutes", dispatch_delay, dtype=pl.Int64),
            pl.Series("transit_hours", transit_delay, dtype=pl.Int64),
            pl.Series("delivery_hours", delivery_delay, dtype=pl.Int64),
        )
        .with_columns(
            (pl.col("created_at") + pl.duration(minutes=pl.col("pack_minutes"))).alias("packed_at")
        )
        .with_columns(
            (pl.col("packed_at") + pl.duration(minutes=pl.col("dispatch_minutes"))).alias(
                "shipped_at"
            )
        )
        .with_columns(
            (pl.col("shipped_at") + pl.duration(hours=pl.col("transit_hours"))).alias(
                "in_transit_at"
            )
        )
        .with_columns(
            (pl.col("in_transit_at") + pl.duration(hours=pl.col("delivery_hours"))).alias(
                "delivered_at"
            )
        )
    )

    # The three completion shares are validated to sum to one, so every
    # shipment clears the first three stages and the cuts only decide how far
    # past them it got.
    in_transit_cut = config.delivered_rate + config.in_transit_rate

    created = _stage_frame(staged, ShipmentStatus.CREATED, 1, pl.col("created_at"))
    packed = _stage_frame(staged, ShipmentStatus.PACKED, 2, pl.col("packed_at"))
    shipped = _stage_frame(staged, ShipmentStatus.SHIPPED, 3, pl.col("shipped_at"))

    in_transit_shipments = staged.filter(pl.col("progress_roll") < in_transit_cut)
    in_transit = _stage_frame(
        in_transit_shipments, ShipmentStatus.IN_TRANSIT, 4, pl.col("in_transit_at")
    )

    # Delivery follows being in transit, so only those shipments are eligible.
    delivered_shipments = in_transit_shipments.filter(
        pl.col("progress_roll") < config.delivered_rate
    )
    delivered = _stage_frame(
        delivered_shipments, ShipmentStatus.DELIVERED, 5, pl.col("delivered_at")
    )

    built = (
        pl.concat([created, packed, shipped, in_transit, delivered], how="vertical")
        .sort("shipment_id", "sequence")
        .with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("history_id"))
        .select("history_id", "shipment_id", "status", "sequence", "status_timestamp")
    )

    for offset in range(0, built.height, config.batch_size):
        yield built.slice(offset, config.batch_size)


def generate_shipment_status_history(
    config: ShipmentConfig, shipments: pl.DataFrame, seed: int
) -> pl.DataFrame:
    """Generate the complete shipment status history dataset.

    Args:
        config: Shipment configuration.
        shipments: The generated shipments dataset.
        seed: Run seed.

    Returns:
        One row per lifecycle stage each shipment reached, keyed by sequential
        ``history_id``. Every shipment reaches at least ``SHIPPED``.
    """
    batches = list(iter_shipment_status_batches(config, shipments, seed))
    if not batches:
        return empty_frame(SHIPMENT_STATUS_HISTORY)
    return pl.concat(batches, how="vertical")


def shipment_lifecycle_position(status: str) -> int:
    """Return a status's position in the shipment lifecycle.

    Args:
        status: A lifecycle status name.

    Returns:
        The one-based position.

    Raises:
        KeyError: If the status is not part of the current lifecycle.
    """
    for position, member in enumerate(SHIPMENT_LIFECYCLE, start=1):
        if str(member) == status:
            return position
    raise KeyError(
        f"Unknown shipment status: {status!r}. "
        f"Lifecycle: {tuple(str(member) for member in SHIPMENT_LIFECYCLE)}"
    )
