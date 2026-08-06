"""The Retail dataset schema registry — every dataset's declaration by name.

Two independent consumers need "name -> Dataset declaration" for all 39
Retail datasets, and neither may import ``eds.domains`` directly to get it
(PADR-003): the PostgreSQL adapter's constraint enforcement
(:mod:`eds.adapters.postgres`), and portable ``schema.json`` export
(:mod:`eds.core.schema_export`, wired in from :mod:`eds.cli.generate`). This
module is where that knowledge is allowed to live: ``eds.runners.retail`` is
the one package that may depend on both a domain and an adapter (PADR-014,
PADR-015), or, as here, hand the same domain data to something that isn't
an adapter at all.

.. code-block:: python

    from eds.adapters.postgres.adapter import PostgresAdapter
    from eds.runners.retail.dataset_registry import RETAIL_DATASET_SCHEMAS

    adapter = PostgresAdapter(dsn, dataset_schemas=RETAIL_DATASET_SCHEMAS)

Every dataset name is registered, but only some engines make use of every
declaration; ``PostgresAdapter.write`` looks each dataset it is actually
given up in this mapping and falls back to an inferred schema for anything
outside it.
"""

from __future__ import annotations

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

__all__ = ["RETAIL_DATASET_SCHEMAS"]

_ALL_RETAIL_DATASETS: tuple[Dataset, ...] = (
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

#: Every Retail dataset's declaration, keyed by name. Pass this (or a subset
#: of it) as ``PostgresAdapter(..., dataset_schemas=...)`` to get primary
#: key, foreign key, and uniqueness enforcement on a PostgreSQL target.
RETAIL_DATASET_SCHEMAS: dict[str, Dataset] = {dataset.name: dataset for dataset in _ALL_RETAIL_DATASETS}
