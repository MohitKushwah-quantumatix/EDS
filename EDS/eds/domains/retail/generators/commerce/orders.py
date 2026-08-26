"""Orchestrator for the F006 order generation run.

The three datasets are produced in dependency order, and the order document is
finalised last:

1. Orders are built from the successful checkouts, financial values copied.
2. Status history records how far each order progressed.
3. ``current_status`` is set from that history, per ADR-012.
4. Order lines are drawn from the active cart items of each order's cart.

Everything is generated on top of the F001, F002, F004 and F005 datasets,
which are passed in rather than regenerated. The whole run is a pure function
of ``(configuration, seed, upstream data)``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.retail.domain.commerce.schema import ORDER_DATASETS
from eds.domains.retail.generators.commerce.order_generator import (
    apply_current_status,
    generate_orders,
)
from eds.domains.retail.generators.commerce.order_line_generator import generate_order_lines
from eds.domains.retail.generators.commerce.order_status_generator import (
    generate_order_status_history,
)

__all__ = ["REQUIRED_ORDER_DATASETS", "OrderData", "generate_order_data"]

#: The datasets F006 needs from earlier features.
REQUIRED_ORDER_DATASETS: tuple[str, ...] = (
    "products",
    "customers",
    "customer_addresses",
    "shopping_carts",
    "cart_items",
    "checkout",
)


@dataclass(frozen=True, slots=True)
class OrderData:
    """The complete set of generated order datasets.

    Attributes:
        datasets: Dataset name to frame, in dependency order.
        seed: The resolved seed the run used.
    """

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        """Return one dataset by name.

        Args:
            name: Dataset name, such as ``"order_lines"``.

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


def generate_order_data(
    config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]
) -> OrderData:
    """Generate orders, order lines, and status history from checkouts.

    Args:
        config: The complete run configuration.
        upstream: The earlier datasets, which must include the entries in
            :data:`REQUIRED_ORDER_DATASETS`.

    Returns:
        The generated bundle, including the resolved seed.

    Raises:
        KeyError: If a required upstream dataset is absent.
    """
    missing = [name for name in REQUIRED_ORDER_DATASETS if name not in upstream]
    if missing:
        raise KeyError(
            f"Missing upstream data required by F006: {missing}. "
            "Run `eds generate master-data`, `eds generate customers`, "
            "`eds generate journey`, and `eds generate commerce` first."
        )

    seed = resolve_seed(config.platform.seed)
    settings = config.orders

    orders = generate_orders(settings, upstream["checkout"], seed)
    history = generate_order_status_history(settings, orders, seed)
    orders = apply_current_status(orders, history)
    lines = generate_order_lines(settings, orders, upstream["cart_items"])

    datasets: dict[str, pl.DataFrame] = {
        "orders": orders,
        "order_lines": lines,
        "order_status_history": history,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in ORDER_DATASETS}
    return OrderData(datasets=ordered, seed=seed)
