"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.shipments`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.shipments import (
    REQUIRED_SHIPMENT_DATASETS as REQUIRED_SHIPMENT_DATASETS,
)
from eds.domains.retail.generators.commerce.shipments import (
    SHIPMENT_DATASETS as SHIPMENT_DATASETS,
)
from eds.domains.retail.generators.commerce.shipments import (
    ShipmentData as ShipmentData,
)
from eds.domains.retail.generators.commerce.shipments import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.generators.commerce.shipments import (
    apply_status_and_timeline as apply_status_and_timeline,
)
from eds.domains.retail.generators.commerce.shipments import (
    generate_shipment_data as generate_shipment_data,
)
from eds.domains.retail.generators.commerce.shipments import (
    generate_shipment_items as generate_shipment_items,
)
from eds.domains.retail.generators.commerce.shipments import (
    generate_shipment_status_history as generate_shipment_status_history,
)
from eds.domains.retail.generators.commerce.shipments import (
    generate_shipments as generate_shipments,
)
from eds.domains.retail.generators.commerce.shipments import (
    resolve_seed as resolve_seed,
)
