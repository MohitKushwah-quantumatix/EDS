"""Orchestrator for the F003.1 customer journey generation run.

Journey data is generated on top of the F001 geography and F002 customer
datasets, which are passed in rather than regenerated. Personas come first,
because a session's shape is entirely determined by its customer's persona.

The whole run is a pure function of ``(configuration, seed, upstream data)``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.retail.domain.journey.schema import JOURNEY_DATASETS
from eds.domains.retail.generators.journey.persona_generator import generate_personas
from eds.domains.retail.generators.journey.session_generator import (
    SessionLocations,
    generate_sessions,
)

__all__ = ["REQUIRED_UPSTREAM_DATASETS", "JourneyData", "generate_journey_data"]

#: The datasets F003.1 needs from earlier features.
REQUIRED_UPSTREAM_DATASETS: tuple[str, ...] = (
    "countries",
    "states",
    "cities",
    "customers",
    "customer_addresses",
)


@dataclass(frozen=True, slots=True)
class JourneyData:
    """The complete set of generated journey datasets.

    Attributes:
        datasets: Dataset name to frame, in dependency order.
        seed: The resolved seed the run used.
    """

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        """Return one dataset by name.

        Args:
            name: Dataset name, such as ``"sessions"``.

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


def generate_journey_data(
    config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]
) -> JourneyData:
    """Generate personas and sessions from existing customer and master data.

    Args:
        config: The complete run configuration.
        upstream: The F001 and F002 datasets, which must include the entries
            in :data:`REQUIRED_UPSTREAM_DATASETS`.

    Returns:
        The generated bundle, including the resolved seed.

    Raises:
        KeyError: If a required upstream dataset is absent.
        ValueError: If a required upstream dataset is empty or a customer has
            no primary address.
    """
    missing = [name for name in REQUIRED_UPSTREAM_DATASETS if name not in upstream]
    if missing:
        raise KeyError(
            f"Missing upstream data required by F003.1: {missing}. "
            "Run `eds generate master-data` and `eds generate customers` first."
        )

    seed = resolve_seed(config.platform.seed)
    customers = upstream["customers"]

    locations = SessionLocations.from_frames(upstream["customer_addresses"], upstream["countries"])
    personas = generate_personas(config.customers, config.journey, customers, seed)
    sessions = generate_sessions(
        config.customers, config.journey, personas, customers, locations, seed
    )

    datasets: dict[str, pl.DataFrame] = {
        "customer_personas": personas,
        "sessions": sessions,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in JOURNEY_DATASETS}
    return JourneyData(datasets=ordered, seed=seed)
