"""Generator for the return status history dataset.

Under ADR-010 a return's progression lives in its own dataset rather than in a
field that gets overwritten, and under ADR-012 the return document itself is
immutable. This generator produces that progression, and it owns the whole
timeline: ``approved_at``, ``received_at`` and ``completed_at`` are read back
off the history rather than computed twice.

Every return is ``REQUESTED`` and ``APPROVED``. Most go on to ``IN_TRANSIT``,
then ``RECEIVED``, then ``COMPLETED``. A return that stops early is complete
data, not missing data - it is simply still working its way back when the
simulated window ends.

The random draws are taken as whole vectors up front and then attached as
columns, so the dataset is built with Polars expressions rather than a
row-by-row loop while staying reproducible from the seed.
"""

from __future__ import annotations

from collections.abc import Iterator

import polars as pl

from eds.config import ReturnConfig
from eds.core.frames import empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.commerce.enums import RETURN_LIFECYCLE, ReturnStatus
from eds.domains.retail.domain.commerce.schema import RETURN_STATUS_HISTORY

__all__ = [
    "generate_return_status_history",
    "iter_return_status_batches",
    "return_lifecycle_position",
]


def _stage_frame(
    returns: pl.DataFrame, status: ReturnStatus, sequence: int, timestamps: pl.Expr
) -> pl.DataFrame:
    """Build one lifecycle stage for a set of returns.

    Args:
        returns: Returns that reached this stage.
        status: The stage being recorded.
        sequence: Position of the stage in the return's history.
        timestamps: Expression producing the moment the stage was reached.

    Returns:
        A frame of ``return_id``, ``status``, ``sequence``, ``status_timestamp``.
    """
    return returns.select(
        pl.col("return_id"),
        pl.lit(str(status)).alias("status"),
        pl.lit(sequence, dtype=pl.Int64).alias("sequence"),
        timestamps.alias("status_timestamp"),
    )


def iter_return_status_batches(
    config: ReturnConfig, returns: pl.DataFrame, seed: int
) -> Iterator[pl.DataFrame]:
    """Yield return status history in batches.

    Args:
        config: Return configuration.
        returns: The generated returns dataset.
        seed: Run seed.

    Yields:
        Frames matching the return status history schema, ordered by return and
        then by sequence.
    """
    if returns.is_empty():
        return

    rng = make_rng(seed, "return_status_history")
    total = returns.height

    # One draw per return per decision, taken up front so the frame can be
    # assembled with expressions instead of a loop.
    progress_roll = [rng.random() for _ in range(total)]
    approval_delay = [
        rng.randint(config.min_approval_hours, config.max_approval_hours) for _ in range(total)
    ]
    dispatch_delay = [
        rng.randint(config.min_dispatch_hours, config.max_dispatch_hours) for _ in range(total)
    ]
    transit_delay = [
        rng.randint(config.min_transit_hours, config.max_transit_hours) for _ in range(total)
    ]
    completion_delay = [
        rng.randint(config.min_completion_hours, config.max_completion_hours) for _ in range(total)
    ]

    staged = (
        returns.select("return_id", "requested_at")
        .with_columns(
            pl.Series("progress_roll", progress_roll, dtype=pl.Float64),
            pl.Series("approval_hours", approval_delay, dtype=pl.Int64),
            pl.Series("dispatch_hours", dispatch_delay, dtype=pl.Int64),
            pl.Series("transit_hours", transit_delay, dtype=pl.Int64),
            pl.Series("completion_hours", completion_delay, dtype=pl.Int64),
        )
        .with_columns(
            (pl.col("requested_at") + pl.duration(hours=pl.col("approval_hours"))).alias(
                "approved_at"
            )
        )
        .with_columns(
            (pl.col("approved_at") + pl.duration(hours=pl.col("dispatch_hours"))).alias(
                "in_transit_at"
            )
        )
        .with_columns(
            (pl.col("in_transit_at") + pl.duration(hours=pl.col("transit_hours"))).alias(
                "received_at"
            )
        )
        .with_columns(
            (pl.col("received_at") + pl.duration(hours=pl.col("completion_hours"))).alias(
                "completed_at"
            )
        )
    )

    # The four completion shares are validated to sum to one, so every return
    # clears REQUESTED and APPROVED, and the cuts only decide how much further
    # it got. Each cut is the share reaching *at least* that stage.
    in_transit_cut = config.completed_rate + config.received_rate + config.in_transit_rate
    received_cut = config.completed_rate + config.received_rate

    requested = _stage_frame(staged, ReturnStatus.REQUESTED, 1, pl.col("requested_at"))
    approved = _stage_frame(staged, ReturnStatus.APPROVED, 2, pl.col("approved_at"))

    in_transit_returns = staged.filter(pl.col("progress_roll") < in_transit_cut)
    in_transit = _stage_frame(
        in_transit_returns, ReturnStatus.IN_TRANSIT, 3, pl.col("in_transit_at")
    )

    # Receipt follows being in transit, and completion follows receipt, so each
    # stage narrows the one before it.
    received_returns = in_transit_returns.filter(pl.col("progress_roll") < received_cut)
    received = _stage_frame(received_returns, ReturnStatus.RECEIVED, 4, pl.col("received_at"))

    completed_returns = received_returns.filter(pl.col("progress_roll") < config.completed_rate)
    completed = _stage_frame(completed_returns, ReturnStatus.COMPLETED, 5, pl.col("completed_at"))

    built = (
        pl.concat([requested, approved, in_transit, received, completed], how="vertical")
        .sort("return_id", "sequence")
        .with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("history_id"))
        .select("history_id", "return_id", "status", "sequence", "status_timestamp")
    )

    for offset in range(0, built.height, config.batch_size):
        yield built.slice(offset, config.batch_size)


def generate_return_status_history(
    config: ReturnConfig, returns: pl.DataFrame, seed: int
) -> pl.DataFrame:
    """Generate the complete return status history dataset.

    Args:
        config: Return configuration.
        returns: The generated returns dataset.
        seed: Run seed.

    Returns:
        One row per lifecycle stage each return reached, keyed by sequential
        ``history_id``. Every return reaches at least ``APPROVED``.
    """
    batches = list(iter_return_status_batches(config, returns, seed))
    if not batches:
        return empty_frame(RETURN_STATUS_HISTORY)
    return pl.concat(batches, how="vertical")


def return_lifecycle_position(status: str) -> int:
    """Return a status's position in the return lifecycle.

    Args:
        status: A lifecycle status name.

    Returns:
        The one-based position.

    Raises:
        KeyError: If the status is not part of the current lifecycle.
    """
    for position, member in enumerate(RETURN_LIFECYCLE, start=1):
        if str(member) == status:
            return position
    raise KeyError(
        f"Unknown return status: {status!r}. "
        f"Lifecycle: {tuple(str(member) for member in RETURN_LIFECYCLE)}"
    )
