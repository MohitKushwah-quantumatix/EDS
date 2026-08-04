"""Enumerations for the encounter domain.

These live beside the encounter schema so F004 adds no risk to the
master data feature.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "EncounterStatus",
    "AppointmentStatus",
]


class EncounterStatus(StrEnum):
    """Current status of an encounter."""

    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AppointmentStatus(StrEnum):
    """Status of a scheduled appointment."""

    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
