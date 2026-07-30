"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commercial.generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commercial.generator import (
    COUPON_TYPES as COUPON_TYPES,
)
from eds.domains.retail.generators.commercial.generator import (
    PAYMENT_METHODS as PAYMENT_METHODS,
)
from eds.domains.retail.generators.commercial.generator import (
    RETURN_REASONS as RETURN_REASONS,
)
from eds.domains.retail.generators.commercial.generator import (
    SHIPPING_METHODS as SHIPPING_METHODS,
)
from eds.domains.retail.generators.commercial.generator import (
    TAX_CODES as TAX_CODES,
)
from eds.domains.retail.generators.commercial.generator import (
    CouponDiscountType as CouponDiscountType,
)
from eds.domains.retail.generators.commercial.generator import (
    MasterDataConfig as MasterDataConfig,
)
from eds.domains.retail.generators.commercial.generator import (
    PaymentMethodType as PaymentMethodType,
)
from eds.domains.retail.generators.commercial.generator import (
    ServiceLevel as ServiceLevel,
)
from eds.domains.retail.generators.commercial.generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.commercial.generator import (
    generate_coupon_types as generate_coupon_types,
)
from eds.domains.retail.generators.commercial.generator import (
    generate_payment_methods as generate_payment_methods,
)
from eds.domains.retail.generators.commercial.generator import (
    generate_return_reasons as generate_return_reasons,
)
from eds.domains.retail.generators.commercial.generator import (
    generate_shipping_methods as generate_shipping_methods,
)
from eds.domains.retail.generators.commercial.generator import (
    generate_tax_codes as generate_tax_codes,
)
