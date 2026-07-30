"""Generator for the return items dataset.

A return item is a shipment item coming back. The lineage is preserved exactly:
``order_line_id``, ``product_id`` and ``quantity`` are carried across from the
shipment item untouched, so a return can always be traced back through the
shipment to the order line that sold the goods.

A customer does not always send back everything that arrived - a single damaged
item out of three is the common case - so each return brings back between one
and all of its shipment's items. Which ones is a draw; how many of each is not,
because partial-quantity returns are out of scope.
"""

from __future__ import annotations

from collections.abc import Iterator

import polars as pl

from eds.config import ReturnConfig
from eds.core.frames import empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.commerce.schema import RETURN_ITEMS

__all__ = ["generate_return_items", "iter_return_item_batches"]


def iter_return_item_batches(
    config: ReturnConfig, returns: pl.DataFrame, shipment_items: pl.DataFrame, seed: int
) -> Iterator[pl.DataFrame]:
    """Yield return items in batches, one per returned shipment item.

    Args:
        config: Return configuration.
        returns: The generated returns dataset.
        shipment_items: The F008 shipment items dataset.
        seed: Run seed.

    Yields:
        Frames matching the return items schema, ordered by return and then by
        shipment item.
    """
    if returns.is_empty():
        return

    candidates = (
        returns.select("return_id", "shipment_id", "created_at")
        .join(
            shipment_items.select(
                "shipment_item_id", "shipment_id", "order_line_id", "product_id", "quantity"
            ),
            on="shipment_id",
            how="inner",
        )
        .sort("return_id", "shipment_item_id")
    )
    if candidates.is_empty():
        return

    rng = make_rng(seed, "return_items")

    # Two vectors of draws: one per candidate item to shuffle it within its
    # return, and one per return to decide how many come back. Taking them up
    # front keeps the selection a pure expression pipeline.
    item_roll = [rng.random() for _ in range(candidates.height)]
    keep_roll = [rng.random() for _ in range(returns.height)]

    keep_share = returns.select("return_id").with_columns(
        pl.Series("keep_roll", keep_roll, dtype=pl.Float64)
    )

    built = (
        candidates.with_columns(pl.Series("item_roll", item_roll, dtype=pl.Float64))
        .join(keep_share, on="return_id", how="inner")
        .with_columns(
            pl.len().over("return_id").alias("item_count"),
            pl.col("item_roll").rank("ordinal").over("return_id").alias("item_rank"),
        )
        .with_columns(
            # At least one item always comes back, and at most all of them.
            (pl.col("keep_roll") * pl.col("item_count"))
            .floor()
            .cast(pl.Int64)
            .clip(upper_bound=pl.col("item_count") - 1)
            .add(1)
            .alias("keep_count")
        )
        .filter(pl.col("item_rank") <= pl.col("keep_count"))
        .sort("return_id", "shipment_item_id")
        .with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("return_item_id"))
        .select(
            "return_item_id",
            "return_id",
            "shipment_item_id",
            # Lineage carried across untouched: the return can always be traced
            # back to the order line that sold the goods.
            "order_line_id",
            "product_id",
            "quantity",
            "created_at",
        )
    )

    for offset in range(0, built.height, config.batch_size):
        yield built.slice(offset, config.batch_size)


def generate_return_items(
    config: ReturnConfig, returns: pl.DataFrame, shipment_items: pl.DataFrame, seed: int
) -> pl.DataFrame:
    """Generate the complete return items dataset.

    Args:
        config: Return configuration.
        returns: The generated returns dataset.
        shipment_items: The F008 shipment items dataset.
        seed: Run seed.

    Returns:
        One row per returned shipment item, keyed by sequential
        ``return_item_id``. Every return carries at least one item.
    """
    batches = list(iter_return_item_batches(config, returns, shipment_items, seed))
    return pl.concat(batches, how="vertical") if batches else empty_frame(RETURN_ITEMS)
