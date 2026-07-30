"""Orchestrator for the F007 payment generation run.

The two datasets are produced in dependency order, and the payment document is
finalised last:

1. Payments are built from the payable orders, the amount copied from the
   order and the method from the checkout it came from.
2. Status history records how each payment ended.
3. ``payment_status`` is set from that history, per ADR-012.

Everything is generated on top of the F002, F005 and F006 datasets, which are
passed in rather than regenerated. The whole run is a pure function of
``(configuration, seed, upstream data)``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.retail.domain.commerce.schema import PAYMENT_DATASETS
from eds.domains.retail.generators.commerce.payment_generator import (
    apply_payment_status,
    generate_payments,
)
from eds.domains.retail.generators.commerce.payment_status_generator import (
    generate_payment_status_history,
)

__all__ = ["REQUIRED_PAYMENT_DATASETS", "PaymentData", "generate_payment_data"]

#: The datasets F007 needs from earlier features. The checkout is read for its
#: ``payment_method``, which the order does not carry.
REQUIRED_PAYMENT_DATASETS: tuple[str, ...] = (
    "customers",
    "checkout",
    "orders",
)


@dataclass(frozen=True, slots=True)
class PaymentData:
    """The complete set of generated payment datasets.

    Attributes:
        datasets: Dataset name to frame, in dependency order.
        seed: The resolved seed the run used.
    """

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        """Return one dataset by name.

        Args:
            name: Dataset name, such as ``"payment_status_history"``.

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


def generate_payment_data(
    config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]
) -> PaymentData:
    """Generate payments and their status history from orders.

    Args:
        config: The complete run configuration.
        upstream: The earlier datasets, which must include the entries in
            :data:`REQUIRED_PAYMENT_DATASETS`.

    Returns:
        The generated bundle, including the resolved seed.

    Raises:
        KeyError: If a required upstream dataset is absent.
    """
    missing = [name for name in REQUIRED_PAYMENT_DATASETS if name not in upstream]
    if missing:
        raise KeyError(
            f"Missing upstream data required by F007: {missing}. "
            "Run `eds generate master-data`, `eds generate customers`, "
            "`eds generate journey`, and `eds generate commerce` first."
        )

    seed = resolve_seed(config.platform.seed)
    settings = config.payments

    payments = generate_payments(settings, upstream["orders"], upstream["checkout"], seed)
    history = generate_payment_status_history(settings, payments, seed)
    payments = apply_payment_status(payments, history)

    datasets: dict[str, pl.DataFrame] = {
        "payments": payments,
        "payment_status_history": history,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in PAYMENT_DATASETS}
    return PaymentData(datasets=ordered, seed=seed)
