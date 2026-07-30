"""Orchestrator for the F008 shipment generation run.

The three datasets are produced in dependency order, and the shipment document
is finalised last:

1. Shipments are built from the captured payments, the shipping method copied
   from the checkout and the carrier chosen from that method's options.
2. Status history records how far each shipment progressed, and owns the whole
   timeline.
3. ``current_status``, ``shipped_at`` and ``delivered_at`` are set from that
   history, per ADR-012.
4. Shipment items are drawn from the order lines of each shipment's order.

Everything is generated on top of the F001, F005, F006 and F007 datasets,
which are passed in rather than regenerated. The whole run is a pure function
of ``(configuration, seed, upstream data)``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.retail.domain.commerce.schema import SHIPMENT_DATASETS
from eds.domains.retail.generators.commerce.shipment_generator import (
    apply_status_and_timeline,
    generate_shipments,
)
from eds.domains.retail.generators.commerce.shipment_item_generator import generate_shipment_items
from eds.domains.retail.generators.commerce.shipment_status_generator import (
    generate_shipment_status_history,
)

__all__ = ["REQUIRED_SHIPMENT_DATASETS", "ShipmentData", "generate_shipment_data"]

#: The datasets F008 needs from earlier features. The checkout is read for its
#: ``shipping_method``, which neither the order nor the payment carries.
REQUIRED_SHIPMENT_DATASETS: tuple[str, ...] = (
    "products",
    "customers",
    "checkout",
    "orders",
    "order_lines",
    "payments",
)


@dataclass(frozen=True, slots=True)
class ShipmentData:
    """The complete set of generated shipment datasets.

    Attributes:
        datasets: Dataset name to frame, in dependency order.
        seed: The resolved seed the run used.
    """

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        """Return one dataset by name.

        Args:
            name: Dataset name, such as ``"shipment_items"``.

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


def generate_shipment_data(
    config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]
) -> ShipmentData:
    """Generate shipments, shipment items, and status history from payments.

    Args:
        config: The complete run configuration.
        upstream: The earlier datasets, which must include the entries in
            :data:`REQUIRED_SHIPMENT_DATASETS`.

    Returns:
        The generated bundle, including the resolved seed.

    Raises:
        KeyError: If a required upstream dataset is absent, or a shipping
            method in the data has no carrier configured.
    """
    missing = [name for name in REQUIRED_SHIPMENT_DATASETS if name not in upstream]
    if missing:
        raise KeyError(
            f"Missing upstream data required by F008: {missing}. "
            "Run `eds generate master-data`, `eds generate customers`, "
            "`eds generate journey`, and `eds generate commerce` first."
        )

    seed = resolve_seed(config.platform.seed)
    settings = config.shipments

    shipments = generate_shipments(
        settings, upstream["payments"], upstream["orders"], upstream["checkout"], seed
    )
    history = generate_shipment_status_history(settings, shipments, seed)
    shipments = apply_status_and_timeline(shipments, history)
    items = generate_shipment_items(settings, shipments, upstream["order_lines"])

    datasets: dict[str, pl.DataFrame] = {
        "shipments": shipments,
        "shipment_items": items,
        "shipment_status_history": history,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in SHIPMENT_DATASETS}
    return ShipmentData(datasets=ordered, seed=seed)
