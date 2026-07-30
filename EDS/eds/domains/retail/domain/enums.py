"""System reference enumerations shared across master data.

These cover the "System Reference" scope of F001: currency, units of measure,
product status, and warehouse status. They are emitted as string columns so
the Parquet output stays portable across Spark, Snowflake, and SQL Server.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "CouponDiscountType",
    "Currency",
    "PaymentMethodType",
    "ProductStatus",
    "ServiceLevel",
    "SupplierTier",
    "UnitOfMeasure",
    "WarehouseStatus",
]


class Currency(StrEnum):
    """ISO 4217 currency codes supported by the simulator."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CAD = "CAD"
    INR = "INR"
    AUD = "AUD"


class UnitOfMeasure(StrEnum):
    """Units in which a product is sold."""

    EACH = "EACH"
    PACK = "PACK"
    CASE = "CASE"
    KILOGRAM = "KG"
    GRAM = "G"
    LITRE = "L"
    MILLILITRE = "ML"
    METRE = "M"


class ProductStatus(StrEnum):
    """Lifecycle status of a catalog product."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DISCONTINUED = "DISCONTINUED"
    PENDING_LAUNCH = "PENDING_LAUNCH"


class WarehouseStatus(StrEnum):
    """Operational status of a warehouse."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    MAINTENANCE = "MAINTENANCE"
    CLOSED = "CLOSED"


class SupplierTier(StrEnum):
    """Commercial tier a supplier is managed under."""

    STRATEGIC = "STRATEGIC"
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    TRANSACTIONAL = "TRANSACTIONAL"


class PaymentMethodType(StrEnum):
    """Category a payment method belongs to."""

    CARD = "CARD"
    WALLET = "WALLET"
    BANK_TRANSFER = "BANK_TRANSFER"
    BUY_NOW_PAY_LATER = "BUY_NOW_PAY_LATER"
    GIFT_CARD = "GIFT_CARD"
    CASH_ON_DELIVERY = "CASH_ON_DELIVERY"


class ServiceLevel(StrEnum):
    """Delivery speed offered by a shipping method."""

    ECONOMY = "ECONOMY"
    STANDARD = "STANDARD"
    EXPRESS = "EXPRESS"
    OVERNIGHT = "OVERNIGHT"
    SAME_DAY = "SAME_DAY"


class CouponDiscountType(StrEnum):
    """How a coupon reduces order value."""

    PERCENTAGE = "PERCENTAGE"
    FIXED_AMOUNT = "FIXED_AMOUNT"
    FREE_SHIPPING = "FREE_SHIPPING"
