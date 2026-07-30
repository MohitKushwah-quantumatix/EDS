"""Enumerations for the commerce domain.

These live beside the commerce schema rather than in the journey enums, so
F004 adds no risk to the customer journey features.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ORDER_LIFECYCLE",
    "PAYMENT_INITIAL_STATUSES",
    "PAYMENT_PROVIDER_BY_METHOD",
    "PAYMENT_TRANSITIONS",
    "RETURN_LIFECYCLE",
    "SHIPMENT_LIFECYCLE",
    "CartItemSource",
    "CartStatus",
    "CheckoutStatus",
    "OrderStatus",
    "PaymentMethod",
    "PaymentProvider",
    "PaymentStatus",
    "ReturnStatus",
    "ShipmentStatus",
    "ShippingMethod",
]


class CartStatus(StrEnum):
    """Where a shopping cart ended up."""

    ACTIVE = "ACTIVE"
    ABANDONED = "ABANDONED"
    CHECKED_OUT = "CHECKED_OUT"


class CartItemSource(StrEnum):
    """What the customer added an item from."""

    PRODUCT_VIEW = "PRODUCT_VIEW"
    WISHLIST = "WISHLIST"


class CheckoutStatus(StrEnum):
    """How a checkout attempt ended."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class OrderStatus(StrEnum):
    """A stage in the order lifecycle.

    Only the first three stages exist today. ``PACKED``, ``SHIPPED`` and
    ``DELIVERED`` belong to later features and are deliberately absent rather
    than declared and unused, so a validator cannot pass data that claims a
    stage nothing yet generates.
    """

    CREATED = "CREATED"
    CONFIRMED = "CONFIRMED"
    PROCESSING = "PROCESSING"


#: The lifecycle in order. An order walks a prefix of this sequence.
ORDER_LIFECYCLE: tuple[OrderStatus, ...] = (
    OrderStatus.CREATED,
    OrderStatus.CONFIRMED,
    OrderStatus.PROCESSING,
)


class ShippingMethod(StrEnum):
    """Delivery option chosen at checkout.

    These are the checkout's own options, chosen from the values F005
    specifies. They are deliberately not the F001 ``shipping_methods``
    reference table, which carries a different, carrier-level vocabulary.
    """

    STANDARD = "STANDARD"
    EXPRESS = "EXPRESS"
    NEXT_DAY = "NEXT_DAY"
    STORE_PICKUP = "STORE_PICKUP"


class PaymentMethod(StrEnum):
    """Payment option chosen at checkout.

    As with :class:`ShippingMethod`, these are the checkout's own options
    rather than the F001 ``payment_methods`` reference table.
    """

    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"
    UPI = "UPI"
    NET_BANKING = "NET_BANKING"
    WALLET = "WALLET"
    COD = "COD"


class PaymentProvider(StrEnum):
    """The processor that handles a payment.

    Derived from the payment method rather than chosen: a customer paying by
    card does not also pick who settles it.
    """

    STRIPE = "Stripe"
    UPI_GATEWAY = "UPI Gateway"
    BANK_GATEWAY = "Bank Gateway"
    WALLET_PROVIDER = "Wallet Provider"
    CASH_ON_DELIVERY = "Cash On Delivery"


#: Which provider handles each payment method. Every method maps to exactly
#: one provider, so the column is fully derived.
PAYMENT_PROVIDER_BY_METHOD: dict[PaymentMethod, PaymentProvider] = {
    PaymentMethod.UPI: PaymentProvider.UPI_GATEWAY,
    PaymentMethod.CREDIT_CARD: PaymentProvider.STRIPE,
    PaymentMethod.DEBIT_CARD: PaymentProvider.STRIPE,
    PaymentMethod.NET_BANKING: PaymentProvider.BANK_GATEWAY,
    PaymentMethod.COD: PaymentProvider.CASH_ON_DELIVERY,
    PaymentMethod.WALLET: PaymentProvider.WALLET_PROVIDER,
}


class PaymentStatus(StrEnum):
    """How a payment attempt ended.

    A payment either fails outright, or is authorised and then either
    captured or voided.
    """

    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


#: How a payment may open. Unlike the order lifecycle, which is a single
#: sequence, a payment either starts by being authorised or never gets that
#: far, so there are two valid first statuses rather than one.
PAYMENT_INITIAL_STATUSES: tuple[PaymentStatus, ...] = (
    PaymentStatus.AUTHORIZED,
    PaymentStatus.FAILED,
)

#: What may follow each status. ``CAPTURED``, ``VOIDED`` and ``FAILED`` are
#: terminal: reversing a capture is a refund, which is a later feature.
PAYMENT_TRANSITIONS: dict[PaymentStatus, tuple[PaymentStatus, ...]] = {
    PaymentStatus.AUTHORIZED: (PaymentStatus.CAPTURED, PaymentStatus.VOIDED),
    PaymentStatus.CAPTURED: (),
    PaymentStatus.VOIDED: (),
    PaymentStatus.FAILED: (),
}


class ShipmentStatus(StrEnum):
    """A stage in the shipment lifecycle.

    This is the shipment's own progression, deliberately separate from
    :class:`OrderStatus`. F006 is frozen under ADR-006, so the order lifecycle
    is not extended to carry fulfilment stages; the shipment records them
    instead, which is also what ADR-011 asks for - one dataset, and one
    lifecycle, per business entity.

    ``RETURNED``, ``LOST`` and ``DAMAGED`` belong to later features and are
    deliberately absent rather than declared and unused, so a validator cannot
    pass data claiming a stage nothing yet generates.
    """

    CREATED = "CREATED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


#: The lifecycle in order. A shipment walks a prefix of this sequence, and
#: always reaches at least ``SHIPPED``.
SHIPMENT_LIFECYCLE: tuple[ShipmentStatus, ...] = (
    ShipmentStatus.CREATED,
    ShipmentStatus.PACKED,
    ShipmentStatus.SHIPPED,
    ShipmentStatus.IN_TRANSIT,
    ShipmentStatus.DELIVERED,
)


class ReturnStatus(StrEnum):
    """A stage in the return lifecycle.

    This is the reverse journey, and it is deliberately separate from
    :class:`ShipmentStatus` even though both carry an ``IN_TRANSIT`` stage:
    there the parcel is travelling to the customer, here it is travelling back.
    ADR-011 asks for one lifecycle per business entity.

    ``REJECTED``, ``CANCELLED`` and ``REFUNDED`` belong to later finance
    extensions and are deliberately absent rather than declared and unused, so
    a validator cannot pass data claiming a stage nothing yet generates.
    """

    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    COMPLETED = "COMPLETED"


#: The lifecycle in order. A return walks a prefix of this sequence, and always
#: reaches at least ``APPROVED``.
RETURN_LIFECYCLE: tuple[ReturnStatus, ...] = (
    ReturnStatus.REQUESTED,
    ReturnStatus.APPROVED,
    ReturnStatus.IN_TRANSIT,
    ReturnStatus.RECEIVED,
    ReturnStatus.COMPLETED,
)
