"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.commerce`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.commerce import (
    COMMERCE_DATASETS as COMMERCE_DATASETS,
)
from eds.domains.retail.generators.commerce.commerce import (
    REQUIRED_COMMERCE_DATASETS as REQUIRED_COMMERCE_DATASETS,
)
from eds.domains.retail.generators.commerce.commerce import (
    CartSources as CartSources,
)
from eds.domains.retail.generators.commerce.commerce import (
    CommerceData as CommerceData,
)
from eds.domains.retail.generators.commerce.commerce import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.generators.commerce.commerce import (
    generate_cart_items as generate_cart_items,
)
from eds.domains.retail.generators.commerce.commerce import (
    generate_carts as generate_carts,
)
from eds.domains.retail.generators.commerce.commerce import (
    generate_commerce_data as generate_commerce_data,
)
from eds.domains.retail.generators.commerce.commerce import (
    plan_carts as plan_carts,
)
from eds.domains.retail.generators.commerce.commerce import (
    resolve_seed as resolve_seed,
)
