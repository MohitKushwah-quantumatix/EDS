"""Orchestrator for the F010 review generation run.

Unlike every earlier commerce feature this one produces a single dataset: a
review has no collection of its own and no lifecycle, so there is nothing to
generate alongside it and nothing to derive a status from. The orchestrator
still exists, because the CLI and the tests reach every feature the same way.

Everything is generated on top of the F001, F002, F006, F008 and F009 datasets,
which are passed in rather than regenerated. The whole run is a pure function
of ``(configuration, seed, upstream data)``.

This is the last feature of Enterprise Data Simulator v1.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.retail.domain.commerce.schema import REVIEW_DATASETS
from eds.domains.retail.generators.commerce.review_generator import generate_reviews

__all__ = ["REQUIRED_REVIEW_DATASETS", "ReviewData", "generate_review_data"]

#: The datasets F010 needs from earlier features. ``return_items`` is read to
#: exclude what came back, so an empty returns run still needs the file.
REQUIRED_REVIEW_DATASETS: tuple[str, ...] = (
    "products",
    "customers",
    "orders",
    "shipments",
    "shipment_items",
    "return_items",
)


@dataclass(frozen=True, slots=True)
class ReviewData:
    """The complete set of generated review datasets.

    Attributes:
        datasets: Dataset name to frame.
        seed: The resolved seed the run used.
    """

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        """Return one dataset by name.

        Args:
            name: Dataset name, such as ``"reviews"``.

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
        """Iterate over ``(name, frame)`` pairs."""
        return iter(self.datasets.items())

    def row_counts(self) -> dict[str, int]:
        """Return the row count of every dataset, keyed by name."""
        return {name: frame.height for name, frame in self.datasets.items()}

    def total_rows(self) -> int:
        """Return the total number of rows across every dataset."""
        return sum(frame.height for frame in self.datasets.values())


def generate_review_data(
    config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]
) -> ReviewData:
    """Generate reviews from delivered, unreturned shipment items.

    Args:
        config: The complete run configuration.
        upstream: The earlier datasets, which must include the entries in
            :data:`REQUIRED_REVIEW_DATASETS`.

    Returns:
        The generated bundle, including the resolved seed.

    Raises:
        KeyError: If a required upstream dataset is absent.
    """
    missing = [name for name in REQUIRED_REVIEW_DATASETS if name not in upstream]
    if missing:
        raise KeyError(
            f"Missing upstream data required by F010: {missing}. "
            "Run `eds generate master-data`, `eds generate customers`, "
            "`eds generate journey`, and `eds generate commerce` first."
        )

    seed = resolve_seed(config.platform.seed)

    reviews = generate_reviews(
        config.reviews,
        upstream["shipments"],
        upstream["shipment_items"],
        upstream["return_items"],
        seed,
    )

    datasets: dict[str, pl.DataFrame] = {"reviews": reviews}

    ordered = {dataset.name: datasets[dataset.name] for dataset in REVIEW_DATASETS}
    return ReviewData(datasets=ordered, seed=seed)
