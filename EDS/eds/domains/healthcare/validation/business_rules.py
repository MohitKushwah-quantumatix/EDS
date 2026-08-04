"""Cross-cutting temporal validation rules for Healthcare."""

from __future__ import annotations

from collections.abc import Mapping

from eds.core.validation.issues import ValidationIssue

__all__ = ["validate_healthcare_business_rules"]


def validate_healthcare_business_rules(
    datasets: Mapping[str, pl.DataFrame],
) -> list[ValidationIssue]:
    """Validate cross-cutting Healthcare business rules."""
    issues: list[ValidationIssue] = []
    return issues
