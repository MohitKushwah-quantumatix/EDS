"""What one simulated day does to the Healthcare business."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

import polars as pl

from eds.core.random_streams import make_rng, resolve_seed
from eds.domains.healthcare.config import SimulationConfig
from eds.domains.healthcare.generators.encounter_data import generate_encounter_data
from eds.domains.healthcare.generators.patient_data import generate_patient_data
from eds.domains.healthcare.temporal.context import BusinessContext
from eds.domains.healthcare.temporal.identity import (
    disambiguate,
    identity_offsets,
    renumber,
    restate_key_codes,
)

__all__ = ["evolve_patients", "evolve_encounters"]

Frames = dict[str, pl.DataFrame]


def evolve_patients(
    config: SimulationConfig,
    context: BusinessContext,
    upstream: Mapping[str, pl.DataFrame],
    history: Mapping[str, pl.DataFrame],
) -> Frames:
    """Generate new patients for today.

    Args:
        config: Healthcare settings.
        context: The business date and the enterprise seed.
        upstream: What earlier stages produced.
        history: What the patients stage has produced before.

    Returns:
        The patient datasets for today, or empty if no new patients.
    """
    today = context.business_date
    produced: Frames = {}

    if config.evolution.new_patients_per_day <= 0:
        return produced

    patient_config = config.patients.model_copy(
        update={
            "patient_count": config.evolution.new_patients_per_day,
            "reference_date": today,
        }
    )
    patient_seed = resolve_seed(context.stream("patients"))
    patient_data = generate_patient_data(
        _seeded(config, patient_seed).model_copy(update={"patients": patient_config}),
        upstream,
    )
    # Renumber patient IDs to continue from history
    patient_offsets = identity_offsets(history, patient_data.datasets)
    patient_frames = renumber(dict(patient_data.datasets), patient_offsets)
    patient_frames = restate_key_codes(patient_frames)
    # Set registration date to today
    patient_frames["patients"] = patient_frames["patients"].with_columns(
        pl.lit(today).cast(pl.Date).alias("registration_date"),
    )
    produced.update(patient_frames)
    return produced


def evolve_encounters(
    config: SimulationConfig,
    context: BusinessContext,
    upstream: Mapping[str, pl.DataFrame],
    history: Mapping[str, pl.DataFrame],
) -> Frames:
    """Generate new encounters for today.

    Args:
        config: Healthcare settings.
        context: The business date and the enterprise seed.
        upstream: What earlier stages produced.
        history: What the encounters stage has produced before.

    Returns:
        The encounter datasets for today, or empty if no encounters.
    """
    today = context.business_date
    produced: Frames = {}

    existing_patients = history.get("patients")
    if existing_patients is None or existing_patients.is_empty():
        return produced

    # Select active patients based on active_patient_rate
    rng = make_rng(resolve_seed(context.stream("encounters")), "active_patients")
    sample_size = min(
        int(len(existing_patients) * config.evolution.active_patient_rate),
        len(existing_patients),
    )
    if sample_size > 0:
        active_patients = existing_patients.sample(sample_size, seed=rng.randint(0, 2**32))
    else:
        active_patients = existing_patients

    if active_patients.is_empty():
        return produced

    # Build encounter upstream with all required data
    encounter_upstream = dict(upstream)
    encounter_upstream["patients"] = existing_patients

    # Filter to only active patients for encounter generation
    encounter_upstream_filtered = dict(encounter_upstream)
    encounter_upstream_filtered["patients"] = active_patients

    encounter_seed = resolve_seed(context.stream("encounters"))
    encounter_data = generate_encounter_data(
        _seeded(config, encounter_seed),
        encounter_upstream_filtered,
        max_encounters_per_patient=config.evolution.max_daily_encounters,
    )
    # Renumber encounter IDs to continue from history
    encounter_offsets = identity_offsets(history, encounter_data.datasets)
    encounter_frames = renumber(dict(encounter_data.datasets), encounter_offsets)
    encounter_frames = restate_key_codes(encounter_frames)
    produced.update(encounter_frames)
    return produced


def _seeded(config: SimulationConfig, seed: int) -> SimulationConfig:
    """Return the settings with one day's seed bound to them."""
    return config.model_copy(update={"platform": config.platform.model_copy(update={"seed": seed})})
