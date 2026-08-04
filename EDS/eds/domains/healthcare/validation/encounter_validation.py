"""Validate encounter data business rules."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.validation.issues import ValidationIssue

__all__ = ["validate_encounter_data"]


def validate_encounter_data(
    datasets: Mapping[str, pl.DataFrame],
) -> list[ValidationIssue]:
    """Validate encounter business rules."""
    issues: list[ValidationIssue] = []
    return issues
