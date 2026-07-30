"""Orchestrator for the F003.3 engagement generation run.

Engagement extends browsing that already exists: product views come first,
then wishlists are saved from those views. Both are generated on top of the
F001, F002, F003.1 and F003.2 datasets, which are passed in rather than
regenerated.

The whole run is a pure function of ``(configuration, seed, upstream data)``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.retail.domain.journey.schema import ENGAGEMENT_DATASETS
from eds.domains.retail.generators.journey.product_view_generator import (
    ProductCatalog,
    generate_product_views,
)
from eds.domains.retail.generators.journey.wishlist_generator import generate_wishlists

__all__ = ["REQUIRED_ENGAGEMENT_DATASETS", "EngagementData", "generate_engagement_data"]

#: The datasets F003.3 needs from earlier features.
REQUIRED_ENGAGEMENT_DATASETS: tuple[str, ...] = (
    "categories",
    "products",
    "customers",
    "customer_personas",
    "sessions",
    "category_views",
    "search_history",
)


@dataclass(frozen=True, slots=True)
class EngagementData:
    """The complete set of generated engagement datasets.

    Attributes:
        datasets: Dataset name to frame, in dependency order.
        seed: The resolved seed the run used.
    """

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        """Return one dataset by name.

        Args:
            name: Dataset name, such as ``"wishlists"``.

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


def generate_engagement_data(
    config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]
) -> EngagementData:
    """Generate product views and wishlists for existing browsing activity.

    Args:
        config: The complete run configuration.
        upstream: The earlier datasets, which must include the entries in
            :data:`REQUIRED_ENGAGEMENT_DATASETS`.

    Returns:
        The generated bundle, including the resolved seed.

    Raises:
        KeyError: If a required upstream dataset is absent, or a session names
            a persona with no engagement profile.
        ValueError: If the categories or products dataset is empty.
    """
    missing = [name for name in REQUIRED_ENGAGEMENT_DATASETS if name not in upstream]
    if missing:
        raise KeyError(
            f"Missing upstream data required by F003.3: {missing}. "
            "Run `eds generate master-data`, `eds generate customers`, and "
            "`eds generate journey` first."
        )

    seed = resolve_seed(config.platform.seed)
    settings = config.engagement

    catalog = ProductCatalog.from_frames(upstream["categories"], upstream["products"], seed)
    product_views = generate_product_views(
        settings,
        upstream["sessions"],
        upstream["category_views"],
        upstream["search_history"],
        catalog,
        seed,
    )
    wishlists = generate_wishlists(
        settings,
        upstream["customer_personas"],
        product_views,
        upstream["sessions"],
        seed,
    )

    datasets: dict[str, pl.DataFrame] = {
        "product_views": product_views,
        "wishlists": wishlists,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in ENGAGEMENT_DATASETS}
    return EngagementData(datasets=ordered, seed=seed)
