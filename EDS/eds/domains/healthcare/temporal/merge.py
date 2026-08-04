"""How a Healthcare day joins history without disturbing it.

Every dataset that changes over time has a rule for how a day's rows combine
with what is already on disk. The rule is derived from the dataset's
temporality, which is declared once in
:mod:`~eds.domains.healthcare.temporal.temporality` and used here without
any second list to keep in step.

Four temporality kinds are recognised:

* **APPEND_ONLY**: The day's rows are concatenated after history. Nothing
  already on disk is touched. This is the rule for encounters, appointments,
  vitals, medications, diagnoses, procedures, billing, and claims.
* **MUTABLE_SNAPSHOT**: The day replaces history entirely. The snapshot is
  what the world looks like at the end of the day, and the day's rows are the
  whole truth. This is the rule for patient_addresses, patient_insurance,
  and provider_departments.
* **SLOWLY_CHANGING**: The day's rows are concatenated, but a new row for an
  existing entity may supersede the old one. This is the rule for patients,
  providers, and provider_specialties.
* **STATIC**: History is returned unchanged. This is the rule for master data
  such as departments, specialties, facilities, and geography.
"""

from __future__ import annotations

from typing import Mapping

import polars as pl

from eds.domains.healthcare.temporal.temporality import Temporality, temporality_of

__all__ = ["merge_dataset", "merge_history"]


def merge_dataset(
    name: str, history: pl.DataFrame | None, produced: pl.DataFrame
) -> pl.DataFrame:
    """Merge a day's rows into history.

    Args:
        name: Dataset name.
        history: What already exists, or ``None``.
        produced: The day's rows.

    Returns:
        The merged history.
    """
    kind = temporality_of(name)
    if history is None or history.is_empty():
        return produced
    if kind is Temporality.APPEND_ONLY:
        return pl.concat([history, produced], how="vertical")
    if kind is Temporality.MUTABLE_SNAPSHOT:
        return produced
    if kind is Temporality.STATIC:
        return history
    if kind is Temporality.SLOWLY_CHANGING:
        return pl.concat([history, produced], how="vertical")
    raise ValueError(f"Unknown temporality: {kind}")


def merge_history(
    history: Mapping[str, pl.DataFrame], produced: Mapping[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Merge a day's datasets into history.

    Args:
        history: What already exists, keyed by dataset name.
        produced: The day's datasets, keyed by dataset name.

    Returns:
        The merged history, keyed by dataset name.
    """
    result = {}
    for name, day_frame in produced.items():
        hist = history.get(name)
        result[name] = merge_dataset(name, hist, day_frame)
    return result
