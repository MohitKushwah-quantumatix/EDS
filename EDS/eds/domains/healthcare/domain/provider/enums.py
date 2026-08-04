"""Enumerations for the provider domain.

These live beside the provider schema so F003 adds no risk to the
master data feature.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ProviderStatus",
]


class ProviderStatus(StrEnum):
    """Current employment status of a provider."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"
