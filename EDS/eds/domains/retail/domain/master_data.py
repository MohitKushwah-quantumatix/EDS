"""The master data dataset registry.

``MASTER_DATA_DATASETS`` is ordered so that every dataset appears after the
datasets it references. Generators, validators, and exporters all iterate this
tuple, so adding an output file is a single-line change here.
"""

from __future__ import annotations

from eds.core.schema import Dataset
from eds.domains.retail.domain.catalog.schema import CATALOG_DATASETS
from eds.domains.retail.domain.commercial.schema import COMMERCIAL_DATASETS
from eds.domains.retail.domain.geography.schema import GEOGRAPHY_DATASETS
from eds.domains.retail.domain.inventory.schema import INVENTORY_DATASETS
from eds.domains.retail.domain.supply_chain.schema import SUPPLY_CHAIN_DATASETS

__all__ = ["MASTER_DATA_DATASETS", "dataset_by_name", "dataset_names"]

MASTER_DATA_DATASETS: tuple[Dataset, ...] = (
    # Geography first: everything else references it.
    *GEOGRAPHY_DATASETS,
    # Commercial reference tables depend only on geography.
    *COMMERCIAL_DATASETS,
    # Supply chain depends on geography.
    *SUPPLY_CHAIN_DATASETS,
    # Catalog depends on geography, suppliers, and tax codes.
    *CATALOG_DATASETS,
    # Inventory depends on products and warehouses.
    *INVENTORY_DATASETS,
)

_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in MASTER_DATA_DATASETS}


def dataset_names() -> tuple[str, ...]:
    """Return every master dataset name in dependency order."""
    return tuple(_BY_NAME)


def dataset_by_name(name: str) -> Dataset:
    """Look up a dataset declaration by name.

    Args:
        name: Dataset name, such as ``"products"``.

    Returns:
        The matching dataset declaration.

    Raises:
        KeyError: If no dataset with that name is registered.
    """
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"Unknown dataset: {name!r}. Known datasets: {dataset_names()}") from None
