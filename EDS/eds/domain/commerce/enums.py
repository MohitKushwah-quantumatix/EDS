"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.commerce.enums`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.commerce.enums import (
    ORDER_LIFECYCLE as ORDER_LIFECYCLE,
)
from eds.domains.retail.domain.commerce.enums import (
    PAYMENT_INITIAL_STATUSES as PAYMENT_INITIAL_STATUSES,
)
from eds.domains.retail.domain.commerce.enums import (
    PAYMENT_PROVIDER_BY_METHOD as PAYMENT_PROVIDER_BY_METHOD,
)
from eds.domains.retail.domain.commerce.enums import (
    PAYMENT_TRANSITIONS as PAYMENT_TRANSITIONS,
)
from eds.domains.retail.domain.commerce.enums import (
    RETURN_LIFECYCLE as RETURN_LIFECYCLE,
)
from eds.domains.retail.domain.commerce.enums import (
    SHIPMENT_LIFECYCLE as SHIPMENT_LIFECYCLE,
)
from eds.domains.retail.domain.commerce.enums import (
    CartItemSource as CartItemSource,
)
from eds.domains.retail.domain.commerce.enums import (
    CartStatus as CartStatus,
)
from eds.domains.retail.domain.commerce.enums import (
    CheckoutStatus as CheckoutStatus,
)
from eds.domains.retail.domain.commerce.enums import (
    OrderStatus as OrderStatus,
)
from eds.domains.retail.domain.commerce.enums import (
    PaymentMethod as PaymentMethod,
)
from eds.domains.retail.domain.commerce.enums import (
    PaymentProvider as PaymentProvider,
)
from eds.domains.retail.domain.commerce.enums import (
    PaymentStatus as PaymentStatus,
)
from eds.domains.retail.domain.commerce.enums import (
    ReturnStatus as ReturnStatus,
)
from eds.domains.retail.domain.commerce.enums import (
    ShipmentStatus as ShipmentStatus,
)
from eds.domains.retail.domain.commerce.enums import (
    ShippingMethod as ShippingMethod,
)
