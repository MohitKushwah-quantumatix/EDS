"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.order_line_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.order_line_generator import (
    ORDER_LINES as ORDER_LINES,
)
from eds.domains.retail.generators.commerce.order_line_generator import (
    OrderConfig as OrderConfig,
)
from eds.domains.retail.generators.commerce.order_line_generator import (
    active_cart_items as active_cart_items,
)
from eds.domains.retail.generators.commerce.order_line_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.order_line_generator import (
    generate_order_lines as generate_order_lines,
)
from eds.domains.retail.generators.commerce.order_line_generator import (
    iter_order_line_batches as iter_order_line_batches,
)
