"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.inventory.schema`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.inventory.schema import (
    INVENTORY as INVENTORY,
)
from eds.domains.retail.domain.inventory.schema import (
    INVENTORY_DATASETS as INVENTORY_DATASETS,
)
from eds.domains.retail.domain.inventory.schema import (
    Dataset as Dataset,
)
from eds.domains.retail.domain.inventory.schema import (
    ForeignKey as ForeignKey,
)
