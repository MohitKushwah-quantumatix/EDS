"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.order_status_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.order_status_generator import (
    ORDER_LIFECYCLE as ORDER_LIFECYCLE,
)
from eds.domains.retail.generators.commerce.order_status_generator import (
    ORDER_STATUS_HISTORY as ORDER_STATUS_HISTORY,
)
from eds.domains.retail.generators.commerce.order_status_generator import (
    OrderConfig as OrderConfig,
)
from eds.domains.retail.generators.commerce.order_status_generator import (
    OrderStatus as OrderStatus,
)
from eds.domains.retail.generators.commerce.order_status_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.order_status_generator import (
    generate_order_status_history as generate_order_status_history,
)
from eds.domains.retail.generators.commerce.order_status_generator import (
    iter_order_status_batches as iter_order_status_batches,
)
from eds.domains.retail.generators.commerce.order_status_generator import (
    lifecycle_position as lifecycle_position,
)
from eds.domains.retail.generators.commerce.order_status_generator import (
    make_rng as make_rng,
)
