"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.commercial.schema`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.commercial.schema import (
    COMMERCIAL_DATASETS as COMMERCIAL_DATASETS,
)
from eds.domains.retail.domain.commercial.schema import (
    COUPON_TYPES as COUPON_TYPES,
)
from eds.domains.retail.domain.commercial.schema import (
    PAYMENT_METHODS as PAYMENT_METHODS,
)
from eds.domains.retail.domain.commercial.schema import (
    RETURN_REASONS as RETURN_REASONS,
)
from eds.domains.retail.domain.commercial.schema import (
    SHIPPING_METHODS as SHIPPING_METHODS,
)
from eds.domains.retail.domain.commercial.schema import (
    TAX_CODES as TAX_CODES,
)
from eds.domains.retail.domain.commercial.schema import (
    Dataset as Dataset,
)
from eds.domains.retail.domain.commercial.schema import (
    ForeignKey as ForeignKey,
)
