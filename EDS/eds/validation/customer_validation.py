"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.customer_validation`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.customer_validation import (
    CUSTOMER_DATASETS as CUSTOMER_DATASETS,
)
from eds.domains.retail.validation.customer_validation import (
    ValidationError as ValidationError,
)
from eds.domains.retail.validation.customer_validation import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.customer_validation import (
    assert_valid_customer_data as assert_valid_customer_data,
)
from eds.domains.retail.validation.customer_validation import (
    validate_address_cardinality as validate_address_cardinality,
)
from eds.domains.retail.validation.customer_validation import (
    validate_customer_data as validate_customer_data,
)
from eds.domains.retail.validation.customer_validation import (
    validate_customer_fields as validate_customer_fields,
)
from eds.domains.retail.validation.customer_validation import (
    validate_loyalty as validate_loyalty,
)
from eds.domains.retail.validation.customer_validation import (
    validate_one_record_per_customer as validate_one_record_per_customer,
)
from eds.domains.retail.validation.customer_validation import (
    validate_referential_integrity as validate_referential_integrity,
)
