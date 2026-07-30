"""Orchestrator for the F009 return generation run.

The three datasets are produced in dependency order, and the return document is
finalised last:

1. Returns are requested against delivered shipments, the reason drawn from the
   F001 master data and the settlement from configuration.
2. Status history records how far each return progressed, and owns the whole
   timeline.
3. ``current_status``, ``approved_at``, ``received_at`` and ``completed_at``
   are set from that history, per ADR-012.
4. Return items are drawn from the shipment items of each return's shipment.

Everything is generated on top of the F001, F006 and F008 datasets, which are
passed in rather than regenerated. The whole run is a pure function of
``(configuration, seed, upstream data)``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.retail.domain.commerce.schema import RETURN_DATASETS
from eds.domains.retail.generators.commerce.return_generator import (
    apply_status_and_timeline,
    generate_returns,
)
from eds.domains.retail.generators.commerce.return_item_generator import generate_return_items
from eds.domains.retail.generators.commerce.return_status_generator import (
    generate_return_status_history,
)

__all__ = ["REQUIRED_RETURN_DATASETS", "ReturnData", "generate_return_data"]

#: The datasets F009 needs from earlier features. ``return_reasons`` is the
#: F001 master table the reason vocabulary is read from.
REQUIRED_RETURN_DATASETS: tuple[str, ...] = (
    "products",
    "return_reasons",
    "orders",
    "order_lines",
    "shipments",
    "shipment_items",
)


@dataclass(frozen=True, slots=True)
class ReturnData:
    """The complete set of generated return datasets.

    Attributes:
        datasets: Dataset name to frame, in dependency order.
        seed: The resolved seed the run used.
    """

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        """Return one dataset by name.

        Args:
            name: Dataset name, such as ``"return_items"``.

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


def generate_return_data(
    config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]
) -> ReturnData:
    """Generate returns, return items, and status history from shipments.

    Args:
        config: The complete run configuration.
        upstream: The earlier datasets, which must include the entries in
            :data:`REQUIRED_RETURN_DATASETS`.

    Returns:
        The generated bundle, including the resolved seed.

    Raises:
        KeyError: If a required upstream dataset is absent.
        ValueError: If the master data offers no active return reason.
    """
    missing = [name for name in REQUIRED_RETURN_DATASETS if name not in upstream]
    if missing:
        raise KeyError(
            f"Missing upstream data required by F009: {missing}. "
            "Run `eds generate master-data`, `eds generate customers`, "
            "`eds generate journey`, and `eds generate commerce` first."
        )

    seed = resolve_seed(config.platform.seed)
    settings = config.returns

    returns = generate_returns(
        settings,
        upstream["shipments"],
        upstream["shipment_items"],
        upstream["return_reasons"],
        seed,
    )
    history = generate_return_status_history(settings, returns, seed)
    returns = apply_status_and_timeline(returns, history)
    items = generate_return_items(settings, returns, upstream["shipment_items"], seed)

    datasets: dict[str, pl.DataFrame] = {
        "returns": returns,
        "return_items": items,
        "return_status_history": history,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in RETURN_DATASETS}
    return ReturnData(datasets=ordered, seed=seed)
