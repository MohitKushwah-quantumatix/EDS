"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.inventory.generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.inventory.generator import (
    INVENTORY as INVENTORY,
)
from eds.domains.retail.generators.inventory.generator import (
    MasterDataConfig as MasterDataConfig,
)
from eds.domains.retail.generators.inventory.generator import (
    WarehouseStatus as WarehouseStatus,
)
from eds.domains.retail.generators.inventory.generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.inventory.generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.inventory.generator import (
    generate_inventory as generate_inventory,
)
from eds.domains.retail.generators.inventory.generator import (
    iter_inventory_batches as iter_inventory_batches,
)
from eds.domains.retail.generators.inventory.generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.inventory.generator import (
    stockable_warehouse_ids as stockable_warehouse_ids,
)
