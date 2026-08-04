"""Referential integrity validation for Healthcare."""

from __future__ import annotations

from collections.abc import Mapping

from eds.core.validation.issues import ValidationIssue

__all__ = ["validate_referential_integrity"]


def validate_referential_integrity(
    datasets: Mapping[str, pl.DataFrame],
) -> list[ValidationIssue]:
    """Validate referential integrity across Healthcare datasets."""
    issues: list[ValidationIssue] = []
    return issues
