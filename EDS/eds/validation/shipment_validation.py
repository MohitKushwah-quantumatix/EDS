"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.shipment_validation`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.shipment_validation import (
    SHIPMENT_DATASETS as SHIPMENT_DATASETS,
)
from eds.domains.retail.validation.shipment_validation import (
    SHIPMENT_LIFECYCLE as SHIPMENT_LIFECYCLE,
)
from eds.domains.retail.validation.shipment_validation import (
    SHIPMENT_NUMBER_PATTERN as SHIPMENT_NUMBER_PATTERN,
)
from eds.domains.retail.validation.shipment_validation import (
    TRACKING_NUMBER_PATTERN as TRACKING_NUMBER_PATTERN,
)
from eds.domains.retail.validation.shipment_validation import (
    PaymentStatus as PaymentStatus,
)
from eds.domains.retail.validation.shipment_validation import (
    ShipmentStatus as ShipmentStatus,
)
from eds.domains.retail.validation.shipment_validation import (
    ValidationError as ValidationError,
)
from eds.domains.retail.validation.shipment_validation import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.shipment_validation import (
    assert_valid_shipment_data as assert_valid_shipment_data,
)
from eds.domains.retail.validation.shipment_validation import (
    validate_carrier_assignment as validate_carrier_assignment,
)
from eds.domains.retail.validation.shipment_validation import (
    validate_item_reconciliation as validate_item_reconciliation,
)
from eds.domains.retail.validation.shipment_validation import (
    validate_payment_eligibility as validate_payment_eligibility,
)
from eds.domains.retail.validation.shipment_validation import (
    validate_referential_integrity as validate_referential_integrity,
)
from eds.domains.retail.validation.shipment_validation import (
    validate_shipment_data as validate_shipment_data,
)
from eds.domains.retail.validation.shipment_validation import (
    validate_shipment_numbers as validate_shipment_numbers,
)
from eds.domains.retail.validation.shipment_validation import (
    validate_shipment_status_history as validate_shipment_status_history,
)
from eds.domains.retail.validation.shipment_validation import (
    validate_shipment_timeline as validate_shipment_timeline,
)
