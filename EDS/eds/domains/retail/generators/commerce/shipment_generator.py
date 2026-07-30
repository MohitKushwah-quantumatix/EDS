"""Generator for the shipments dataset.

A shipment is the physical side of an order, and it exists only where the
money actually moved: a captured payment. A failed or voided payment ships
nothing. Three architecture rules shape it:

* **ADR-007.** ``shipping_method`` is *copied* from the checkout the order
  came from, never re-drawn. The customer chose it and paid for it.
* **ADR-009.** ``tracking_number`` is derived from the shipment's own
  identifier rather than sampled, so it is unique by construction rather than
  by luck.
* **ADR-012.** The shipment document is written once. ``current_status``,
  ``shipped_at`` and ``delivered_at`` are denormalised conveniences derived
  from the shipment's status history, and :func:`apply_status_and_timeline` is
  what sets them.

Generation is expression-based rather than row-by-row: the random draws are
taken as whole vectors up front and attached as columns, so the dataset is one
Polars pipeline that stays reproducible from the seed.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Final

import polars as pl

from eds.config import ShipmentConfig
from eds.core.frames import empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.commerce.enums import PaymentStatus, ShipmentStatus
from eds.domains.retail.domain.commerce.schema import SHIPMENTS

__all__ = [
    "SHIPMENT_NUMBER_SEQUENCE_WIDTH",
    "TRACKING_NUMBER_DIGITS",
    "apply_status_and_timeline",
    "generate_shipments",
    "iter_shipment_batches",
    "shipment_number_expression",
    "tracking_number_expression",
]

#: Zero-padded width of the sequence in ``SHP-YYYYMMDD-000001``.
SHIPMENT_NUMBER_SEQUENCE_WIDTH: Final[int] = 6

#: Digits in the tracking number's body, as in ``TRK-4738105562``.
TRACKING_NUMBER_DIGITS: Final[int] = 10

#: Size of the tracking number space.
_TRACKING_MODULUS: Final[int] = 10**TRACKING_NUMBER_DIGITS

#: Odd, not a multiple of five, and therefore coprime to the modulus, which
#: makes ``id -> (id * multiplier + offset) mod modulus`` a bijection. That is
#: what guarantees the tracking numbers are unique rather than merely unlikely
#: to collide - no hash, and no birthday problem.
_TRACKING_MULTIPLIER: Final[int] = 2_654_435_761

#: Shifts the sequence off zero so the first shipment does not read as one.
_TRACKING_OFFSET: Final[int] = 7_246_913


def shipment_number_expression(prefix: str) -> pl.Expr:
    """Build the business shipment number.

    The number is ``<prefix>-YYYYMMDD-NNNNNN``, where the sequence restarts
    each day and counts shipments in the order they were created. Because the
    shipments are sorted deterministically before this runs, the same input
    always yields the same numbers.

    Args:
        prefix: Leading token, such as ``"SHP"``.

    Returns:
        An expression producing the shipment number. It reads a
        ``shipment_date`` column, which the pipeline adds before calling this.
    """
    sequence = pl.int_range(pl.len(), dtype=pl.UInt32).over("shipment_date") + 1
    return pl.concat_str(
        [
            pl.lit(prefix),
            pl.col("shipment_date").dt.strftime("%Y%m%d"),
            sequence.cast(pl.String).str.zfill(SHIPMENT_NUMBER_SEQUENCE_WIDTH),
        ],
        separator="-",
    ).alias("shipment_number")


def tracking_number_expression(prefix: str) -> pl.Expr:
    """Build the carrier tracking number.

    The number is ``<prefix>-`` followed by ten digits scrambled from the
    shipment identifier. The scramble is a modular multiplication by a
    constant coprime to the modulus, which is a bijection: two shipments can
    never share a tracking number, and the same shipment always gets the same
    one. No seed is involved, so the value is reproducible even across runs
    with different seeds.

    Args:
        prefix: Leading token, such as ``"TRK"``.

    Returns:
        An expression producing the tracking number. It reads a
        ``shipment_id`` column.
    """
    scrambled = (pl.col("shipment_id") * _TRACKING_MULTIPLIER + _TRACKING_OFFSET).mod(
        _TRACKING_MODULUS
    )
    return pl.concat_str(
        [
            pl.lit(prefix),
            scrambled.cast(pl.String).str.zfill(TRACKING_NUMBER_DIGITS),
        ],
        separator="-",
    ).alias("tracking_number")


def _shippable(
    payments: pl.DataFrame, orders: pl.DataFrame, checkouts: pl.DataFrame
) -> pl.DataFrame:
    """Select the payments that produce a shipment, in a deterministic order.

    The shipping method lives on the checkout rather than the order or the
    payment, so all three are joined here.

    Args:
        payments: The F007 payments dataset.
        orders: The F006 orders dataset.
        checkouts: The F005 checkout dataset.

    Returns:
        Captured payments sorted by capture time then identifier, carrying the
        order's ``checkout_id`` and the checkout's ``shipping_method``.
    """
    return (
        payments.filter(pl.col("payment_status") == str(PaymentStatus.CAPTURED))
        .join(orders.select("order_id", "checkout_id"), on="order_id", how="inner")
        .join(checkouts.select("checkout_id", "shipping_method"), on="checkout_id", how="inner")
        .sort("captured_at", "payment_id")
    )


def _carrier_tables(
    config: ShipmentConfig, methods: list[str]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build the per-method carrier and delivery-window lookups.

    Args:
        config: Shipment configuration.
        methods: The shipping methods actually present in the data.

    Returns:
        A ``(choices, windows)`` pair. ``choices`` has one row per
        method-and-carrier with a zero-based ``carrier_index``; ``windows`` has
        one row per method with its carrier count and delivery day range.

    Raises:
        KeyError: If a method in the data has no carrier list or no delivery
            window configured. Checking against the data rather than against
            the enum catches the failure that actually matters.
    """
    missing_carriers = sorted(method for method in methods if method not in config.carriers)
    missing_windows = sorted(method for method in methods if method not in config.delivery_days)
    if missing_carriers or missing_windows:
        raise KeyError(
            "shipments.yaml does not cover every shipping method in the data. "
            f"Missing from carriers: {missing_carriers}. "
            f"Missing from delivery_days: {missing_windows}."
        )

    choice_methods: list[str] = []
    choice_indexes: list[int] = []
    choice_carriers: list[str] = []
    for method in methods:
        for index, carrier in enumerate(config.carriers[method]):
            choice_methods.append(method)
            choice_indexes.append(index)
            choice_carriers.append(carrier)

    choices = pl.DataFrame(
        {
            "shipping_method": choice_methods,
            "carrier_index": choice_indexes,
            "carrier": choice_carriers,
        },
        schema={
            "shipping_method": pl.String,
            "carrier_index": pl.Int64,
            "carrier": pl.String,
        },
    )
    windows = pl.DataFrame(
        {
            "shipping_method": methods,
            "carrier_count": [len(config.carriers[method]) for method in methods],
            "min_delivery_days": [config.delivery_days[method][0] for method in methods],
            "max_delivery_days": [config.delivery_days[method][1] for method in methods],
        },
        schema={
            "shipping_method": pl.String,
            "carrier_count": pl.Int64,
            "min_delivery_days": pl.Int64,
            "max_delivery_days": pl.Int64,
        },
    )
    return choices, windows


def iter_shipment_batches(
    config: ShipmentConfig,
    payments: pl.DataFrame,
    orders: pl.DataFrame,
    checkouts: pl.DataFrame,
    seed: int,
) -> Iterator[pl.DataFrame]:
    """Yield shipments in batches, one per captured payment.

    Args:
        config: Shipment configuration.
        payments: The F007 payments dataset.
        orders: The F006 orders dataset.
        checkouts: The F005 checkout dataset.
        seed: Run seed.

    Yields:
        Frames matching the shipments schema, with ``current_status`` set to
        ``CREATED`` and the timeline columns still empty.
        :func:`apply_status_and_timeline` fills them once the history exists.

    Raises:
        KeyError: If a shipping method in the data has no carrier configured.
    """
    shippable = _shippable(payments, orders, checkouts)
    if shippable.is_empty():
        return

    methods = sorted(set(shippable["shipping_method"].to_list()))
    choices, windows = _carrier_tables(config, methods)

    rng = make_rng(seed, "shipments")
    total = shippable.height

    # One draw per shipment per decision, taken up front so the frame can be
    # assembled with expressions instead of a loop.
    carrier_roll = [rng.random() for _ in range(total)]
    delivery_roll = [rng.random() for _ in range(total)]

    lead = timedelta(seconds=config.shipment_lead_seconds)
    built = (
        shippable.with_columns(
            pl.Series("carrier_roll", carrier_roll, dtype=pl.Float64),
            pl.Series("delivery_roll", delivery_roll, dtype=pl.Float64),
            (pl.col("captured_at") + lead).alias("created_at"),
        )
        .join(windows, on="shipping_method", how="inner")
        .with_columns(
            # Scale each roll across its method's own option count, so a
            # method with one carrier always yields that carrier.
            (pl.col("carrier_roll") * pl.col("carrier_count"))
            .floor()
            .cast(pl.Int64)
            .clip(upper_bound=pl.col("carrier_count") - 1)
            .alias("carrier_index"),
            (
                pl.col("min_delivery_days")
                + (
                    pl.col("delivery_roll")
                    * (pl.col("max_delivery_days") - pl.col("min_delivery_days") + 1)
                )
                .floor()
                .cast(pl.Int64)
            )
            .clip(upper_bound=pl.col("max_delivery_days"))
            .alias("delivery_days"),
        )
        .join(choices, on=["shipping_method", "carrier_index"], how="inner")
        # The promise is made when the shipment is created, not when it
        # eventually leaves, so the estimate hangs off created_at.
        .with_columns(
            (pl.col("created_at") + pl.duration(days=pl.col("delivery_days"))).alias(
                "estimated_delivery_at"
            ),
        )
        .sort("created_at", "payment_id")
        .with_columns(
            pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("shipment_id"),
            pl.col("created_at").dt.date().alias("shipment_date"),
            pl.lit(str(ShipmentStatus.CREATED)).alias("current_status"),
            pl.lit(None, dtype=pl.Datetime("us")).alias("shipped_at"),
            pl.lit(None, dtype=pl.Datetime("us")).alias("delivered_at"),
        )
        .with_columns(
            shipment_number_expression(config.shipment_number_prefix),
            tracking_number_expression(config.tracking_number_prefix),
        )
        .select(
            "shipment_id",
            "shipment_number",
            "order_id",
            "payment_id",
            "customer_id",
            "carrier",
            # Copied verbatim from the checkout under ADR-007.
            "shipping_method",
            "tracking_number",
            "current_status",
            "shipped_at",
            "estimated_delivery_at",
            "delivered_at",
            "created_at",
        )
    )

    for offset in range(0, built.height, config.batch_size):
        yield built.slice(offset, config.batch_size)


def generate_shipments(
    config: ShipmentConfig,
    payments: pl.DataFrame,
    orders: pl.DataFrame,
    checkouts: pl.DataFrame,
    seed: int,
) -> pl.DataFrame:
    """Generate the complete shipments dataset.

    Args:
        config: Shipment configuration.
        payments: The F007 payments dataset.
        orders: The F006 orders dataset.
        checkouts: The F005 checkout dataset.
        seed: Run seed.

    Returns:
        One row per captured payment, keyed by sequential ``shipment_id``,
        with ``current_status`` set to ``CREATED``.

    Raises:
        KeyError: If a shipping method in the data has no carrier configured.
    """
    batches = list(iter_shipment_batches(config, payments, orders, checkouts, seed))
    return pl.concat(batches, how="vertical") if batches else empty_frame(SHIPMENTS)


def apply_status_and_timeline(
    shipments: pl.DataFrame, status_history: pl.DataFrame
) -> pl.DataFrame:
    """Set each shipment's status and timeline from its status history.

    ADR-012 makes the history the source of truth, so ``current_status``,
    ``shipped_at`` and ``delivered_at`` are all read back out of it rather than
    maintained alongside it. A shipment that never reached ``DELIVERED`` keeps
    a null ``delivered_at``, which is complete data rather than missing data.

    Args:
        shipments: The generated shipments dataset.
        status_history: The generated shipment status history.

    Returns:
        The shipments with their status and timeline columns filled in.
    """
    if shipments.is_empty():
        return shipments

    latest = (
        status_history.sort("shipment_id", "sequence")
        .group_by("shipment_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest_status"))
    )
    stamps = status_history.group_by("shipment_id").agg(
        pl.col("status_timestamp")
        .filter(pl.col("status") == str(ShipmentStatus.SHIPPED))
        .first()
        .alias("shipped_stamp"),
        pl.col("status_timestamp")
        .filter(pl.col("status") == str(ShipmentStatus.DELIVERED))
        .first()
        .alias("delivered_stamp"),
    )
    return (
        shipments.join(latest, on="shipment_id", how="left")
        .join(stamps, on="shipment_id", how="left")
        .with_columns(
            pl.col("latest_status").fill_null(pl.col("current_status")).alias("current_status"),
            pl.col("shipped_stamp").alias("shipped_at"),
            pl.col("delivered_stamp").alias("delivered_at"),
        )
        .drop("latest_status", "shipped_stamp", "delivered_stamp")
        .select(shipments.columns)
    )
