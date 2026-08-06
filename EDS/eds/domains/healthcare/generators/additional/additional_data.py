"""Orchestrator for additional healthcare datasets."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.healthcare.domain.additional.schema import ADDITIONAL_DATASETS
from eds.domains.healthcare.generators.additional.lab_results import generate_lab_results
from eds.domains.healthcare.generators.additional.radiology_reports import generate_radiology_reports
from eds.domains.healthcare.generators.additional.medication_administration import generate_medication_administration
from eds.domains.healthcare.generators.additional.admissions import generate_admissions
from eds.domains.healthcare.generators.additional.discharge_summaries import generate_discharge_summaries
from eds.domains.healthcare.generators.additional.immunizations import generate_immunizations
from eds.domains.healthcare.generators.additional.referrals import generate_referrals
from eds.domains.healthcare.generators.additional.patient_emergency_contacts import generate_patient_emergency_contacts

__all__ = ["AdditionalData", "generate_additional_data"]


@dataclass(frozen=True, slots=True)
class AdditionalData:
    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        try:
            return self.datasets[name]
        except KeyError:
            raise KeyError(
                f"Unknown dataset {name!r}. Generated: {sorted(self.datasets)}"
            ) from None

    def __iter__(self) -> Iterator[tuple[str, pl.DataFrame]]:
        return iter(self.datasets.items())


def generate_additional_data(
    config: SimulationConfig,
    upstream: Mapping[str, pl.DataFrame],
) -> AdditionalData:
    seed = resolve_seed(config.platform.seed)

    lab_results = generate_lab_results(config, upstream)
    radiology_reports = generate_radiology_reports(config, upstream)
    medication_administration = generate_medication_administration(config, upstream)
    admissions = generate_admissions(config, upstream)
    discharge_summaries = generate_discharge_summaries(config, upstream)
    immunizations = generate_immunizations(config, upstream)
    referrals = generate_referrals(config, upstream)
    patient_emergency_contacts = generate_patient_emergency_contacts(config, upstream)

    datasets: dict[str, pl.DataFrame] = {
        "lab_results": lab_results,
        "radiology_reports": radiology_reports,
        "medication_administration": medication_administration,
        "admissions": admissions,
        "discharge_summaries": discharge_summaries,
        "immunizations": immunizations,
        "referrals": referrals,
        "patient_emergency_contacts": patient_emergency_contacts,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in ADDITIONAL_DATASETS}
    return AdditionalData(datasets=ordered, seed=seed)
