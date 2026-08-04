"""Running one Healthcare stage for the platform."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import polars as pl

from eds.core.validation.issues import ValidationIssue
from eds.domains.healthcare.config import SimulationConfig
from eds.domains.healthcare.temporal.context import BusinessContext
from eds.domains.healthcare.temporal.day import DayOfBusiness, advance_day
from eds.domains.healthcare.temporal.rules import validate_temporal_history
from eds.domains.healthcare.validation.master_data import validate_master_data
from eds.domains.healthcare.validation.patient_validation import validate_patient_data
from eds.domains.healthcare.validation.provider_validation import validate_provider_data
from eds.domains.healthcare.validation.encounter_validation import validate_encounter_data
from eds.domains.healthcare.validation.billing_validation import validate_billing_data
from eds.platform.runtime.failure import FailureType
from eds.platform.scheduler.executor import StageExecutionError

__all__ = ["HEALTHCARE_STAGES", "StageValidation", "run_stage"]

type StageValidation = Callable[
    [SimulationConfig, Mapping[str, pl.DataFrame], Mapping[str, pl.DataFrame]],
    Sequence[ValidationIssue],
]

Frames = Mapping[str, pl.DataFrame]


def _master_data(
    config: SimulationConfig, world: Frames, today: Frames
) -> Sequence[ValidationIssue]:
    del today
    return validate_master_data(world)


def _patients(config: SimulationConfig, world: Frames, today: Frames) -> Sequence[ValidationIssue]:
    del today
    return validate_patient_data(
        world,
        config.patients.min_addresses,
        config.patients.max_addresses,
    )


def _providers(config: SimulationConfig, world: Frames, today: Frames) -> Sequence[ValidationIssue]:
    del today
    return validate_provider_data(world)


def _encounters(config: SimulationConfig, world: Frames, today: Frames) -> Sequence[ValidationIssue]:
    del today
    issues = list(validate_encounter_data(world))
    issues += validate_billing_data(world)
    return issues


HEALTHCARE_STAGES: dict[str, StageValidation] = {
    "master-data": _master_data,
    "patients": _patients,
    "providers": _providers,
    "encounters": _encounters,
}


def run_stage(
    stage: str,
    config: SimulationConfig,
    context: BusinessContext,
    upstream: Frames,
    history: Frames,
) -> DayOfBusiness:
    """Run one Healthcare stage for one business date."""
    checks = HEALTHCARE_STAGES.get(stage)
    if checks is None:
        raise StageExecutionError(
            f"Healthcare has no work for stage {stage!r}; it runs {sorted(HEALTHCARE_STAGES)}",
            FailureType.CONFIGURATION,
        )

    try:
        day = advance_day(stage, config, context, upstream, history)
    except (KeyError, ValueError) as exc:
        raise StageExecutionError(
            f"{stage} could not be generated: {exc}",
            FailureType.GENERATION,
            cause=repr(exc),
        ) from exc

    world = {**history, **upstream, **day.persisted}
    issues = list(checks(config, world, day.generated))
    issues += validate_temporal_history(world)
    _refuse(stage, issues)
    return day


def _refuse(stage: str, issues: Sequence[ValidationIssue]) -> None:
    """Reject a day whose work does not hold up."""
    if not issues:
        return
    shown = "; ".join(str(issue) for issue in issues[:5])
    more = f" (and {len(issues) - 5} more)" if len(issues) > 5 else ""
    raise StageExecutionError(
        f"{stage} failed validation with {len(issues)} issue(s): {shown}{more}",
        FailureType.VALIDATION,
    )
