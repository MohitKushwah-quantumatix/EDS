"""Generator for the payments dataset.

A payment is the money side of an order, and only of an order: nothing else in
the simulation originates one. Three architecture rules shape it:

* **ADR-007.** ``payment_amount`` is *copied* from the order's
  ``total_amount``, and ``payment_method`` from the checkout the order came
  from. Neither is recalculated or re-drawn.
* **ADR-009.** ``payment_provider`` is derived from the method rather than
  sampled - a customer paying by card does not separately pick who settles it.
* **ADR-012.** The payment document is written once. ``payment_status`` is a
  denormalised convenience derived from the payment's status history, and
  :func:`apply_payment_status` is what sets it.

Generation is expression-based rather than row-by-row: the random draws are
taken as whole vectors up front and attached as columns, so the dataset is one
Polars pipeline that stays reproducible from the seed.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Final

import polars as pl

from eds.config import PaymentConfig
from eds.core.frames import empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.commerce.enums import PAYMENT_PROVIDER_BY_METHOD, PaymentStatus
from eds.domains.retail.domain.commerce.schema import PAYMENTS

__all__ = [
    "PAYMENT_REFERENCE_SEQUENCE_WIDTH",
    "PROVIDER_BY_METHOD",
    "apply_payment_status",
    "generate_payments",
    "iter_payment_batches",
    "payment_reference_expression",
]

#: Zero-padded width of the sequence in ``PAY-YYYYMMDD-000001``.
PAYMENT_REFERENCE_SEQUENCE_WIDTH: Final[int] = 6

#: The method-to-provider mapping as plain strings, ready for a Polars lookup.
PROVIDER_BY_METHOD: Final[dict[str, str]] = {
    str(method): str(provider) for method, provider in PAYMENT_PROVIDER_BY_METHOD.items()
}


def payment_reference_expression(prefix: str) -> pl.Expr:
    """Build the business payment reference.

    The reference is ``<prefix>-YYYYMMDD-NNNNNN``, where the sequence restarts
    each day and counts payments in the order they were created. Because the
    payments are sorted deterministically before this runs, the same input
    always yields the same references.

    Args:
        prefix: Leading token, such as ``"PAY"``.

    Returns:
        An expression producing the payment reference. It reads a
        ``payment_date`` column, which the pipeline adds before calling this.
    """
    sequence = pl.int_range(pl.len(), dtype=pl.UInt32).over("payment_date") + 1
    return pl.concat_str(
        [
            pl.lit(prefix),
            pl.col("payment_date").dt.strftime("%Y%m%d"),
            sequence.cast(pl.String).str.zfill(PAYMENT_REFERENCE_SEQUENCE_WIDTH),
        ],
        separator="-",
    ).alias("payment_reference")


def _payable(orders: pl.DataFrame, checkouts: pl.DataFrame) -> pl.DataFrame:
    """Select the orders that are paid for, in a deterministic order.

    The payment method lives on the checkout rather than the order, so the two
    are joined here. An order billed at zero or less is not charged: there is
    nothing to authorise.

    Args:
        orders: The F006 orders dataset.
        checkouts: The F005 checkout dataset.

    Returns:
        Payable orders sorted by creation then identifier, with the checkout's
        ``payment_method`` attached and the order's own ``created_at``
        renamed to ``order_created_at``.
    """
    return (
        orders.join(
            checkouts.select("checkout_id", "payment_method"), on="checkout_id", how="inner"
        )
        .filter(pl.col("total_amount") > 0.0)
        .sort("created_at", "order_id")
        .rename({"created_at": "order_created_at"})
    )


def iter_payment_batches(
    config: PaymentConfig, orders: pl.DataFrame, checkouts: pl.DataFrame, seed: int
) -> Iterator[pl.DataFrame]:
    """Yield payments in batches, one per payable order.

    Args:
        config: Payment configuration.
        orders: The F006 orders dataset.
        checkouts: The F005 checkout dataset.
        seed: Run seed.

    Yields:
        Frames matching the payments schema. ``payment_status`` holds the drawn
        outcome; :func:`apply_payment_status` re-derives it from the status
        history once that exists.
    """
    payable = _payable(orders, checkouts)
    if payable.is_empty():
        return

    rng = make_rng(seed, "payments")
    total = payable.height

    # One draw per payment per decision, taken up front so the frame can be
    # assembled with expressions instead of a loop.
    outcome_roll = [rng.random() for _ in range(total)]
    capture_delay = [
        rng.randint(config.min_capture_minutes, config.max_capture_minutes) for _ in range(total)
    ]

    lead = timedelta(seconds=config.authorization_lead_seconds)
    # The three outcome shares are validated to sum to one, so the second cut
    # covers voiding and everything above it fails.
    captured_cut = config.capture_rate
    voided_cut = config.capture_rate + config.void_rate

    built = (
        payable.with_columns(
            pl.Series("outcome_roll", outcome_roll, dtype=pl.Float64),
            pl.Series("capture_minutes", capture_delay, dtype=pl.Int64),
            (pl.col("order_created_at") + lead).alias("created_at"),
        )
        .with_columns(
            pl.when(pl.col("outcome_roll") < captured_cut)
            .then(pl.lit(str(PaymentStatus.CAPTURED)))
            .when(pl.col("outcome_roll") < voided_cut)
            .then(pl.lit(str(PaymentStatus.VOIDED)))
            .otherwise(pl.lit(str(PaymentStatus.FAILED)))
            .alias("payment_status"),
        )
        .with_columns(
            # A failed payment was never authorised, so it has no
            # authorisation moment - the attempt is all there is.
            pl.when(pl.col("payment_status") != str(PaymentStatus.FAILED))
            .then(pl.col("created_at"))
            .alias("authorized_at"),
        )
        .with_columns(
            # Only a captured payment ever took the money.
            pl.when(pl.col("payment_status") == str(PaymentStatus.CAPTURED))
            .then(pl.col("authorized_at") + pl.duration(minutes=pl.col("capture_minutes")))
            .alias("captured_at"),
        )
        .with_columns(
            pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("payment_id"),
            pl.col("created_at").dt.date().alias("payment_date"),
            pl.lit(config.currency).alias("currency"),
            pl.col("payment_method").replace_strict(PROVIDER_BY_METHOD).alias("payment_provider"),
            # Copied verbatim from the order under ADR-007.
            pl.col("total_amount").alias("payment_amount"),
        )
        .with_columns(payment_reference_expression(config.payment_reference_prefix))
        .select(
            "payment_id",
            "payment_reference",
            "order_id",
            "customer_id",
            "payment_method",
            "payment_provider",
            "currency",
            "payment_amount",
            "payment_status",
            "authorized_at",
            "captured_at",
            "created_at",
        )
    )

    for offset in range(0, built.height, config.batch_size):
        yield built.slice(offset, config.batch_size)


def generate_payments(
    config: PaymentConfig, orders: pl.DataFrame, checkouts: pl.DataFrame, seed: int
) -> pl.DataFrame:
    """Generate the complete payments dataset.

    Args:
        config: Payment configuration.
        orders: The F006 orders dataset.
        checkouts: The F005 checkout dataset.
        seed: Run seed.

    Returns:
        One row per payable order, keyed by sequential ``payment_id``.
    """
    batches = list(iter_payment_batches(config, orders, checkouts, seed))
    return pl.concat(batches, how="vertical") if batches else empty_frame(PAYMENTS)


def apply_payment_status(payments: pl.DataFrame, status_history: pl.DataFrame) -> pl.DataFrame:
    """Set each payment's status from its latest history row.

    ADR-012 makes the history the source of truth and ``payment_status`` a
    derived convenience, so this reads the history rather than the other way
    round.

    Args:
        payments: The generated payments dataset.
        status_history: The generated payment status history.

    Returns:
        The payments with ``payment_status`` replaced by the status of their
        highest-sequence history row.
    """
    if payments.is_empty():
        return payments

    latest = (
        status_history.sort("payment_id", "sequence")
        .group_by("payment_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest_status"))
    )
    return (
        payments.join(latest, on="payment_id", how="left")
        .with_columns(
            pl.col("latest_status").fill_null(pl.col("payment_status")).alias("payment_status")
        )
        .drop("latest_status")
        .select(payments.columns)
    )
