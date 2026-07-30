"""Generator for the payment status history dataset.

Under ADR-010 a payment's progression lives in its own dataset rather than in a
field that gets overwritten, and under ADR-012 the payment document itself is
immutable. This generator produces that progression.

A payment either fails outright - one row, and that is the whole story - or is
authorised and then either captured or voided. There is no third step: a
reversal after capture is a refund, which belongs to a later feature.

Every timestamp except the void is read off the payment, so the history is
derived rather than re-drawn. Only the wait before voiding needs a draw of its
own, and it is taken as a whole vector up front so the frame is assembled with
Polars expressions rather than a row-by-row loop.
"""

from __future__ import annotations

from collections.abc import Iterator

import polars as pl

from eds.config import PaymentConfig
from eds.core.frames import empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.commerce.enums import PaymentStatus
from eds.domains.retail.domain.commerce.schema import PAYMENT_STATUS_HISTORY

__all__ = [
    "generate_payment_status_history",
    "iter_payment_status_batches",
]


def _stage_frame(
    payments: pl.DataFrame, status: PaymentStatus, sequence: int, timestamps: pl.Expr
) -> pl.DataFrame:
    """Build one lifecycle stage for a set of payments.

    Args:
        payments: Payments that reached this stage.
        status: The stage being recorded.
        sequence: Position of the stage in the payment's history.
        timestamps: Expression producing the moment the stage was reached.

    Returns:
        A frame of ``payment_id``, ``status``, ``sequence``,
        ``status_timestamp``.
    """
    return payments.select(
        pl.col("payment_id"),
        pl.lit(str(status)).alias("status"),
        pl.lit(sequence, dtype=pl.Int64).alias("sequence"),
        timestamps.alias("status_timestamp"),
    )


def iter_payment_status_batches(
    config: PaymentConfig, payments: pl.DataFrame, seed: int
) -> Iterator[pl.DataFrame]:
    """Yield payment status history in batches.

    Args:
        config: Payment configuration.
        payments: The generated payments dataset.
        seed: Run seed.

    Yields:
        Frames matching the payment status history schema, ordered by payment
        and then by sequence.
    """
    if payments.is_empty():
        return

    rng = make_rng(seed, "payment_status_history")
    total = payments.height

    # The capture moment is already on the payment; only the void needs a
    # draw. It is taken for every payment so the stream stays aligned with the
    # dataset regardless of how many payments end up voided.
    void_delay = [
        rng.randint(config.min_void_minutes, config.max_void_minutes) for _ in range(total)
    ]

    staged = payments.select(
        "payment_id", "payment_status", "authorized_at", "captured_at", "created_at"
    ).with_columns(pl.Series("void_minutes", void_delay, dtype=pl.Int64))
    staged = staged.with_columns(
        (pl.col("authorized_at") + pl.duration(minutes=pl.col("void_minutes"))).alias("voided_at")
    )

    authorized = _stage_frame(
        staged.filter(pl.col("payment_status") != str(PaymentStatus.FAILED)),
        PaymentStatus.AUTHORIZED,
        1,
        pl.col("authorized_at"),
    )
    # A failed payment never reached authorisation, so its single row sits at
    # sequence 1 and is stamped with the moment of the attempt.
    failed = _stage_frame(
        staged.filter(pl.col("payment_status") == str(PaymentStatus.FAILED)),
        PaymentStatus.FAILED,
        1,
        pl.col("created_at"),
    )
    captured = _stage_frame(
        staged.filter(pl.col("payment_status") == str(PaymentStatus.CAPTURED)),
        PaymentStatus.CAPTURED,
        2,
        pl.col("captured_at"),
    )
    voided = _stage_frame(
        staged.filter(pl.col("payment_status") == str(PaymentStatus.VOIDED)),
        PaymentStatus.VOIDED,
        2,
        pl.col("voided_at"),
    )

    built = (
        pl.concat([authorized, failed, captured, voided], how="vertical")
        .sort("payment_id", "sequence")
        .with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("history_id"))
        .select("history_id", "payment_id", "status", "sequence", "status_timestamp")
    )

    for offset in range(0, built.height, config.batch_size):
        yield built.slice(offset, config.batch_size)


def generate_payment_status_history(
    config: PaymentConfig, payments: pl.DataFrame, seed: int
) -> pl.DataFrame:
    """Generate the complete payment status history dataset.

    Args:
        config: Payment configuration.
        payments: The generated payments dataset.
        seed: Run seed.

    Returns:
        One row per status each payment reached, keyed by sequential
        ``history_id``. Every payment has at least one row.
    """
    batches = list(iter_payment_status_batches(config, payments, seed))
    if not batches:
        return empty_frame(PAYMENT_STATUS_HISTORY)
    return pl.concat(batches, how="vertical")
