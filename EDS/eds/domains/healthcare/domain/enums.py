"""System reference enumerations shared across healthcare.

These cover the "System Reference" scope: patient status, provider type,
encounter type, billing status, insurance type, room status, medication
form, admit source, and discharge disposition. They are emitted as string
columns so the Parquet output stays portable across Spark, Snowflake, and
SQL Server.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "PatientStatus",
    "ProviderType",
    "EncounterType",
    "BillingStatus",
    "InsuranceType",
    "RoomStatus",
    "MedicationForm",
    "AdmitSource",
    "DischargeDisposition",
]


class PatientStatus(StrEnum):
    """Current status of a patient."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    TRANSFERRED = "TRANSFERRED"
    DECEASED = "DECEASED"


class ProviderType(StrEnum):
    """Category a provider belongs to."""

    PHYSICIAN = "PHYSICIAN"
    NURSE = "NURSE"
    SPECIALIST = "SPECIALIST"
    TECHNICIAN = "TECHNICIAN"
    ADMIN = "ADMIN"


class EncounterType(StrEnum):
    """Type of patient encounter."""

    INPATIENT = "INPATIENT"
    OUTPATIENT = "OUTPATIENT"
    EMERGENCY = "EMERGENCY"
    TELEHEALTH = "TELEHEALTH"


class BillingStatus(StrEnum):
    """Current status of a billing record."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class InsuranceType(StrEnum):
    """Category of insurance coverage."""

    PRIVATE = "PRIVATE"
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    SELF_PAY = "SELF_PAY"


class RoomStatus(StrEnum):
    """Operational status of a room."""

    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    MAINTENANCE = "MAINTENANCE"
    CLOSED = "CLOSED"


class MedicationForm(StrEnum):
    """Physical form of a medication."""

    TABLET = "TABLET"
    CAPSULE = "CAPSULE"
    INJECTION = "INJECTION"
    TOPICAL = "TOPICAL"
    INHALER = "INHALER"
    LIQUID = "LIQUID"
    PATCH = "PATCH"
    DROPS = "DROPS"
    SUPPOSITORY = "SUPPOSITORY"
    INTRAVENOUS = "INTRAVENOUS"


class AdmitSource(StrEnum):
    """How a patient was admitted for an encounter."""

    EMERGENCY = "EMERGENCY"
    REFERRAL = "REFERRAL"
    TRANSFER = "TRANSFER"
    DIRECT_ADMIT = "DIRECT_ADMIT"


class DischargeDisposition(StrEnum):
    """Where a patient was discharged to."""

    HOME = "HOME"
    TRANSFER = "TRANSFER"
    DECEASED = "DECEASED"
    LEFT_AMALGAMATED = "LEFT_AMALGAMATED"
