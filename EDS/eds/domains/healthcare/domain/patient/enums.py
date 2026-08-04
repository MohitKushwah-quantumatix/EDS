"""Enumerations for the patient domain.

These live beside the patient schema so F002 adds no risk to the
master data feature.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "PatientGender",
    "PatientSegment",
]


class PatientGender(StrEnum):
    """Gender recorded on a patient profile."""

    MALE = "MALE"
    FEMALE = "FEMALE"
    NON_BINARY = "NON_BINARY"
    UNDISCLOSED = "UNDISCLOSED"


class PatientSegment(StrEnum):
    """Commercial segment a patient belongs to."""

    NEW = "NEW"
    REGULAR = "REGULAR"
    PREMIUM = "PREMIUM"
    VIP = "VIP"
