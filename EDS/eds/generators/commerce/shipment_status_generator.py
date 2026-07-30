"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.shipment_status_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.shipment_status_generator import (
    SHIPMENT_LIFECYCLE as SHIPMENT_LIFECYCLE,
)
from eds.domains.retail.generators.commerce.shipment_status_generator import (
    SHIPMENT_STATUS_HISTORY as SHIPMENT_STATUS_HISTORY,
)
from eds.domains.retail.generators.commerce.shipment_status_generator import (
    ShipmentConfig as ShipmentConfig,
)
from eds.domains.retail.generators.commerce.shipment_status_generator import (
    ShipmentStatus as ShipmentStatus,
)
from eds.domains.retail.generators.commerce.shipment_status_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.shipment_status_generator import (
    generate_shipment_status_history as generate_shipment_status_history,
)
from eds.domains.retail.generators.commerce.shipment_status_generator import (
    iter_shipment_status_batches as iter_shipment_status_batches,
)
from eds.domains.retail.generators.commerce.shipment_status_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.commerce.shipment_status_generator import (
    shipment_lifecycle_position as shipment_lifecycle_position,
)
