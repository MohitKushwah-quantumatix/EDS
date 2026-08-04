"""Enumerations for the billing domain.

These live beside the billing schema so F006 adds no risk to the
encounter feature.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ClaimStatus",
    "PaymentMethod",
]


class ClaimStatus(StrEnum):
    """Current status of an insurance claim."""

    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class PaymentMethod(StrEnum):
    """Payment method used for billing."""

    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"
    UPI = "UPI"
    NET_BANKING = "NET_BANKING"
    WALLET = "WALLET"
    INSURANCE = "INSURANCE"
    CASH = "CASH"
