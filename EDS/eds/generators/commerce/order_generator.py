"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.order_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.order_generator import (
    ORDER_NUMBER_SEQUENCE_WIDTH as ORDER_NUMBER_SEQUENCE_WIDTH,
)
from eds.domains.retail.generators.commerce.order_generator import (
    ORDERS as ORDERS,
)
from eds.domains.retail.generators.commerce.order_generator import (
    CheckoutStatus as CheckoutStatus,
)
from eds.domains.retail.generators.commerce.order_generator import (
    OrderConfig as OrderConfig,
)
from eds.domains.retail.generators.commerce.order_generator import (
    OrderStatus as OrderStatus,
)
from eds.domains.retail.generators.commerce.order_generator import (
    apply_current_status as apply_current_status,
)
from eds.domains.retail.generators.commerce.order_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.order_generator import (
    generate_orders as generate_orders,
)
from eds.domains.retail.generators.commerce.order_generator import (
    iter_order_batches as iter_order_batches,
)
from eds.domains.retail.generators.commerce.order_generator import (
    order_number_expression as order_number_expression,
)
