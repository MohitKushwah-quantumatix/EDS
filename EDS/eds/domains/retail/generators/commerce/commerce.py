"""Orchestrator for the F004 commerce generation run.

Carts are planned first, then filled, then finalised. The order matters: a
cart's ``item_count`` and timestamps are derived from the items it actually
received, and a planned cart that ended up empty is dropped rather than
written as a cart with nothing in it.

Everything is generated on top of the F001, F002, F003.1 and F003.3 datasets,
which are passed in rather than regenerated. The whole run is a pure function
of ``(configuration, seed, upstream data)``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.retail.domain.commerce.schema import COMMERCE_DATASETS
from eds.domains.retail.generators.commerce.cart_generator import generate_carts, plan_carts
from eds.domains.retail.generators.commerce.cart_item_generator import (
    CartSources,
    generate_cart_items,
)

__all__ = ["REQUIRED_COMMERCE_DATASETS", "CommerceData", "generate_commerce_data"]

#: The datasets F004 needs from earlier features.
REQUIRED_COMMERCE_DATASETS: tuple[str, ...] = (
    "products",
    "customers",
    "sessions",
    "customer_personas",
    "product_views",
    "wishlists",
)


@dataclass(frozen=True, slots=True)
class CommerceData:
    """The complete set of generated commerce datasets.

    Attributes:
        datasets: Dataset name to frame, in dependency order.
        seed: The resolved seed the run used.
    """

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        """Return one dataset by name.

        Args:
            name: Dataset name, such as ``"cart_items"``.

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


def generate_commerce_data(
    config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]
) -> CommerceData:
    """Generate shopping carts and cart items from existing browsing activity.

    Args:
        config: The complete run configuration.
        upstream: The earlier datasets, which must include the entries in
            :data:`REQUIRED_COMMERCE_DATASETS`.

    Returns:
        The generated bundle, including the resolved seed.

    Raises:
        KeyError: If a required upstream dataset is absent, or a session names
            a persona with no cart profile.
        ValueError: If product views or products are empty.
    """
    missing = [name for name in REQUIRED_COMMERCE_DATASETS if name not in upstream]
    if missing:
        raise KeyError(
            f"Missing upstream data required by F004: {missing}. "
            "Run `eds generate master-data`, `eds generate customers`, and "
            "`eds generate journey` first."
        )

    seed = resolve_seed(config.platform.seed)
    settings = config.commerce

    sources = CartSources.from_frames(
        upstream["product_views"], upstream["wishlists"], upstream["products"]
    )
    planned = plan_carts(settings, upstream["sessions"], upstream["customer_personas"], seed)
    cart_items = generate_cart_items(settings, planned, sources, seed)
    carts = generate_carts(planned, cart_items, settings.batch_size)

    datasets: dict[str, pl.DataFrame] = {
        "shopping_carts": carts,
        "cart_items": cart_items,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in COMMERCE_DATASETS}
    return CommerceData(datasets=ordered, seed=seed)
