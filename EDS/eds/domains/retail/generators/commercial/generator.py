"""Generators for the commercial master datasets.

Payment methods, shipping methods, and coupon programmes are fixed catalogues
rather than random draws: a real retailer offers a knowable, stable set, so
randomising them would reduce realism instead of increasing it. These
generators are therefore deterministic without consulting the seed.

Tax codes are the exception - they are emitted per configured country, because
a tax code without a country is meaningless.
"""

from __future__ import annotations

from typing import Final, NamedTuple

import polars as pl

from eds.config import MasterDataConfig
from eds.core.frames import build_frame
from eds.domains.retail.domain.commercial.schema import (
    COUPON_TYPES,
    PAYMENT_METHODS,
    RETURN_REASONS,
    SHIPPING_METHODS,
    TAX_CODES,
)
from eds.domains.retail.domain.enums import CouponDiscountType, PaymentMethodType, ServiceLevel

__all__ = [
    "generate_coupon_types",
    "generate_payment_methods",
    "generate_return_reasons",
    "generate_shipping_methods",
    "generate_tax_codes",
]


class _PaymentMethodRow(NamedTuple):
    """A fixed payment method catalogue entry."""

    code: str
    name: str
    method_type: PaymentMethodType
    fee_pct: float
    requires_authorization: bool
    is_active: bool


class _ShippingMethodRow(NamedTuple):
    """A fixed shipping method catalogue entry."""

    code: str
    name: str
    carrier: str
    service_level: ServiceLevel
    min_days: int
    max_days: int
    base_cost: float
    cost_per_kg: float
    is_active: bool


class _CouponTypeRow(NamedTuple):
    """A fixed coupon programme catalogue entry."""

    prefix: str
    name: str
    discount_type: CouponDiscountType
    discount_value: float
    min_order_value: float
    max_discount_value: float
    is_active: bool


class _TaxCodeRow(NamedTuple):
    """A tax code template applied per country."""

    code: str
    description: str
    rate_pct: float
    is_active: bool


class _ReturnReasonRow(NamedTuple):
    """A fixed return reason catalogue entry."""

    code: str
    name: str
    is_customer_fault: bool
    requires_inspection: bool
    is_active: bool


_PAYMENT_METHODS: Final[tuple[_PaymentMethodRow, ...]] = (
    _PaymentMethodRow("VISA", "Visa Credit Card", PaymentMethodType.CARD, 1.80, True, True),
    _PaymentMethodRow("MC", "Mastercard", PaymentMethodType.CARD, 1.80, True, True),
    _PaymentMethodRow("AMEX", "American Express", PaymentMethodType.CARD, 2.90, True, True),
    _PaymentMethodRow("DISC", "Discover", PaymentMethodType.CARD, 1.95, True, True),
    _PaymentMethodRow("DEBIT", "Debit Card", PaymentMethodType.CARD, 0.85, True, True),
    _PaymentMethodRow("PAYPAL", "PayPal", PaymentMethodType.WALLET, 2.49, True, True),
    _PaymentMethodRow("APPLEPAY", "Apple Pay", PaymentMethodType.WALLET, 1.50, True, True),
    _PaymentMethodRow("GOOGLEPAY", "Google Pay", PaymentMethodType.WALLET, 1.50, True, True),
    _PaymentMethodRow("ACH", "Bank Transfer", PaymentMethodType.BANK_TRANSFER, 0.50, False, True),
    _PaymentMethodRow(
        "KLARNA", "Klarna Pay Later", PaymentMethodType.BUY_NOW_PAY_LATER, 3.50, True, True
    ),
    _PaymentMethodRow(
        "AFTERPAY", "Afterpay", PaymentMethodType.BUY_NOW_PAY_LATER, 4.00, True, True
    ),
    _PaymentMethodRow("GIFTCARD", "Gift Card", PaymentMethodType.GIFT_CARD, 0.00, False, True),
    _PaymentMethodRow(
        "COD", "Cash on Delivery", PaymentMethodType.CASH_ON_DELIVERY, 0.00, False, False
    ),
)

_SHIPPING_METHODS: Final[tuple[_ShippingMethodRow, ...]] = (
    _ShippingMethodRow(
        "ECON", "Economy Ground", "UPS", ServiceLevel.ECONOMY, 5, 8, 3.99, 0.35, True
    ),
    _ShippingMethodRow(
        "STD", "Standard Ground", "UPS", ServiceLevel.STANDARD, 3, 5, 5.99, 0.45, True
    ),
    _ShippingMethodRow(
        "STDPOST", "Standard Post", "USPS", ServiceLevel.STANDARD, 3, 6, 4.99, 0.40, True
    ),
    _ShippingMethodRow(
        "EXP2", "Express 2-Day", "FedEx", ServiceLevel.EXPRESS, 2, 2, 12.99, 0.85, True
    ),
    _ShippingMethodRow(
        "EXP3", "Express 3-Day", "FedEx", ServiceLevel.EXPRESS, 3, 3, 9.99, 0.70, True
    ),
    _ShippingMethodRow(
        "OVNT", "Overnight Priority", "FedEx", ServiceLevel.OVERNIGHT, 1, 1, 24.99, 1.50, True
    ),
    _ShippingMethodRow(
        "OVNTAM", "Overnight Before 10am", "DHL", ServiceLevel.OVERNIGHT, 1, 1, 34.99, 1.95, True
    ),
    _ShippingMethodRow(
        "SAMEDAY",
        "Same Day Courier",
        "Local Courier",
        ServiceLevel.SAME_DAY,
        0,
        1,
        19.99,
        1.20,
        True,
    ),
    _ShippingMethodRow(
        "FREIGHT", "Freight LTL", "XPO Logistics", ServiceLevel.ECONOMY, 7, 14, 89.00, 0.15, True
    ),
)

_COUPON_TYPES: Final[tuple[_CouponTypeRow, ...]] = (
    _CouponTypeRow(
        "WELCOME", "New Customer Welcome", CouponDiscountType.PERCENTAGE, 10.0, 25.0, 50.0, True
    ),
    _CouponTypeRow(
        "SAVE5", "Five Dollars Off", CouponDiscountType.FIXED_AMOUNT, 5.0, 30.0, 5.0, True
    ),
    _CouponTypeRow(
        "SAVE20", "Twenty Dollars Off", CouponDiscountType.FIXED_AMOUNT, 20.0, 100.0, 20.0, True
    ),
    _CouponTypeRow(
        "SEASONAL", "Seasonal Sale", CouponDiscountType.PERCENTAGE, 15.0, 50.0, 100.0, True
    ),
    _CouponTypeRow(
        "CLEARANCE", "Clearance Event", CouponDiscountType.PERCENTAGE, 30.0, 0.0, 250.0, True
    ),
    _CouponTypeRow(
        "FREESHIP", "Free Shipping", CouponDiscountType.FREE_SHIPPING, 0.0, 35.0, 25.0, True
    ),
    _CouponTypeRow(
        "LOYALTY", "Loyalty Reward", CouponDiscountType.PERCENTAGE, 5.0, 0.0, 40.0, True
    ),
    _CouponTypeRow(
        "WINBACK", "Lapsed Customer Winback", CouponDiscountType.PERCENTAGE, 20.0, 40.0, 75.0, False
    ),
)

#: Why a customer sends an order back. ``is_customer_fault`` separates the
#: reasons the retailer caused - a damaged or wrong item - from the ones it did
#: not, which is what a returns analyst wants to group by. Only the reasons a
#: retailer might genuinely dispute require inspection on arrival.
_RETURN_REASONS: Final[tuple[_ReturnReasonRow, ...]] = (
    _ReturnReasonRow("DAMAGED", "Damaged", False, True, True),
    _ReturnReasonRow("WRONG_ITEM", "Wrong Item", False, True, True),
    _ReturnReasonRow("DEFECTIVE", "Defective", False, True, True),
    _ReturnReasonRow("CHANGED_MIND", "Changed Mind", True, False, True),
    _ReturnReasonRow("LATE_DELIVERY", "Late Delivery", False, False, True),
)

_TAX_CODES: Final[tuple[_TaxCodeRow, ...]] = (
    _TaxCodeRow("STD", "Standard rated goods", 20.0, True),
    _TaxCodeRow("RED", "Reduced rate goods", 5.0, True),
    _TaxCodeRow("ZERO", "Zero rated goods", 0.0, True),
    _TaxCodeRow("EXEMPT", "Tax exempt goods", 0.0, True),
    _TaxCodeRow("GROCERY", "Grocery and food items", 2.5, True),
    _TaxCodeRow("ALCOHOL", "Alcohol and tobacco", 32.5, True),
    _TaxCodeRow("LUXURY", "Luxury goods surcharge", 28.0, True),
)


def generate_payment_methods() -> pl.DataFrame:
    """Generate the payment methods dataset.

    Returns:
        One row per supported payment method.
    """
    return build_frame(
        PAYMENT_METHODS,
        {
            "payment_method_id": list(range(1, len(_PAYMENT_METHODS) + 1)),
            "method_code": [row.code for row in _PAYMENT_METHODS],
            "method_name": [row.name for row in _PAYMENT_METHODS],
            "method_type": [str(row.method_type) for row in _PAYMENT_METHODS],
            "processing_fee_pct": [row.fee_pct for row in _PAYMENT_METHODS],
            "requires_authorization": [row.requires_authorization for row in _PAYMENT_METHODS],
            "is_active": [row.is_active for row in _PAYMENT_METHODS],
        },
    )


def generate_shipping_methods() -> pl.DataFrame:
    """Generate the shipping methods dataset.

    Returns:
        One row per supported shipping method.
    """
    return build_frame(
        SHIPPING_METHODS,
        {
            "shipping_method_id": list(range(1, len(_SHIPPING_METHODS) + 1)),
            "method_code": [row.code for row in _SHIPPING_METHODS],
            "method_name": [row.name for row in _SHIPPING_METHODS],
            "carrier_name": [row.carrier for row in _SHIPPING_METHODS],
            "service_level": [str(row.service_level) for row in _SHIPPING_METHODS],
            "min_transit_days": [row.min_days for row in _SHIPPING_METHODS],
            "max_transit_days": [row.max_days for row in _SHIPPING_METHODS],
            "base_cost": [row.base_cost for row in _SHIPPING_METHODS],
            "cost_per_kg": [row.cost_per_kg for row in _SHIPPING_METHODS],
            "is_active": [row.is_active for row in _SHIPPING_METHODS],
        },
    )


def generate_coupon_types() -> pl.DataFrame:
    """Generate the coupon types dataset.

    Returns:
        One row per coupon programme.
    """
    return build_frame(
        COUPON_TYPES,
        {
            "coupon_type_id": list(range(1, len(_COUPON_TYPES) + 1)),
            "coupon_code_prefix": [row.prefix for row in _COUPON_TYPES],
            "coupon_name": [row.name for row in _COUPON_TYPES],
            "discount_type": [str(row.discount_type) for row in _COUPON_TYPES],
            "discount_value": [row.discount_value for row in _COUPON_TYPES],
            "min_order_value": [row.min_order_value for row in _COUPON_TYPES],
            "max_discount_value": [row.max_discount_value for row in _COUPON_TYPES],
            "is_active": [row.is_active for row in _COUPON_TYPES],
        },
    )


def generate_return_reasons() -> pl.DataFrame:
    """Generate the return reasons dataset.

    Returns:
        One row per reason a customer may give for sending an order back.
    """
    return build_frame(
        RETURN_REASONS,
        {
            "return_reason_id": list(range(1, len(_RETURN_REASONS) + 1)),
            "reason_code": [row.code for row in _RETURN_REASONS],
            "reason_name": [row.name for row in _RETURN_REASONS],
            "is_customer_fault": [row.is_customer_fault for row in _RETURN_REASONS],
            "requires_inspection": [row.requires_inspection for row in _RETURN_REASONS],
            "is_active": [row.is_active for row in _RETURN_REASONS],
        },
    )


def generate_tax_codes(config: MasterDataConfig) -> pl.DataFrame:
    """Generate the tax codes dataset, one set per configured country.

    Args:
        config: Master data configuration, supplying the country list.

    Returns:
        ``len(countries) * len(templates)`` rows, keyed by ``tax_code_id``. The
        ``tax_code`` column is prefixed with the country code so it stays
        unique across countries.
    """
    tax_code_ids: list[int] = []
    codes: list[str] = []
    descriptions: list[str] = []
    rates: list[float] = []
    country_ids: list[int] = []
    active_flags: list[bool] = []

    next_id = 1
    for country_id, country_code in enumerate(config.countries, start=1):
        for template in _TAX_CODES:
            tax_code_ids.append(next_id)
            codes.append(f"{country_code}-{template.code}")
            descriptions.append(template.description)
            rates.append(template.rate_pct)
            country_ids.append(country_id)
            active_flags.append(template.is_active)
            next_id += 1

    return build_frame(
        TAX_CODES,
        {
            "tax_code_id": tax_code_ids,
            "tax_code": codes,
            "tax_description": descriptions,
            "tax_rate_pct": rates,
            "country_id": country_ids,
            "is_active": active_flags,
        },
    )
