"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.return_validation`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.return_validation import (
    RETURN_DATASETS as RETURN_DATASETS,
)
from eds.domains.retail.validation.return_validation import (
    RETURN_LIFECYCLE as RETURN_LIFECYCLE,
)
from eds.domains.retail.validation.return_validation import (
    RETURN_NUMBER_PATTERN as RETURN_NUMBER_PATTERN,
)
from eds.domains.retail.validation.return_validation import (
    ReturnStatus as ReturnStatus,
)
from eds.domains.retail.validation.return_validation import (
    ShipmentStatus as ShipmentStatus,
)
from eds.domains.retail.validation.return_validation import (
    ValidationError as ValidationError,
)
from eds.domains.retail.validation.return_validation import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.return_validation import (
    assert_valid_return_data as assert_valid_return_data,
)
from eds.domains.retail.validation.return_validation import (
    validate_item_reconciliation as validate_item_reconciliation,
)
from eds.domains.retail.validation.return_validation import (
    validate_referential_integrity as validate_referential_integrity,
)
from eds.domains.retail.validation.return_validation import (
    validate_refund_types as validate_refund_types,
)
from eds.domains.retail.validation.return_validation import (
    validate_return_data as validate_return_data,
)
from eds.domains.retail.validation.return_validation import (
    validate_return_numbers as validate_return_numbers,
)
from eds.domains.retail.validation.return_validation import (
    validate_return_status_history as validate_return_status_history,
)
from eds.domains.retail.validation.return_validation import (
    validate_return_timeline as validate_return_timeline,
)
from eds.domains.retail.validation.return_validation import (
    validate_shipment_eligibility as validate_shipment_eligibility,
)
