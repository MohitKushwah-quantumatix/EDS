"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.order_validation`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.order_validation import (
    MONEY_TOLERANCE as MONEY_TOLERANCE,
)
from eds.domains.retail.validation.order_validation import (
    ORDER_DATASETS as ORDER_DATASETS,
)
from eds.domains.retail.validation.order_validation import (
    ORDER_LIFECYCLE as ORDER_LIFECYCLE,
)
from eds.domains.retail.validation.order_validation import (
    ORDER_NUMBER_PATTERN as ORDER_NUMBER_PATTERN,
)
from eds.domains.retail.validation.order_validation import (
    CheckoutStatus as CheckoutStatus,
)
from eds.domains.retail.validation.order_validation import (
    OrderStatus as OrderStatus,
)
from eds.domains.retail.validation.order_validation import (
    ValidationError as ValidationError,
)
from eds.domains.retail.validation.order_validation import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.order_validation import (
    assert_valid_order_data as assert_valid_order_data,
)
from eds.domains.retail.validation.order_validation import (
    validate_checkout_eligibility as validate_checkout_eligibility,
)
from eds.domains.retail.validation.order_validation import (
    validate_financial_copy as validate_financial_copy,
)
from eds.domains.retail.validation.order_validation import (
    validate_line_reconciliation as validate_line_reconciliation,
)
from eds.domains.retail.validation.order_validation import (
    validate_order_data as validate_order_data,
)
from eds.domains.retail.validation.order_validation import (
    validate_order_numbers as validate_order_numbers,
)
from eds.domains.retail.validation.order_validation import (
    validate_order_timeline as validate_order_timeline,
)
from eds.domains.retail.validation.order_validation import (
    validate_referential_integrity as validate_referential_integrity,
)
from eds.domains.retail.validation.order_validation import (
    validate_status_history as validate_status_history,
)
