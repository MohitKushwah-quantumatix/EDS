"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.shipment_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.shipment_generator import (
    SHIPMENT_NUMBER_SEQUENCE_WIDTH as SHIPMENT_NUMBER_SEQUENCE_WIDTH,
)
from eds.domains.retail.generators.commerce.shipment_generator import (
    SHIPMENTS as SHIPMENTS,
)
from eds.domains.retail.generators.commerce.shipment_generator import (
    TRACKING_NUMBER_DIGITS as TRACKING_NUMBER_DIGITS,
)
from eds.domains.retail.generators.commerce.shipment_generator import (
    PaymentStatus as PaymentStatus,
)
from eds.domains.retail.generators.commerce.shipment_generator import (
    ShipmentConfig as ShipmentConfig,
)
from eds.domains.retail.generators.commerce.shipment_generator import (
    ShipmentStatus as ShipmentStatus,
)
from eds.domains.retail.generators.commerce.shipment_generator import (
    apply_status_and_timeline as apply_status_and_timeline,
)
from eds.domains.retail.generators.commerce.shipment_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.shipment_generator import (
    generate_shipments as generate_shipments,
)
from eds.domains.retail.generators.commerce.shipment_generator import (
    iter_shipment_batches as iter_shipment_batches,
)
from eds.domains.retail.generators.commerce.shipment_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.commerce.shipment_generator import (
    shipment_number_expression as shipment_number_expression,
)
from eds.domains.retail.generators.commerce.shipment_generator import (
    tracking_number_expression as tracking_number_expression,
)
