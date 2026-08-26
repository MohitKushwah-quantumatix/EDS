"""The Healthcare dataset schema registry — every dataset's declaration by name.

Two independent consumers need "name -> Dataset declaration" for all Healthcare
datasets, and neither may import ``eds.domains`` directly to get it: the
PostgreSQL adapter's constraint enforcement (:mod:`eds.adapters.postgres`), and
portable ``schema.json`` export (:mod:`eds.core.schema_export`, wired in from
:mod:`eds.cli.healthcare`). This module is where that knowledge is allowed to
live: ``eds.runners.healthcare`` is the one package that may depend on both a
domain and an adapter (PADR-014, PADR-015), or, as here, hand the same domain
data to something that isn't an adapter at all.

.. code-block:: python

    from eds.adapters.postgres.adapter import PostgresAdapter
    from eds.runners.healthcare.dataset_registry import HEALTHCARE_DATASET_SCHEMAS

    adapter = PostgresAdapter(dsn, dataset_schemas=HEALTHCARE_DATASET_SCHEMAS)

Every dataset name is registered, but only some engines make use of every
declaration; ``PostgresAdapter.write`` looks each dataset it is actually given
up in this mapping and falls back to an inferred schema for anything outside it.
"""

from __future__ import annotations

from eds.core.schema import Dataset
from eds.domains.healthcare.domain.additional.schema import ADDITIONAL_DATASETS
from eds.domains.healthcare.domain.billing.schema import BILLING_DATASETS
from eds.domains.healthcare.domain.encounter.schema import ENCOUNTER_DATASETS
from eds.domains.healthcare.domain.master_data import MASTER_DATA_DATASETS
from eds.domains.healthcare.domain.patient.schema import PATIENT_DATASETS
from eds.domains.healthcare.domain.provider.schema import PROVIDER_DATASETS

__all__ = ["HEALTHCARE_DATASET_SCHEMAS"]

_ALL_HEALTHCARE_DATASETS: tuple[Dataset, ...] = (
    *MASTER_DATA_DATASETS,
    *PATIENT_DATASETS,
    *PROVIDER_DATASETS,
    *ENCOUNTER_DATASETS,
    *BILLING_DATASETS,
    *ADDITIONAL_DATASETS,
)

HEALTHCARE_DATASET_SCHEMAS: dict[str, Dataset] = {dataset.name: dataset for dataset in _ALL_HEALTHCARE_DATASETS}
