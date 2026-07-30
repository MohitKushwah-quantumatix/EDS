"""Combined validation entry point for generated master data.

Runs referential integrity first, then business rules, and reports every issue
found rather than stopping at the first - a generation run that produced two
kinds of defect should surface both in one pass.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.validation.issues import ValidationError, ValidationIssue
from eds.domains.retail.validation.business_rules import validate_business_rules
from eds.domains.retail.validation.referential import validate_referential_integrity

__all__ = ["assert_valid_master_data", "validate_master_data"]


def validate_master_data(datasets: Mapping[str, pl.DataFrame]) -> list[ValidationIssue]:
    """Validate schema, referential integrity, and business rules.

    Args:
        datasets: Generated datasets, keyed by name.

    Returns:
        Every issue found. An empty list means the data satisfies the F001
        success criteria.
    """
    return [*validate_referential_integrity(datasets), *validate_business_rules(datasets)]


def assert_valid_master_data(datasets: Mapping[str, pl.DataFrame]) -> None:
    """Validate datasets and raise if anything is wrong.

    Args:
        datasets: Generated datasets, keyed by name.

    Raises:
        ValidationError: If any validation issue is found.
    """
    issues = validate_master_data(datasets)
    if issues:
        raise ValidationError(issues)
