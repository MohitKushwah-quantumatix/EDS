"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.master_data`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.master_data import (
    ValidationError as ValidationError,
)
from eds.domains.retail.validation.master_data import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.master_data import (
    assert_valid_master_data as assert_valid_master_data,
)
from eds.domains.retail.validation.master_data import (
    validate_business_rules as validate_business_rules,
)
from eds.domains.retail.validation.master_data import (
    validate_master_data as validate_master_data,
)
from eds.domains.retail.validation.master_data import (
    validate_referential_integrity as validate_referential_integrity,
)
