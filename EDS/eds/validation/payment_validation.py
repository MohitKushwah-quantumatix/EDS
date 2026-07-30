"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.payment_validation`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.payment_validation import (
    CURRENCY_PATTERN as CURRENCY_PATTERN,
)
from eds.domains.retail.validation.payment_validation import (
    PAYMENT_DATASETS as PAYMENT_DATASETS,
)
from eds.domains.retail.validation.payment_validation import (
    PAYMENT_INITIAL_STATUSES as PAYMENT_INITIAL_STATUSES,
)
from eds.domains.retail.validation.payment_validation import (
    PAYMENT_REFERENCE_PATTERN as PAYMENT_REFERENCE_PATTERN,
)
from eds.domains.retail.validation.payment_validation import (
    PAYMENT_TRANSITIONS as PAYMENT_TRANSITIONS,
)
from eds.domains.retail.validation.payment_validation import (
    PROVIDER_BY_METHOD as PROVIDER_BY_METHOD,
)
from eds.domains.retail.validation.payment_validation import (
    PaymentStatus as PaymentStatus,
)
from eds.domains.retail.validation.payment_validation import (
    ValidationError as ValidationError,
)
from eds.domains.retail.validation.payment_validation import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.payment_validation import (
    assert_valid_payment_data as assert_valid_payment_data,
)
from eds.domains.retail.validation.payment_validation import (
    validate_order_coverage as validate_order_coverage,
)
from eds.domains.retail.validation.payment_validation import (
    validate_payment_amounts as validate_payment_amounts,
)
from eds.domains.retail.validation.payment_validation import (
    validate_payment_data as validate_payment_data,
)
from eds.domains.retail.validation.payment_validation import (
    validate_payment_method as validate_payment_method,
)
from eds.domains.retail.validation.payment_validation import (
    validate_payment_references as validate_payment_references,
)
from eds.domains.retail.validation.payment_validation import (
    validate_payment_status_history as validate_payment_status_history,
)
from eds.domains.retail.validation.payment_validation import (
    validate_payment_timeline as validate_payment_timeline,
)
from eds.domains.retail.validation.payment_validation import (
    validate_referential_integrity as validate_referential_integrity,
)
