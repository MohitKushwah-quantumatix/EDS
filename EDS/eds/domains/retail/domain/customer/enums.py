"""Enumerations for the customer master data domain.

These live beside the customer schema rather than in
:mod:`eds.domains.retail.domain.enums`, which holds the F001 system reference values. Keeping
them separate means F002 adds no risk to the master data feature.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "AcquisitionChannel",
    "AddressType",
    "CustomerSegment",
    "CustomerStatus",
    "Gender",
    "LifecycleStage",
    "LoyaltyStatus",
    "LoyaltyTier",
    "RegistrationSource",
]


class Gender(StrEnum):
    """Gender recorded on a customer profile."""

    MALE = "MALE"
    FEMALE = "FEMALE"
    NON_BINARY = "NON_BINARY"
    UNDISCLOSED = "UNDISCLOSED"


class CustomerStatus(StrEnum):
    """Account status of a customer."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CustomerSegment(StrEnum):
    """Commercial segment a customer belongs to."""

    NEW = "NEW"
    REGULAR = "REGULAR"
    PREMIUM = "PREMIUM"
    VIP = "VIP"


class RegistrationSource(StrEnum):
    """Channel the customer registered through."""

    WEB = "WEB"
    ANDROID_APP = "ANDROID_APP"
    IOS_APP = "IOS_APP"
    PARTNER_PORTAL = "PARTNER_PORTAL"


class AcquisitionChannel(StrEnum):
    """Marketing channel that acquired the customer."""

    ORGANIC_SEARCH = "ORGANIC_SEARCH"
    PAID_SEARCH = "PAID_SEARCH"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    EMAIL_CAMPAIGN = "EMAIL_CAMPAIGN"
    REFERRAL = "REFERRAL"
    DIRECT = "DIRECT"


class LifecycleStage(StrEnum):
    """Where the customer sits in the relationship lifecycle.

    Derived from account status and tenure rather than sampled, so the stage
    never contradicts the status it is reported alongside.
    """

    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    DORMANT = "DORMANT"
    CHURNED = "CHURNED"


class AddressType(StrEnum):
    """Purpose an address serves."""

    HOME = "HOME"
    WORK = "WORK"
    BILLING = "BILLING"
    SHIPPING = "SHIPPING"
    OTHER = "OTHER"


class LoyaltyTier(StrEnum):
    """Loyalty programme tier."""

    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class LoyaltyStatus(StrEnum):
    """Membership status in the loyalty programme."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    CLOSED = "CLOSED"
