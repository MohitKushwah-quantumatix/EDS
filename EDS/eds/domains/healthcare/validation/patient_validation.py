"""Validate patient data business rules."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.validation.issues import ValidationIssue

__all__ = ["validate_patient_data"]


def validate_patient_data(
    datasets: Mapping[str, pl.DataFrame],
    min_addresses: int,
    max_addresses: int,
) -> list[ValidationIssue]:
    """Validate patient business rules."""
    issues: list[ValidationIssue] = []
    return issues
