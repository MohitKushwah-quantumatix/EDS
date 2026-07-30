"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.enums`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.enums import (
    CouponDiscountType as CouponDiscountType,
)
from eds.domains.retail.domain.enums import (
    Currency as Currency,
)
from eds.domains.retail.domain.enums import (
    PaymentMethodType as PaymentMethodType,
)
from eds.domains.retail.domain.enums import (
    ProductStatus as ProductStatus,
)
from eds.domains.retail.domain.enums import (
    ServiceLevel as ServiceLevel,
)
from eds.domains.retail.domain.enums import (
    SupplierTier as SupplierTier,
)
from eds.domains.retail.domain.enums import (
    UnitOfMeasure as UnitOfMeasure,
)
from eds.domains.retail.domain.enums import (
    WarehouseStatus as WarehouseStatus,
)
