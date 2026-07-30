"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.supply_chain.schema`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.supply_chain.schema import (
    SUPPLIERS as SUPPLIERS,
)
from eds.domains.retail.domain.supply_chain.schema import (
    SUPPLY_CHAIN_DATASETS as SUPPLY_CHAIN_DATASETS,
)
from eds.domains.retail.domain.supply_chain.schema import (
    WAREHOUSES as WAREHOUSES,
)
from eds.domains.retail.domain.supply_chain.schema import (
    Dataset as Dataset,
)
from eds.domains.retail.domain.supply_chain.schema import (
    ForeignKey as ForeignKey,
)
