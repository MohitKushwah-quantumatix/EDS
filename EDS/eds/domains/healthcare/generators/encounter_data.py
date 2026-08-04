"""Orchestrator for the F004-F010 encounter and billing generation run."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.healthcare.domain.encounter.schema import ENCOUNTER_DATASETS
from eds.domains.healthcare.domain.billing.schema import BILLING_DATASETS
from eds.domains.healthcare.generators.encounters.encounter_generator import generate_encounters
from eds.domains.healthcare.generators.encounters.appointment_generator import generate_appointments
from eds.domains.healthcare.generators.encounters.vitals_generator import generate_vitals
from eds.domains.healthcare.generators.encounters.medication_generator import generate_medications
from eds.domains.healthcare.generators.encounters.diagnosis_generator import generate_diagnoses
from eds.domains.healthcare.generators.encounters.procedure_generator import generate_procedures
from eds.domains.healthcare.generators.billing.billing_generator import generate_billing
from eds.domains.healthcare.generators.billing.claim_generator import generate_claims

__all__ = ["EncounterData", "REQUIRED_MASTER_DATASETS", "generate_encounter_data"]

REQUIRED_MASTER_DATASETS: tuple[str, ...] = (
    "patients",
    "providers",
    "departments",
    "specialties",
    "medications",
    "diagnosis_codes",
    "procedure_codes",
    "billing_codes",
    "insurance_plans",
    "room_types",
    "facilities",
)


@dataclass(frozen=True, slots=True)
class EncounterData:
    """The complete set of generated encounter and billing datasets."""

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

    def row_counts(self) -> dict[str, int]:
        return {name: frame.height for name, frame in self.datasets.items()}

    def total_rows(self) -> int:
        return sum(frame.height for frame in self.datasets.values())


def generate_encounter_data(
    config: SimulationConfig,
    upstream: Mapping[str, pl.DataFrame],
    max_encounters_per_patient: int = 5,
) -> EncounterData:
    """Generate every encounter and billing dataset from existing upstream data.

    Args:
        config: The complete run configuration.
        upstream: The F001, F002, and F003 datasets, which must include the
            entries in :data:`REQUIRED_MASTER_DATASETS`.
        max_encounters_per_patient: Maximum encounters per patient per day.

    Returns:
        The generated bundle, including the resolved seed.
    """
    missing = [name for name in REQUIRED_MASTER_DATASETS if name not in upstream]
    if missing:
        raise KeyError(
            f"Missing upstream data required by F004-F010: {missing}. "
            "Run `eds generate patients` and `eds generate providers` first."
        )

    seed = resolve_seed(config.platform.seed)

    encounters = generate_encounters(
        config.encounters, upstream, seed, max_encounters_per_patient
    )
    appointments = generate_appointments(config.encounters, encounters, upstream, seed)
    vitals = generate_vitals(config.encounters, encounters, upstream, seed)
    medications = generate_medications(config.encounters, encounters, upstream, seed)
    diagnoses = generate_diagnoses(config.encounters, encounters, upstream, seed)
    procedures = generate_procedures(config.encounters, encounters, upstream, seed)
    billing = generate_billing(config.billing, encounters, upstream, seed)
    claims = generate_claims(config.billing, billing, upstream, seed)

    datasets: dict[str, pl.DataFrame] = {
        "encounters": encounters,
        "appointments": appointments,
        "vitals": vitals,
        "medications_prescribed": medications,
        "diagnoses": diagnoses,
        "procedures": procedures,
        "billing": billing,
        "claims": claims,
    }

    encounter_ordered = {dataset.name: datasets[dataset.name] for dataset in ENCOUNTER_DATASETS}
    billing_ordered = {dataset.name: datasets[dataset.name] for dataset in BILLING_DATASETS}
    all_ordered = {**encounter_ordered, **billing_ordered}
    return EncounterData(datasets=all_ordered, seed=seed)
