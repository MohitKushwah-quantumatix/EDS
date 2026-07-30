"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.shipment_item_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.shipment_item_generator import (
    SHIPMENT_ITEMS as SHIPMENT_ITEMS,
)
from eds.domains.retail.generators.commerce.shipment_item_generator import (
    ShipmentConfig as ShipmentConfig,
)
from eds.domains.retail.generators.commerce.shipment_item_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.shipment_item_generator import (
    generate_shipment_items as generate_shipment_items,
)
from eds.domains.retail.generators.commerce.shipment_item_generator import (
    iter_shipment_item_batches as iter_shipment_item_batches,
)
