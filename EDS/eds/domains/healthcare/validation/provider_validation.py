"""Validate provider data business rules."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.validation.issues import ValidationIssue

__all__ = ["validate_provider_data"]


def validate_provider_data(
    datasets: Mapping[str, pl.DataFrame],
) -> list[ValidationIssue]:
    """Validate provider business rules."""
    issues: list[ValidationIssue] = []
    return issues
