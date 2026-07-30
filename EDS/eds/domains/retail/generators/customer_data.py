"""Orchestrator for the F002 customer generation run.

Customer data is generated **on top of** the F001 master data, which is passed
in rather than regenerated. Datasets are produced in dependency order:
customers first, then the three datasets that reference them.

The whole run is a pure function of ``(configuration, seed, geography)``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.retail.domain.customer.schema import CUSTOMER_DATASETS
from eds.domains.retail.generators.customers.address_generator import generate_addresses
from eds.domains.retail.generators.customers.customer_generator import (
    CustomerGeography,
    generate_customers,
)
from eds.domains.retail.generators.customers.loyalty_generator import generate_loyalty
from eds.domains.retail.generators.customers.preference_generator import generate_preferences

__all__ = ["CustomerData", "REQUIRED_MASTER_DATASETS", "generate_customer_data"]

#: The F001 datasets F002 needs in order to place customers geographically.
REQUIRED_MASTER_DATASETS: tuple[str, ...] = ("countries", "states", "cities")


@dataclass(frozen=True, slots=True)
class CustomerData:
    """The complete set of generated customer datasets.

    Attributes:
        datasets: Dataset name to frame, in dependency order.
        seed: The resolved seed the run used.
    """

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        """Return one dataset by name.

        Args:
            name: Dataset name, such as ``"customer_addresses"``.

        Returns:
            The generated frame.

        Raises:
            KeyError: If the dataset was not generated.
        """
        try:
            return self.datasets[name]
        except KeyError:
            raise KeyError(
                f"Unknown dataset {name!r}. Generated: {sorted(self.datasets)}"
            ) from None

    def __iter__(self) -> Iterator[tuple[str, pl.DataFrame]]:
        """Iterate over ``(name, frame)`` pairs in dependency order."""
        return iter(self.datasets.items())

    def row_counts(self) -> dict[str, int]:
        """Return the row count of every dataset, keyed by name."""
        return {name: frame.height for name, frame in self.datasets.items()}

    def total_rows(self) -> int:
        """Return the total number of rows across every dataset."""
        return sum(frame.height for frame in self.datasets.values())


def generate_customer_data(
    config: SimulationConfig, master_data: Mapping[str, pl.DataFrame]
) -> CustomerData:
    """Generate every customer dataset from existing master data.

    Args:
        config: The complete run configuration.
        master_data: The F001 datasets, which must include the entries in
            :data:`REQUIRED_MASTER_DATASETS`.

    Returns:
        The generated bundle, including the resolved seed.

    Raises:
        KeyError: If a required master dataset is absent.
        ValueError: If a required master dataset is empty.
    """
    missing = [name for name in REQUIRED_MASTER_DATASETS if name not in master_data]
    if missing:
        raise KeyError(
            f"Missing master data required by F002: {missing}. "
            "Run `eds generate master-data` first."
        )

    seed = resolve_seed(config.platform.seed)
    locale = config.platform.locale
    settings = config.customers

    geography = CustomerGeography.from_frames(
        master_data["cities"], master_data["states"], master_data["countries"]
    )

    customers = generate_customers(settings, geography, seed, locale)
    addresses = generate_addresses(settings, geography, seed, locale)
    preferences = generate_preferences(settings, geography, seed)
    loyalty = generate_loyalty(settings, customers, seed)

    datasets: dict[str, pl.DataFrame] = {
        "customers": customers,
        "customer_addresses": addresses,
        "customer_preferences": preferences,
        "customer_loyalty": loyalty,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in CUSTOMER_DATASETS}
    return CustomerData(datasets=ordered, seed=seed)
