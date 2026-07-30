"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.master_data`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.master_data import (
    CATALOG_DATASETS as CATALOG_DATASETS,
)
from eds.domains.retail.domain.master_data import (
    COMMERCIAL_DATASETS as COMMERCIAL_DATASETS,
)
from eds.domains.retail.domain.master_data import (
    GEOGRAPHY_DATASETS as GEOGRAPHY_DATASETS,
)
from eds.domains.retail.domain.master_data import (
    INVENTORY_DATASETS as INVENTORY_DATASETS,
)
from eds.domains.retail.domain.master_data import (
    MASTER_DATA_DATASETS as MASTER_DATA_DATASETS,
)
from eds.domains.retail.domain.master_data import (
    SUPPLY_CHAIN_DATASETS as SUPPLY_CHAIN_DATASETS,
)
from eds.domains.retail.domain.master_data import (
    Dataset as Dataset,
)
from eds.domains.retail.domain.master_data import (
    dataset_by_name as dataset_by_name,
)
from eds.domains.retail.domain.master_data import (
    dataset_names as dataset_names,
)
