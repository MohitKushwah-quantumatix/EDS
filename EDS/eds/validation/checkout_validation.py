"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.checkout_validation`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.checkout_validation import (
    CHECKOUT_DATASETS as CHECKOUT_DATASETS,
)
from eds.domains.retail.validation.checkout_validation import (
    MONEY_TOLERANCE as MONEY_TOLERANCE,
)
from eds.domains.retail.validation.checkout_validation import (
    CartStatus as CartStatus,
)
from eds.domains.retail.validation.checkout_validation import (
    CheckoutStatus as CheckoutStatus,
)
from eds.domains.retail.validation.checkout_validation import (
    ValidationError as ValidationError,
)
from eds.domains.retail.validation.checkout_validation import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.checkout_validation import (
    assert_valid_checkout_data as assert_valid_checkout_data,
)
from eds.domains.retail.validation.checkout_validation import (
    validate_addresses_belong_to_the_customer as validate_addresses_belong_to_the_customer,
)
from eds.domains.retail.validation.checkout_validation import (
    validate_cart_eligibility as validate_cart_eligibility,
)
from eds.domains.retail.validation.checkout_validation import (
    validate_checkout_data as validate_checkout_data,
)
from eds.domains.retail.validation.checkout_validation import (
    validate_checkout_timeline as validate_checkout_timeline,
)
from eds.domains.retail.validation.checkout_validation import (
    validate_referential_integrity as validate_referential_integrity,
)
from eds.domains.retail.validation.checkout_validation import (
    validate_totals as validate_totals,
)
