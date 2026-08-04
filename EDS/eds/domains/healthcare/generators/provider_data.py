"""Orchestrator for the F003 provider data generation run."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.domains.healthcare.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.healthcare.domain.provider.schema import PROVIDER_DATASETS
from eds.domains.healthcare.generators.providers.provider_generator import generate_providers
from eds.domains.healthcare.generators.providers.department_generator import generate_provider_departments
from eds.domains.healthcare.generators.providers.specialty_generator import generate_provider_specialties

__all__ = ["ProviderData", "REQUIRED_MASTER_DATASETS", "generate_provider_data"]

REQUIRED_MASTER_DATASETS: tuple[str, ...] = ("departments", "specialties", "facilities")


@dataclass(frozen=True, slots=True)
class ProviderData:
    """The complete set of generated provider datasets."""

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


def generate_provider_data(
    config: SimulationConfig, master_data: Mapping[str, pl.DataFrame]
) -> ProviderData:
    """Generate every provider dataset from existing master data."""
    missing = [name for name in REQUIRED_MASTER_DATASETS if name not in master_data]
    if missing:
        raise KeyError(
            f"Missing master data required by F003: {missing}. "
            "Run `eds generate master-data` first."
        )

    seed = resolve_seed(config.platform.seed)

    providers = generate_providers(config.providers, master_data, seed)
    provider_departments = generate_provider_departments(config.providers, providers, master_data, seed)
    provider_specialties = generate_provider_specialties(config.providers, providers, master_data, seed)

    datasets: dict[str, pl.DataFrame] = {
        "providers": providers,
        "provider_departments": provider_departments,
        "provider_specialties": provider_specialties,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in PROVIDER_DATASETS}
    return ProviderData(datasets=ordered, seed=seed)
