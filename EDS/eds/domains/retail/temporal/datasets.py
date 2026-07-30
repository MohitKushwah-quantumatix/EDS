"""Every Retail dataset declaration, in one place.

The declarations already exist, one collection per feature. What did not exist
was a way to ask "what is the primary key of *this* name" without knowing
which feature owns it - which is exactly what a temporal layer needs, because
appending a day's work to history is the same operation for all thirty-nine
datasets and differs only by key.

Nothing new is declared here. This module gathers, and a test asserts it
gathers everything the domain says it produces.
"""

from __future__ import annotations

from typing import Final

from eds.core.schema import Dataset
from eds.domains.retail.domain.commerce.schema import (
    CHECKOUT_DATASETS,
    COMMERCE_DATASETS,
    ORDER_DATASETS,
    PAYMENT_DATASETS,
    RETURN_DATASETS,
    REVIEW_DATASETS,
    SHIPMENT_DATASETS,
)
from eds.domains.retail.domain.customer.schema import CUSTOMER_DATASETS
from eds.domains.retail.domain.journey.schema import (
    BROWSING_DATASETS,
    ENGAGEMENT_DATASETS,
    JOURNEY_DATASETS,
)
from eds.domains.retail.domain.master_data import MASTER_DATA_DATASETS

__all__ = ["RETAIL_DATASETS", "retail_dataset", "retail_dataset_names"]

#: Every dataset Retail produces, in dependency order.
RETAIL_DATASETS: Final[tuple[Dataset, ...]] = (
    *MASTER_DATA_DATASETS,
    *CUSTOMER_DATASETS,
    *JOURNEY_DATASETS,
    *BROWSING_DATASETS,
    *ENGAGEMENT_DATASETS,
    *COMMERCE_DATASETS,
    *CHECKOUT_DATASETS,
    *ORDER_DATASETS,
    *PAYMENT_DATASETS,
    *SHIPMENT_DATASETS,
    *RETURN_DATASETS,
    *REVIEW_DATASETS,
)

_BY_NAME: Final[dict[str, Dataset]] = {dataset.name: dataset for dataset in RETAIL_DATASETS}


def retail_dataset_names() -> tuple[str, ...]:
    """Return every Retail dataset name, in dependency order."""
    return tuple(_BY_NAME)


def retail_dataset(name: str) -> Dataset:
    """Look up any Retail dataset declaration by name.

    Args:
        name: Dataset name, such as ``"order_lines"``.

    Returns:
        The declaration, including its primary key and foreign keys.

    Raises:
        KeyError: If Retail does not produce a dataset with that name.
    """
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"Retail produces no dataset named {name!r}") from None
