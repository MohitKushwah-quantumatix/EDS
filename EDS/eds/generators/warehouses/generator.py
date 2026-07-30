"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.warehouses.generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.warehouses.generator import (
    WAREHOUSES as WAREHOUSES,
)
from eds.domains.retail.generators.warehouses.generator import (
    MasterDataConfig as MasterDataConfig,
)
from eds.domains.retail.generators.warehouses.generator import (
    WarehouseStatus as WarehouseStatus,
)
from eds.domains.retail.generators.warehouses.generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.warehouses.generator import (
    format_code as format_code,
)
from eds.domains.retail.generators.warehouses.generator import (
    generate_warehouses as generate_warehouses,
)
from eds.domains.retail.generators.warehouses.generator import (
    make_rng as make_rng,
)
