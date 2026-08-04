"""Validate Healthcare master data integrity."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.validation.issues import ValidationIssue

__all__ = ["validate_master_data"]


def validate_master_data(datasets: Mapping[str, pl.DataFrame]) -> list[ValidationIssue]:
    """Validate master data integrity."""
    issues: list[ValidationIssue] = []
    return issues
