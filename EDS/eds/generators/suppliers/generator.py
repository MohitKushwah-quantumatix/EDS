"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.suppliers.generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.suppliers.generator import (
    SUPPLIERS as SUPPLIERS,
)
from eds.domains.retail.generators.suppliers.generator import (
    MasterDataConfig as MasterDataConfig,
)
from eds.domains.retail.generators.suppliers.generator import (
    SupplierTier as SupplierTier,
)
from eds.domains.retail.generators.suppliers.generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.suppliers.generator import (
    format_code as format_code,
)
from eds.domains.retail.generators.suppliers.generator import (
    generate_suppliers as generate_suppliers,
)
from eds.domains.retail.generators.suppliers.generator import (
    make_faker as make_faker,
)
from eds.domains.retail.generators.suppliers.generator import (
    make_rng as make_rng,
)
