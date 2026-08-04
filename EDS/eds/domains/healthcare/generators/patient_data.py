"""Orchestrator for the F002 patient data generation run."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.healthcare.domain.patient.schema import PATIENT_DATASETS
from eds.domains.healthcare.generators.patients.address_generator import generate_addresses
from eds.domains.healthcare.generators.patients.patient_generator import generate_patients
from eds.domains.healthcare.generators.patients.insurance_generator import generate_insurance
from eds.domains.healthcare.generators.patients.allergy_generator import generate_allergies

__all__ = ["PatientData", "REQUIRED_MASTER_DATASETS", "generate_patient_data"]

REQUIRED_MASTER_DATASETS: tuple[str, ...] = (
    "departments",
    "specialties",
    "insurance_plans",
    "facilities",
    "cities",
    "states",
    "countries",
)


@dataclass(frozen=True, slots=True)
class PatientData:
    """The complete set of generated patient datasets."""

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


def generate_patient_data(
    config: SimulationConfig, master_data: Mapping[str, pl.DataFrame]
) -> PatientData:
    """Generate every patient dataset from existing master data."""
    missing = [name for name in REQUIRED_MASTER_DATASETS if name not in master_data]
    if missing:
        raise KeyError(
            f"Missing master data required by F002: {missing}. "
            "Run `eds generate master-data` first."
        )

    seed = resolve_seed(config.platform.seed)

    patients = generate_patients(config.patients, master_data, seed)
    addresses = generate_addresses(config.patients, patients, master_data, seed)
    insurance = generate_insurance(config.patients, patients, master_data, seed)
    allergies = generate_allergies(config.patients, patients, seed)

    datasets: dict[str, pl.DataFrame] = {
        "patients": patients,
        "patient_addresses": addresses,
        "patient_insurance": insurance,
        "patient_allergies": allergies,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in PATIENT_DATASETS}
    return PatientData(datasets=ordered, seed=seed)
