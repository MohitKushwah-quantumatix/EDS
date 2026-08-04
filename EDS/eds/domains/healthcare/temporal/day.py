"""One business day of Healthcare, whichever day it is."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl

from eds.domains.healthcare.config import SimulationConfig
from eds.domains.healthcare.domain.billing.schema import billing_dataset_names
from eds.domains.healthcare.domain.encounter.schema import encounter_dataset_names
from eds.domains.healthcare.domain.master_data import dataset_names as master_dataset_names
from eds.domains.healthcare.domain.patient.schema import patient_dataset_names
from eds.domains.healthcare.domain.provider.schema import provider_dataset_names
from eds.domains.healthcare.generators.encounter_data import generate_encounter_data
from eds.domains.healthcare.generators.master_data import generate_master_data
from eds.domains.healthcare.generators.patient_data import generate_patient_data
from eds.domains.healthcare.generators.provider_data import generate_provider_data
from eds.domains.healthcare.temporal.context import BusinessContext
from eds.domains.healthcare.temporal.evolution import evolve_encounters, evolve_patients
from eds.domains.healthcare.temporal.merge import merge_history

__all__ = [
    "HISTORY_READ",
    "HEALTHCARE_STAGE_NAMES",
    "STAGE_DATASETS",
    "DayOfBusiness",
    "advance_day",
]

Frames = dict[str, pl.DataFrame]

#: What each Healthcare stage produces, in dependency order.
STAGE_DATASETS: Final[Mapping[str, tuple[str, ...]]] = {
    "master-data": master_dataset_names(),
    "patients": patient_dataset_names(),
    "providers": provider_dataset_names(),
    "encounters": (
        *encounter_dataset_names(),
        *billing_dataset_names(),
    ),
}

#: The four stages, in execution order.
HEALTHCARE_STAGE_NAMES: Final[tuple[str, ...]] = tuple(STAGE_DATASETS)

#: What each stage must be shown of the past.
HISTORY_READ: Final[Mapping[str, tuple[str, ...]]] = {
    "master-data": STAGE_DATASETS["master-data"],
    "patients": STAGE_DATASETS["patients"],
    "providers": STAGE_DATASETS["providers"],
    "encounters": STAGE_DATASETS["encounters"],
}


@dataclass(frozen=True, slots=True)
class DayOfBusiness:
    """What one stage did on one business date."""

    generated: Mapping[str, pl.DataFrame]
    persisted: Mapping[str, pl.DataFrame]
    settings: SimulationConfig
    is_founding: bool


def advance_day(
    stage: str,
    config: SimulationConfig,
    context: BusinessContext,
    upstream: Mapping[str, pl.DataFrame],
    history: Mapping[str, pl.DataFrame],
) -> DayOfBusiness:
    """Run one Healthcare stage for one business date."""
    if stage not in STAGE_DATASETS:
        raise KeyError(f"Healthcare runs no stage named {stage!r}; it runs {HEALTHCARE_STAGE_NAMES}")

    if _founding(stage, history):
        generated = _found(stage, config, upstream)
        return DayOfBusiness(generated, generated, config, is_founding=True)

    generated = _evolve(stage, config, context, upstream, history)
    return DayOfBusiness(generated, merge_history(history, generated), config, is_founding=False)


def _founding(stage: str, history: Mapping[str, pl.DataFrame]) -> bool:
    """Report whether this stage has anything to continue."""
    return all(name not in history or history[name].is_empty() for name in STAGE_DATASETS[stage])


def _found(stage: str, config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]) -> Frames:
    """Build a stage's datasets from nothing."""
    match stage:
        case "master-data":
            return dict(generate_master_data(config).datasets)
        case "patients":
            return dict(generate_patient_data(config, upstream).datasets)
        case "providers":
            return dict(generate_provider_data(config, upstream).datasets)
        case _:
            return _found_encounters(config, upstream)


def _found_encounters(config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]) -> Frames:
    """Build the encounter and billing datasets from nothing."""
    return dict(generate_encounter_data(config, upstream).datasets)


def _evolve(
    stage: str,
    config: SimulationConfig,
    context: BusinessContext,
    upstream: Mapping[str, pl.DataFrame],
    history: Mapping[str, pl.DataFrame],
) -> Frames:
    """Add one day to a stage's history."""
    match stage:
        case "master-data":
            return {}  # Master data is static, no daily changes
        case "patients":
            return evolve_patients(config, context, upstream, history)
        case "providers":
            return {}  # Providers are static after founding
        case _:
            return evolve_encounters(config, context, upstream, history)
