"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.business_rules`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.business_rules import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.business_rules import (
    validate_business_rules as validate_business_rules,
)
from eds.domains.retail.validation.business_rules import (
    validate_categories as validate_categories,
)
from eds.domains.retail.validation.business_rules import (
    validate_geography as validate_geography,
)
from eds.domains.retail.validation.business_rules import (
    validate_inventory as validate_inventory,
)
from eds.domains.retail.validation.business_rules import (
    validate_products as validate_products,
)
from eds.domains.retail.validation.business_rules import (
    validate_suppliers as validate_suppliers,
)
from eds.domains.retail.validation.business_rules import (
    validate_warehouses as validate_warehouses,
)
