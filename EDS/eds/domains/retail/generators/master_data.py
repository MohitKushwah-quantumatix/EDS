"""Orchestrator for the F001 master data generation run.

Datasets are produced in dependency order so that every foreign key has a
target by the time it is written. The result is a :class:`MasterData` bundle
keyed by dataset name, which the exporter and validators both consume.

The whole run is a pure function of ``(configuration, seed)``: given the same
inputs it produces byte-identical output.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import resolve_seed
from eds.domains.retail.domain.master_data import MASTER_DATA_DATASETS
from eds.domains.retail.generators.commercial.generator import (
    generate_coupon_types,
    generate_payment_methods,
    generate_return_reasons,
    generate_shipping_methods,
    generate_tax_codes,
)
from eds.domains.retail.generators.geography.generator import (
    generate_cities,
    generate_countries,
    generate_states,
)
from eds.domains.retail.generators.geography.reference import country_by_code
from eds.domains.retail.generators.inventory.generator import generate_inventory
from eds.domains.retail.generators.products.brands import generate_brands
from eds.domains.retail.generators.products.categories import generate_categories
from eds.domains.retail.generators.products.products import generate_products
from eds.domains.retail.generators.suppliers.generator import generate_suppliers
from eds.domains.retail.generators.warehouses.generator import generate_warehouses

__all__ = ["MasterData", "generate_master_data"]


@dataclass(frozen=True, slots=True)
class MasterData:
    """The complete set of generated master datasets.

    Attributes:
        datasets: Dataset name to frame, in dependency order.
        seed: The resolved seed the run used. Re-running with this seed
            reproduces the output exactly, even if the configured seed was
            ``None``.
    """

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        """Return one dataset by name.

        Args:
            name: Dataset name, such as ``"products"``.

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


def _primary_currency(config: SimulationConfig) -> str:
    """Return the currency products are priced in.

    The first configured country's currency is used, so a US-only run prices
    in USD and a UK-only run in GBP.

    Args:
        config: The run configuration.

    Returns:
        An ISO 4217 currency code.

    Raises:
        KeyError: If the first configured country has no reference data.
    """
    return country_by_code(config.master_data.countries[0]).currency_code


def generate_master_data(config: SimulationConfig) -> MasterData:
    """Generate every master dataset in dependency order.

    Args:
        config: The complete run configuration.

    Returns:
        The generated bundle, including the resolved seed.

    Raises:
        KeyError: If a configured country has no reference data.
        ValueError: If a dataset cannot be generated because an upstream
            dataset is empty.
    """
    seed = resolve_seed(config.platform.seed)
    locale = config.platform.locale
    settings = config.master_data
    currency = _primary_currency(config)

    countries = generate_countries(settings)
    states = generate_states(settings)
    cities = generate_cities(settings, seed, locale)

    payment_methods = generate_payment_methods()
    shipping_methods = generate_shipping_methods()
    tax_codes = generate_tax_codes(settings)
    coupon_types = generate_coupon_types()
    return_reasons = generate_return_reasons()

    suppliers = generate_suppliers(settings, cities, seed, locale)
    warehouses = generate_warehouses(settings, cities, seed)

    categories = generate_categories(settings)
    brands = generate_brands(settings, countries, seed, locale)
    products = generate_products(settings, categories, brands, suppliers, tax_codes, seed, currency)

    inventory = generate_inventory(settings, products, warehouses, seed)

    datasets: dict[str, pl.DataFrame] = {
        "countries": countries,
        "states": states,
        "cities": cities,
        "payment_methods": payment_methods,
        "shipping_methods": shipping_methods,
        "tax_codes": tax_codes,
        "coupon_types": coupon_types,
        "return_reasons": return_reasons,
        "suppliers": suppliers,
        "warehouses": warehouses,
        "categories": categories,
        "brands": brands,
        "products": products,
        "inventory": inventory,
    }

    # Emit in the registry's dependency order so exporters and validators see
    # a stable, referentially safe sequence.
    ordered = {dataset.name: datasets[dataset.name] for dataset in MASTER_DATA_DATASETS}
    return MasterData(datasets=ordered, seed=seed)
