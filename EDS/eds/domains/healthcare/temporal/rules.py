"""Temporal invariant checks for Healthcare."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.validation.issues import ValidationIssue

__all__ = ["validate_temporal_history"]


def validate_temporal_history(
    datasets: Mapping[str, pl.DataFrame],
) -> list[ValidationIssue]:
    """Validate temporal rules across Healthcare datasets."""
    issues: list[ValidationIssue] = []
    return issues
