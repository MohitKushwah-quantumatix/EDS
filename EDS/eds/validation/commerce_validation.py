"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.commerce_validation`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.commerce_validation import (
    COMMERCE_DATASETS as COMMERCE_DATASETS,
)
from eds.domains.retail.validation.commerce_validation import (
    ValidationError as ValidationError,
)
from eds.domains.retail.validation.commerce_validation import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.commerce_validation import (
    assert_valid_commerce_data as assert_valid_commerce_data,
)
from eds.domains.retail.validation.commerce_validation import (
    validate_cart_item_source as validate_cart_item_source,
)
from eds.domains.retail.validation.commerce_validation import (
    validate_cart_timeline as validate_cart_timeline,
)
from eds.domains.retail.validation.commerce_validation import (
    validate_commerce_data as validate_commerce_data,
)
from eds.domains.retail.validation.commerce_validation import (
    validate_item_counts as validate_item_counts,
)
from eds.domains.retail.validation.commerce_validation import (
    validate_quantities as validate_quantities,
)
from eds.domains.retail.validation.commerce_validation import (
    validate_referential_integrity as validate_referential_integrity,
)
