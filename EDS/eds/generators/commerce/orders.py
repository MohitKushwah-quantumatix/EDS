"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.orders`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.orders import (
    ORDER_DATASETS as ORDER_DATASETS,
)
from eds.domains.retail.generators.commerce.orders import (
    REQUIRED_ORDER_DATASETS as REQUIRED_ORDER_DATASETS,
)
from eds.domains.retail.generators.commerce.orders import (
    OrderData as OrderData,
)
from eds.domains.retail.generators.commerce.orders import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.generators.commerce.orders import (
    apply_current_status as apply_current_status,
)
from eds.domains.retail.generators.commerce.orders import (
    generate_order_data as generate_order_data,
)
from eds.domains.retail.generators.commerce.orders import (
    generate_order_lines as generate_order_lines,
)
from eds.domains.retail.generators.commerce.orders import (
    generate_order_status_history as generate_order_status_history,
)
from eds.domains.retail.generators.commerce.orders import (
    generate_orders as generate_orders,
)
from eds.domains.retail.generators.commerce.orders import (
    resolve_seed as resolve_seed,
)
