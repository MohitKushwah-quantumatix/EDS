"""Orchestrator for the F003.2 browsing generation run.

Browsing extends sessions that already exist: category views come first, then
searches attach to those views. Both are generated on top of the F001, F002
and F003.1 datasets, which are passed in rather than regenerated.

The whole run is a pure function of ``(configuration, seed, upstream data)``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.retail.domain.journey.schema import BROWSING_DATASETS
from eds.domains.retail.generators.journey.category_generator import (
    CategoryCatalog,
    generate_category_views,
)
from eds.domains.retail.generators.journey.search_generator import generate_searches

__all__ = ["REQUIRED_BROWSING_DATASETS", "BrowsingData", "generate_browsing_data"]

#: The datasets F003.2 needs from earlier features.
REQUIRED_BROWSING_DATASETS: tuple[str, ...] = (
    "categories",
    "customers",
    "customer_personas",
    "sessions",
)


@dataclass(frozen=True, slots=True)
class BrowsingData:
    """The complete set of generated browsing datasets.

    Attributes:
        datasets: Dataset name to frame, in dependency order.
        seed: The resolved seed the run used.
    """

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        """Return one dataset by name.

        Args:
            name: Dataset name, such as ``"search_history"``.

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


def generate_browsing_data(
    config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]
) -> BrowsingData:
    """Generate category views and searches for existing sessions.

    Args:
        config: The complete run configuration.
        upstream: The earlier datasets, which must include the entries in
            :data:`REQUIRED_BROWSING_DATASETS`.

    Returns:
        The generated bundle, including the resolved seed.

    Raises:
        KeyError: If a required upstream dataset is absent, or a session names
            a persona with no browsing profile.
        ValueError: If the categories dataset is empty.
    """
    missing = [name for name in REQUIRED_BROWSING_DATASETS if name not in upstream]
    if missing:
        raise KeyError(
            f"Missing upstream data required by F003.2: {missing}. "
            "Run `eds generate master-data`, `eds generate customers`, and "
            "`eds generate journey` first."
        )

    seed = resolve_seed(config.platform.seed)
    settings = config.browsing
    sessions = upstream["sessions"]

    catalog = CategoryCatalog.from_frame(upstream["categories"])
    category_views = generate_category_views(settings, sessions, catalog, seed)
    searches = generate_searches(settings, sessions, category_views, catalog, seed)

    datasets: dict[str, pl.DataFrame] = {
        "category_views": category_views,
        "search_history": searches,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in BROWSING_DATASETS}
    return BrowsingData(datasets=ordered, seed=seed)
