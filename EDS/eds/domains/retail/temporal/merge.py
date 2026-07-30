"""Joining one day's work to everything that came before it.

There is one rule per temporality and no rule anywhere else, which is what
makes "never rewrite history" a property of the code rather than a hope:

* **Static** keeps history and discards the day's version. Nothing written on
  the founding day is ever written again.
* **Append-only** puts history first and the day's rows after it. The
  historical rows keep their order and their contents, so the file's existing
  prefix is byte for byte what it was.
* **Mutable snapshot** takes the day's version whole. It is a picture of now,
  and yesterday's picture is not history, it is a stale picture.
* **Slowly changing** keeps every historical row that the day did not touch,
  takes the day's version of the ones it did, and sorts by identity so the
  result reads the same however it was assembled.

**A founding day merges nothing.** With no history there is nothing to join
to, so the day's output is returned exactly as the generators produced it -
which is what keeps a one-day platform run byte-identical to ``eds generate``.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.domains.retail.temporal.datasets import retail_dataset
from eds.domains.retail.temporal.temporality import Temporality, temporality_of

__all__ = ["merge_dataset", "merge_history"]


def merge_dataset(name: str, history: pl.DataFrame | None, produced: pl.DataFrame) -> pl.DataFrame:
    """Join one dataset's new rows to its history.

    Args:
        name: Dataset name.
        history: What already exists, or ``None`` on the founding day.
        produced: What today generated.

    Returns:
        The dataset as it now stands.

    Raises:
        KeyError: If the dataset is not one Retail declares, or has not
            declared a temporality.
    """
    if history is None or history.is_empty():
        return produced

    match temporality_of(name):
        case Temporality.STATIC:
            return history
        case Temporality.MUTABLE_SNAPSHOT:
            return produced
        case Temporality.APPEND_ONLY:
            if produced.is_empty():
                return history
            return pl.concat([history, produced.select(history.columns)], how="vertical")
        case Temporality.SLOWLY_CHANGING:
            if produced.is_empty():
                return history
            key = retail_dataset(name).primary_key
            kept = history.join(produced.select(key), on=key, how="anti")
            return pl.concat([kept, produced.select(history.columns)], how="vertical").sort(key)


def merge_history(
    history: Mapping[str, pl.DataFrame], produced: Mapping[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Join a day's datasets to their histories.

    Args:
        history: What already exists, keyed by dataset name. A name absent
            here has no history.
        produced: What today generated.

    Returns:
        Every dataset in ``produced``, as it now stands.

    Raises:
        KeyError: If a dataset is not one Retail declares, or has not declared
            a temporality.
    """
    return {name: merge_dataset(name, history.get(name), frame) for name, frame in produced.items()}
