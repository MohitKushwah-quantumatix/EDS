"""Generator for the returns dataset.

A return is the reverse journey, and it starts where the forward one ended: a
shipment that was actually delivered. A shipment still in transit has not
arrived, so there is nothing to send back. Three architecture rules shape it:

* **ADR-008.** The shipment is the return's single parent. ``customer_id`` is
  copied from it rather than re-derived through the order.
* **ADR-009.** ``return_reason`` is drawn from ``return_reasons.parquet``, the
  master data table, never from a literal in this module.
* **ADR-012.** The return document is written once. ``current_status``,
  ``approved_at``, ``received_at`` and ``completed_at`` are denormalised
  conveniences derived from the return's status history, and
  :func:`apply_status_and_timeline` is what sets them.

Generation is expression-based rather than row-by-row: the random draws are
taken as whole vectors up front and attached as columns, so the dataset is one
Polars pipeline that stays reproducible from the seed.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Final

import polars as pl

from eds.config import ReturnConfig
from eds.core.frames import empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.commerce.enums import ReturnStatus, ShipmentStatus
from eds.domains.retail.domain.commerce.schema import RETURNS

__all__ = [
    "RETURN_NUMBER_SEQUENCE_WIDTH",
    "apply_status_and_timeline",
    "eligible_shipments",
    "generate_returns",
    "iter_return_batches",
    "return_number_expression",
]

#: Zero-padded width of the sequence in ``RET-YYYYMMDD-000001``.
RETURN_NUMBER_SEQUENCE_WIDTH: Final[int] = 6


def return_number_expression(prefix: str) -> pl.Expr:
    """Build the business return number.

    The number is ``<prefix>-YYYYMMDD-NNNNNN``, where the sequence restarts
    each day and counts returns in the order they were requested. Because the
    returns are sorted deterministically before this runs, the same input
    always yields the same numbers.

    Args:
        prefix: Leading token, such as ``"RET"``.

    Returns:
        An expression producing the return number. It reads a ``return_date``
        column, which the pipeline adds before calling this.
    """
    sequence = pl.int_range(pl.len(), dtype=pl.UInt32).over("return_date") + 1
    return pl.concat_str(
        [
            pl.lit(prefix),
            pl.col("return_date").dt.strftime("%Y%m%d"),
            sequence.cast(pl.String).str.zfill(RETURN_NUMBER_SEQUENCE_WIDTH),
        ],
        separator="-",
    ).alias("return_number")


def eligible_shipments(shipments: pl.DataFrame, shipment_items: pl.DataFrame) -> pl.DataFrame:
    """Select the shipments a customer could send back.

    A shipment must have been delivered, and it must have carried something:
    the objective is that returns originate from delivered shipment *items*, so
    a delivered shipment with no items has nothing to return.

    Args:
        shipments: The F008 shipments dataset.
        shipment_items: The F008 shipment items dataset.

    Returns:
        Delivered, non-empty shipments sorted by delivery time then identifier.
    """
    return (
        shipments.filter(
            (pl.col("current_status") == str(ShipmentStatus.DELIVERED))
            & pl.col("delivered_at").is_not_null()
        )
        .join(shipment_items.select("shipment_id").unique(), on="shipment_id", how="semi")
        .sort("delivered_at", "shipment_id")
    )


def _reason_codes(return_reasons: pl.DataFrame) -> list[str]:
    """Return the reason codes a customer may choose from.

    Args:
        return_reasons: The F001 return reasons master dataset.

    Returns:
        The active reason codes, in dataset order.

    Raises:
        ValueError: If no active reason is available, which would leave the
            generator with nothing to attribute a return to.
    """
    active = return_reasons.filter(pl.col("is_active").cast(pl.Boolean))["reason_code"].to_list()
    if not active:
        raise ValueError(
            "return_reasons.parquet contains no active reason. F009 reads the "
            "reason vocabulary from master data and does not substitute a default."
        )
    return [str(code) for code in active]


def _weighted_choices(weights: Mapping[str, float]) -> tuple[list[str], list[float]]:
    """Split a weight mapping into aligned names and cumulative cut points.

    Args:
        weights: Option name to share. The shares are validated to sum to one.

    Returns:
        A ``(names, cumulative)`` pair, where ``cumulative[i]`` is the upper
        bound of option ``i`` on the unit interval.
    """
    names = list(weights)
    cumulative: list[float] = []
    running = 0.0
    for name in names:
        running += weights[name]
        cumulative.append(running)
    return names, cumulative


def _pick(rolls: list[float], names: list[str], cumulative: list[float]) -> list[str]:
    """Map uniform draws onto weighted options.

    Args:
        rolls: One uniform draw per row.
        names: Option names.
        cumulative: Cumulative upper bounds aligned with ``names``.

    Returns:
        The chosen option for each draw.
    """
    picked: list[str] = []
    last = names[-1]
    for roll in rolls:
        for name, bound in zip(names, cumulative, strict=True):
            if roll < bound:
                picked.append(name)
                break
        else:
            # Only reachable through floating-point drift at the very top of
            # the interval, where the last option is the right answer anyway.
            picked.append(last)
    return picked


def iter_return_batches(
    config: ReturnConfig,
    shipments: pl.DataFrame,
    shipment_items: pl.DataFrame,
    return_reasons: pl.DataFrame,
    seed: int,
) -> Iterator[pl.DataFrame]:
    """Yield returns in batches, at most one per eligible shipment.

    Args:
        config: Return configuration.
        shipments: The F008 shipments dataset.
        shipment_items: The F008 shipment items dataset.
        return_reasons: The F001 return reasons master dataset.
        seed: Run seed.

    Yields:
        Frames matching the returns schema, with ``current_status`` set to
        ``REQUESTED`` and the later timeline columns still empty.
        :func:`apply_status_and_timeline` fills them once the history exists.

    Raises:
        ValueError: If the master data offers no active return reason.
    """
    eligible = eligible_shipments(shipments, shipment_items)
    if eligible.is_empty():
        return

    codes = _reason_codes(return_reasons)
    refund_names, refund_bounds = _weighted_choices(config.refund_types)

    rng = make_rng(seed, "returns")
    total = eligible.height

    # One draw per eligible shipment per decision, taken up front so the frame
    # can be assembled with expressions instead of a loop. The requested
    # shipments are decided first, then the reason, settlement and delay are
    # drawn only for those - keeping the stream short and the intent clear.
    request_roll = [rng.random() for _ in range(total)]
    requested = eligible.with_columns(
        pl.Series("request_roll", request_roll, dtype=pl.Float64)
    ).filter(pl.col("request_roll") < config.return_rate)
    if requested.is_empty():
        return

    chosen = requested.height
    reason_roll = [rng.randrange(len(codes)) for _ in range(chosen)]
    refund_roll = [rng.random() for _ in range(chosen)]
    request_delay = [
        rng.randint(config.min_request_days, config.max_request_days) for _ in range(chosen)
    ]

    built = (
        requested.with_columns(
            pl.Series("reason_index", reason_roll, dtype=pl.Int64),
            pl.Series("refund_roll", refund_roll, dtype=pl.Float64),
            pl.Series("request_days", request_delay, dtype=pl.Int64),
        )
        .with_columns(
            # The request is the moment the return document exists, so both
            # timestamps are the same instant.
            (pl.col("delivered_at") + pl.duration(days=pl.col("request_days"))).alias(
                "requested_at"
            ),
            pl.Series(
                "return_reason",
                [codes[index] for index in reason_roll],
                dtype=pl.String,
            ),
            pl.Series(
                "refund_type",
                _pick(refund_roll, refund_names, refund_bounds),
                dtype=pl.String,
            ),
        )
        .sort("requested_at", "shipment_id")
        .with_columns(
            pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("return_id"),
            pl.col("requested_at").alias("created_at"),
            pl.col("requested_at").dt.date().alias("return_date"),
            pl.lit(str(ReturnStatus.REQUESTED)).alias("current_status"),
            pl.lit(None, dtype=pl.Datetime("us")).alias("approved_at"),
            pl.lit(None, dtype=pl.Datetime("us")).alias("received_at"),
            pl.lit(None, dtype=pl.Datetime("us")).alias("completed_at"),
        )
        .with_columns(return_number_expression(config.return_number_prefix))
        .select(
            "return_id",
            "return_number",
            "shipment_id",
            # Copied from the shipment, its single parent under ADR-008.
            "customer_id",
            "return_reason",
            "refund_type",
            "current_status",
            "requested_at",
            "approved_at",
            "received_at",
            "completed_at",
            "created_at",
        )
    )

    for offset in range(0, built.height, config.batch_size):
        yield built.slice(offset, config.batch_size)


def generate_returns(
    config: ReturnConfig,
    shipments: pl.DataFrame,
    shipment_items: pl.DataFrame,
    return_reasons: pl.DataFrame,
    seed: int,
) -> pl.DataFrame:
    """Generate the complete returns dataset.

    Args:
        config: Return configuration.
        shipments: The F008 shipments dataset.
        shipment_items: The F008 shipment items dataset.
        return_reasons: The F001 return reasons master dataset.
        seed: Run seed.

    Returns:
        At most one row per delivered, non-empty shipment, keyed by sequential
        ``return_id``, with ``current_status`` set to ``REQUESTED``.

    Raises:
        ValueError: If the master data offers no active return reason.
    """
    batches = list(iter_return_batches(config, shipments, shipment_items, return_reasons, seed))
    return pl.concat(batches, how="vertical") if batches else empty_frame(RETURNS)


def apply_status_and_timeline(returns: pl.DataFrame, status_history: pl.DataFrame) -> pl.DataFrame:
    """Set each return's status and timeline from its status history.

    ADR-012 makes the history the source of truth, so ``current_status`` and
    the three later timestamps are all read back out of it rather than
    maintained alongside it. A return that never reached a stage keeps a null
    there, which is complete data rather than missing data.

    Args:
        returns: The generated returns dataset.
        status_history: The generated return status history.

    Returns:
        The returns with their status and timeline columns filled in.
    """
    if returns.is_empty():
        return returns

    latest = (
        status_history.sort("return_id", "sequence")
        .group_by("return_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest_status"))
    )
    stamps = status_history.group_by("return_id").agg(
        *[
            pl.col("status_timestamp")
            .filter(pl.col("status") == str(status))
            .first()
            .alias(f"{column}_stamp")
            for status, column in (
                (ReturnStatus.APPROVED, "approved_at"),
                (ReturnStatus.RECEIVED, "received_at"),
                (ReturnStatus.COMPLETED, "completed_at"),
            )
        ]
    )
    return (
        returns.join(latest, on="return_id", how="left")
        .join(stamps, on="return_id", how="left")
        .with_columns(
            pl.col("latest_status").fill_null(pl.col("current_status")).alias("current_status"),
            pl.col("approved_at_stamp").alias("approved_at"),
            pl.col("received_at_stamp").alias("received_at"),
            pl.col("completed_at_stamp").alias("completed_at"),
        )
        .drop("latest_status", "approved_at_stamp", "received_at_stamp", "completed_at_stamp")
        .select(returns.columns)
    )
