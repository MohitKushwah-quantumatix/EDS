"""Healthcare dataset registry for temporal operations.

Every module in this package that needs to look up a dataset declaration
imports it from here, so the registry is defined once and used everywhere.
"""

from __future__ import annotations

from eds.core.schema import Dataset
from eds.domains.healthcare.domain.master_data import MASTER_DATA_DATASETS
from eds.domains.healthcare.domain.patient.schema import PATIENT_DATASETS
from eds.domains.healthcare.domain.provider.schema import PROVIDER_DATASETS
from eds.domains.healthcare.domain.encounter.schema import ENCOUNTER_DATASETS
from eds.domains.healthcare.domain.billing.schema import BILLING_DATASETS

__all__ = ["HEALTHCARE_DATASETS", "healthcare_dataset"]

HEALTHCARE_DATASETS: tuple[Dataset, ...] = (
    *MASTER_DATA_DATASETS,
    *PATIENT_DATASETS,
    *PROVIDER_DATASETS,
    *ENCOUNTER_DATASETS,
    *BILLING_DATASETS,
)

_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in HEALTHCARE_DATASETS}


def healthcare_dataset(name: str) -> Dataset:
    """Look up a Healthcare dataset declaration by name.

    Args:
        name: Dataset name.

    Returns:
        The dataset declaration.

    Raises:
        KeyError: If the dataset is not declared.
    """
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Healthcare produces no dataset named {name!r}. "
            f"Known datasets: {[d.name for d in HEALTHCARE_DATASETS]}"
        ) from None
