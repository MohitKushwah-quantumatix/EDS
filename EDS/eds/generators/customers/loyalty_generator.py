"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.customers.loyalty_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.customers.loyalty_generator import (
    CUSTOMER_LOYALTY as CUSTOMER_LOYALTY,
)
from eds.domains.retail.generators.customers.loyalty_generator import (
    CustomerConfig as CustomerConfig,
)
from eds.domains.retail.generators.customers.loyalty_generator import (
    CustomerStatus as CustomerStatus,
)
from eds.domains.retail.generators.customers.loyalty_generator import (
    LoyaltyStatus as LoyaltyStatus,
)
from eds.domains.retail.generators.customers.loyalty_generator import (
    LoyaltyTier as LoyaltyTier,
)
from eds.domains.retail.generators.customers.loyalty_generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.customers.loyalty_generator import (
    format_code as format_code,
)
from eds.domains.retail.generators.customers.loyalty_generator import (
    generate_loyalty as generate_loyalty,
)
from eds.domains.retail.generators.customers.loyalty_generator import (
    iter_loyalty_batches as iter_loyalty_batches,
)
from eds.domains.retail.generators.customers.loyalty_generator import (
    make_rng as make_rng,
)
