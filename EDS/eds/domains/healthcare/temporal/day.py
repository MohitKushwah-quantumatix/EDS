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
from eds.domains.healthcare.generators.additional.additional_data import generate_additional_data
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
    "patients": (
        *patient_dataset_names(),
        "immunizations",
        "patient_emergency_contacts",
    ),
    "providers": provider_dataset_names(),
    "encounters": (
        *encounter_dataset_names(),
        *billing_dataset_names(),
        "lab_results",
        "radiology_reports",
        "medication_administration",
        "admissions",
        "discharge_summaries",
        "referrals",
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

    settings = config.model_copy(
        update={
            "patients": config.patients.model_copy(update={"reference_date": context.business_date}),
            "providers": config.providers.model_copy(update={"reference_date": context.business_date}),
            "encounters": config.encounters.model_copy(update={"reference_date": context.business_date}),
            "billing": config.billing.model_copy(update={"reference_date": context.business_date}),
        }
    )
    if _founding(stage, history):
        generated = _found(stage, settings, upstream)
        return DayOfBusiness(generated, generated, settings, is_founding=True)

    generated = _evolve(stage, settings, context, upstream, history)
    return DayOfBusiness(generated, merge_history(history, generated), settings, is_founding=False)


def _founding(stage: str, history: Mapping[str, pl.DataFrame]) -> bool:
    """Report whether this stage has anything to continue."""
    return all(name not in history or history[name].is_empty() for name in STAGE_DATASETS[stage])


def _found(stage: str, config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]) -> Frames:
    """Build a stage's datasets from nothing."""
    match stage:
        case "master-data":
            return dict(generate_master_data(config).datasets)
        case "patients":
            data = generate_patient_data(config, upstream)
            additional = _generate_patient_additional(
                config, upstream, patients=dict(data.datasets).get("patients")
            )
            return {**dict(data.datasets), **additional}
        case "providers":
            return dict(generate_provider_data(config, upstream).datasets)
        case _:
            data = generate_encounter_data(config, upstream)
            additional = _generate_encounter_additional(
                config, upstream, encounters=dict(data.datasets).get("encounters")
            )
            return {**dict(data.datasets), **additional}


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
            evolved = evolve_patients(config, context, upstream, history)
            if not evolved:
                return {}
            additional = _generate_patient_additional(
                config, {**upstream, **history}, patients=evolved.get("patients")
            )
            return {**evolved, **additional}
        case "providers":
            return {}  # Providers are static after founding
        case _:
            evolved = evolve_encounters(config, context, upstream, history)
            if not evolved:
                return {}
            additional = _generate_encounter_additional(
                config, {**upstream, **history}, encounters=evolved.get("encounters")
            )
            return {**evolved, **additional}


def _generate_patient_additional(
    config: SimulationConfig,
    upstream: Mapping[str, pl.DataFrame],
    patients: pl.DataFrame | None = None,
) -> Frames:
    from eds.domains.healthcare.generators.additional.immunizations import generate_immunizations
    from eds.domains.healthcare.generators.additional.patient_emergency_contacts import generate_patient_emergency_contacts

    patients_df = patients if patients is not None else upstream.get("patients")
    if patients_df is None or patients_df.is_empty():
        return {
            "immunizations": pl.DataFrame(schema={
                "immunization_id": pl.Int64(),
                "patient_id": pl.Int64(),
                "vaccine_name": pl.String(),
                "dose_number": pl.Int64(),
                "administered_at": pl.Date(),
                "administered_by": pl.Int64(),
                "site": pl.String(),
                "lot_number": pl.String(),
            }),
            "patient_emergency_contacts": pl.DataFrame(schema={
                "contact_id": pl.Int64(),
                "patient_id": pl.Int64(),
                "contact_name": pl.String(),
                "relationship": pl.String(),
                "phone_number": pl.String(),
                "email": pl.String(),
                "is_primary": pl.Boolean(),
            }),
        }

    return {
        "immunizations": generate_immunizations(config, {**upstream, "patients": patients_df}),
        "patient_emergency_contacts": generate_patient_emergency_contacts(config, {**upstream, "patients": patients_df}),
    }


def _generate_encounter_additional(
    config: SimulationConfig,
    upstream: Mapping[str, pl.DataFrame],
    encounters: pl.DataFrame | None = None,
) -> Frames:
    from eds.domains.healthcare.generators.additional.admissions import generate_admissions
    from eds.domains.healthcare.generators.additional.discharge_summaries import generate_discharge_summaries
    from eds.domains.healthcare.generators.additional.lab_results import generate_lab_results
    from eds.domains.healthcare.generators.additional.medication_administration import generate_medication_administration
    from eds.domains.healthcare.generators.additional.radiology_reports import generate_radiology_reports
    from eds.domains.healthcare.generators.additional.referrals import generate_referrals

    encounters_df = encounters if encounters is not None else upstream.get("encounters")
    if encounters_df is None or encounters_df.is_empty():
        return {
            "lab_results": pl.DataFrame(schema={
                "lab_result_id": pl.Int64(),
                "encounter_id": pl.Int64(),
                "patient_id": pl.Int64(),
                "test_name": pl.String(),
                "result_value": pl.String(),
                "unit": pl.String(),
                "normal_range": pl.String(),
                "result_status": pl.String(),
                "reported_at": pl.Date(),
            }),
            "radiology_reports": pl.DataFrame(schema={
                "radiology_id": pl.Int64(),
                "encounter_id": pl.Int64(),
                "patient_id": pl.Int64(),
                "modality": pl.String(),
                "body_part": pl.String(),
                "findings": pl.String(),
                "impression": pl.String(),
                "performed_at": pl.Date(),
                "radiologist_id": pl.Int64(),
            }),
            "medication_administration": pl.DataFrame(schema={
                "administration_id": pl.Int64(),
                "encounter_id": pl.Int64(),
                "medication_id": pl.Int64(),
                "dose": pl.String(),
                "route": pl.String(),
                "administered_at": pl.Date(),
                "administered_by": pl.Int64(),
            }),
            "admissions": pl.DataFrame(schema={
                "admission_id": pl.Int64(),
                "encounter_id": pl.Int64(),
                "patient_id": pl.Int64(),
                "admission_type": pl.String(),
                "admission_source": pl.String(),
                "admitted_at": pl.Date(),
                "discharged_at": pl.Date(),
                "ward": pl.String(),
                "bed_number": pl.String(),
                "attending_physician": pl.Int64(),
            }),
            "discharge_summaries": pl.DataFrame(schema={
                "discharge_id": pl.Int64(),
                "encounter_id": pl.Int64(),
                "patient_id": pl.Int64(),
                "discharge_diagnosis": pl.String(),
                "discharge_instructions": pl.String(),
                "follow_up_date": pl.Date(),
                "follow_up_physician": pl.Int64(),
                "discharge_disposition": pl.String(),
            }),
            "referrals": pl.DataFrame(schema={
                "referral_id": pl.Int64(),
                "patient_id": pl.Int64(),
                "encounter_id": pl.Int64(),
                "referring_provider": pl.Int64(),
                "referred_to_provider": pl.Int64(),
                "referral_reason": pl.String(),
                "referral_date": pl.Date(),
                "status": pl.String(),
            }),
        }

    encounter_upstream = {**upstream, "encounters": encounters_df}
    return {
        "lab_results": generate_lab_results(config, encounter_upstream),
        "radiology_reports": generate_radiology_reports(config, encounter_upstream),
        "medication_administration": generate_medication_administration(config, encounter_upstream),
        "admissions": generate_admissions(config, encounter_upstream),
        "discharge_summaries": generate_discharge_summaries(config, encounter_upstream),
        "referrals": generate_referrals(config, encounter_upstream),
    }
