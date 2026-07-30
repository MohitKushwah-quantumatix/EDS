"""Generator for the reviews dataset.

A review is what a customer says about something they actually received and
kept. That makes the eligibility rule narrow: the shipment must have been
delivered, and the item must not have come back. An item that was returned is
excluded even though it arrived - whatever the customer thought of it, the
transaction is not the one this feature describes.

Three architecture rules shape it:

* **ADR-008.** The shipment item is the review's single parent. Everything
  else - the shipment, order, product and customer - is copied down that chain
  rather than re-derived.
* **ADR-009.** The title and body are *selected* from the configured phrases
  for the drawn rating, never generated. A three-star review can never carry
  five-star wording.
* **ADR-012.** The review is written once. Edits and moderation are out of
  scope, so there is no status and no history to derive anything from.

Generation is expression-based rather than row-by-row: the random draws are
taken as whole vectors up front and attached as columns, so the dataset is one
Polars pipeline that stays reproducible from the seed.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Final

import polars as pl

from eds.config import ReviewConfig
from eds.core.frames import empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.commerce.enums import ShipmentStatus
from eds.domains.retail.domain.commerce.schema import REVIEWS

__all__ = [
    "REVIEW_NUMBER_SEQUENCE_WIDTH",
    "eligible_items",
    "generate_reviews",
    "iter_review_batches",
    "review_number_expression",
]

#: Zero-padded width of the sequence in ``REV-YYYYMMDD-000001``.
REVIEW_NUMBER_SEQUENCE_WIDTH: Final[int] = 6


def review_number_expression(prefix: str) -> pl.Expr:
    """Build the business review number.

    The number is ``<prefix>-YYYYMMDD-NNNNNN``, where the sequence restarts
    each day and counts reviews in the order they were written. Because the
    reviews are sorted deterministically before this runs, the same input
    always yields the same numbers.

    Args:
        prefix: Leading token, such as ``"REV"``.

    Returns:
        An expression producing the review number. It reads a ``review_date``
        column, which the pipeline adds before calling this.
    """
    sequence = pl.int_range(pl.len(), dtype=pl.UInt32).over("review_date") + 1
    return pl.concat_str(
        [
            pl.lit(prefix),
            pl.col("review_date").dt.strftime("%Y%m%d"),
            sequence.cast(pl.String).str.zfill(REVIEW_NUMBER_SEQUENCE_WIDTH),
        ],
        separator="-",
    ).alias("review_number")


def eligible_items(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_items: pl.DataFrame
) -> pl.DataFrame:
    """Select the shipment items a customer could review.

    An item qualifies when its shipment reached ``DELIVERED`` and the item does
    not appear in ``return_items``. Both halves matter: an undelivered item was
    never seen, and a returned one is no longer the customer's to comment on.

    Args:
        shipments: The F008 shipments dataset.
        shipment_items: The F008 shipment items dataset.
        return_items: The F009 return items dataset.

    Returns:
        Eligible items sorted by delivery time then identifier, carrying the
        shipment's ``order_id``, ``customer_id`` and ``delivered_at``.
    """
    delivered = shipments.filter(
        (pl.col("current_status") == str(ShipmentStatus.DELIVERED))
        & pl.col("delivered_at").is_not_null()
    ).select("shipment_id", "order_id", "customer_id", "delivered_at")

    return (
        shipment_items.select("shipment_item_id", "shipment_id", "product_id")
        .join(delivered, on="shipment_id", how="inner")
        .join(
            return_items.select("shipment_item_id").unique(),
            on="shipment_item_id",
            how="anti",
        )
        .sort("delivered_at", "shipment_item_id")
    )


def _phrase_tables(
    table: Mapping[int, tuple[str, ...]], column: str
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build the per-rating phrase lookup and its option count.

    Args:
        table: Rating mapped to the phrases available for it.
        column: Name of the phrase column to produce.

    Returns:
        A ``(choices, counts)`` pair. ``choices`` has one row per
        rating-and-phrase with a zero-based index; ``counts`` has one row per
        rating with how many phrases it offers.
    """
    ratings: list[int] = []
    indexes: list[int] = []
    phrases: list[str] = []
    for rating in sorted(table):
        for index, phrase in enumerate(table[rating]):
            ratings.append(rating)
            indexes.append(index)
            phrases.append(phrase)

    choices = pl.DataFrame(
        {"rating": ratings, f"{column}_index": indexes, column: phrases},
        schema={"rating": pl.Int64, f"{column}_index": pl.Int64, column: pl.String},
    )
    counts = pl.DataFrame(
        {
            "rating": sorted(table),
            f"{column}_count": [len(table[rating]) for rating in sorted(table)],
        },
        schema={"rating": pl.Int64, f"{column}_count": pl.Int64},
    )
    return choices, counts


def _rating_expression(weights: Mapping[int, float]) -> pl.Expr:
    """Map a uniform draw onto a star rating.

    The weights are turned into cumulative cut points and applied with
    :meth:`polars.Expr.cut`, so the assignment is one vectorised operation
    rather than a comparison chain that would have to know how many ratings
    there are.

    Args:
        weights: Rating mapped to its share. Validated to sum to one.

    Returns:
        An expression producing the rating from a ``rating_roll`` column.
    """
    ratings = sorted(weights)
    breaks: list[float] = []
    running = 0.0
    # The final bound is left off: everything above the last break belongs to
    # the last rating, which is what `cut` does with n breaks and n+1 labels.
    for rating in ratings[:-1]:
        running += weights[rating]
        breaks.append(running)

    return (
        pl.col("rating_roll")
        .cut(breaks=breaks, labels=[str(rating) for rating in ratings])
        .cast(pl.String)
        .cast(pl.Int64)
        .alias("rating")
    )


def iter_review_batches(
    config: ReviewConfig,
    shipments: pl.DataFrame,
    shipment_items: pl.DataFrame,
    return_items: pl.DataFrame,
    seed: int,
) -> Iterator[pl.DataFrame]:
    """Yield reviews in batches, at most one per eligible shipment item.

    Args:
        config: Review configuration.
        shipments: The F008 shipments dataset.
        shipment_items: The F008 shipment items dataset.
        return_items: The F009 return items dataset.
        seed: Run seed.

    Yields:
        Frames matching the reviews schema.
    """
    eligible = eligible_items(shipments, shipment_items, return_items)
    if eligible.is_empty():
        return

    rng = make_rng(seed, "reviews")
    total = eligible.height

    # The reviewed items are decided first, then the rating, wording and delay
    # are drawn only for those - keeping the stream short and the intent clear.
    review_roll = [rng.random() for _ in range(total)]
    reviewed = eligible.with_columns(
        pl.Series("review_roll", review_roll, dtype=pl.Float64)
    ).filter(pl.col("review_roll") < config.review_rate)
    if reviewed.is_empty():
        return

    chosen = reviewed.height
    rating_roll = [rng.random() for _ in range(chosen)]
    title_roll = [rng.random() for _ in range(chosen)]
    text_roll = [rng.random() for _ in range(chosen)]
    delay_roll = [
        rng.randint(config.min_review_days, config.max_review_days) for _ in range(chosen)
    ]

    title_choices, title_counts = _phrase_tables(config.titles, "review_title")
    text_choices, text_counts = _phrase_tables(config.texts, "review_text")

    built = (
        reviewed.with_columns(
            pl.Series("rating_roll", rating_roll, dtype=pl.Float64),
            pl.Series("title_roll", title_roll, dtype=pl.Float64),
            pl.Series("text_roll", text_roll, dtype=pl.Float64),
            pl.Series("review_days", delay_roll, dtype=pl.Int64),
        )
        .with_columns(_rating_expression(config.rating_weights))
        .join(title_counts, on="rating", how="inner")
        .join(text_counts, on="rating", how="inner")
        .with_columns(
            # Scale each roll across the phrase count for its own rating, so a
            # rating offering one phrase always yields that phrase.
            (pl.col("title_roll") * pl.col("review_title_count"))
            .floor()
            .cast(pl.Int64)
            .clip(upper_bound=pl.col("review_title_count") - 1)
            .alias("review_title_index"),
            (pl.col("text_roll") * pl.col("review_text_count"))
            .floor()
            .cast(pl.Int64)
            .clip(upper_bound=pl.col("review_text_count") - 1)
            .alias("review_text_index"),
            (pl.col("delivered_at") + pl.duration(days=pl.col("review_days"))).alias("created_at"),
        )
        .join(title_choices, on=["rating", "review_title_index"], how="inner")
        .join(text_choices, on=["rating", "review_text_index"], how="inner")
        .sort("created_at", "shipment_item_id")
        .with_columns(
            pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("review_id"),
            pl.col("created_at").dt.date().alias("review_date"),
            # Every review comes from a delivered shipment, so there is no
            # unverified case to represent.
            pl.lit(True).alias("verified_purchase"),
        )
        .with_columns(review_number_expression(config.review_number_prefix))
        .select(
            "review_id",
            "review_number",
            "shipment_item_id",
            "shipment_id",
            "order_id",
            "product_id",
            "customer_id",
            "rating",
            "review_title",
            "review_text",
            "verified_purchase",
            "created_at",
        )
    )

    for offset in range(0, built.height, config.batch_size):
        yield built.slice(offset, config.batch_size)


def generate_reviews(
    config: ReviewConfig,
    shipments: pl.DataFrame,
    shipment_items: pl.DataFrame,
    return_items: pl.DataFrame,
    seed: int,
) -> pl.DataFrame:
    """Generate the complete reviews dataset.

    Args:
        config: Review configuration.
        shipments: The F008 shipments dataset.
        shipment_items: The F008 shipment items dataset.
        return_items: The F009 return items dataset.
        seed: Run seed.

    Returns:
        At most one row per eligible shipment item, keyed by sequential
        ``review_id``.
    """
    batches = list(iter_review_batches(config, shipments, shipment_items, return_items, seed))
    return pl.concat(batches, how="vertical") if batches else empty_frame(REVIEWS)
