"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.checkout_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.checkout_generator import (
    CHECKOUT as CHECKOUT,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    CHECKOUT_DATASETS as CHECKOUT_DATASETS,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    MONEY_PRECISION as MONEY_PRECISION,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    REQUIRED_CHECKOUT_DATASETS as REQUIRED_CHECKOUT_DATASETS,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    SHIPPING_COST_BANDS as SHIPPING_COST_BANDS,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    CartStatus as CartStatus,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    CheckoutConfig as CheckoutConfig,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    CheckoutData as CheckoutData,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    CheckoutStatus as CheckoutStatus,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    PaymentMethod as PaymentMethod,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    ShippingMethod as ShippingMethod,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    generate_checkout_data as generate_checkout_data,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    generate_checkouts as generate_checkouts,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    iter_checkout_batches as iter_checkout_batches,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.commerce.checkout_generator import (
    resolve_seed as resolve_seed,
)
