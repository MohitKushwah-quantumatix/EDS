"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.payment_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.payment_generator import (
    PAYMENT_PROVIDER_BY_METHOD as PAYMENT_PROVIDER_BY_METHOD,
)
from eds.domains.retail.generators.commerce.payment_generator import (
    PAYMENT_REFERENCE_SEQUENCE_WIDTH as PAYMENT_REFERENCE_SEQUENCE_WIDTH,
)
from eds.domains.retail.generators.commerce.payment_generator import (
    PAYMENTS as PAYMENTS,
)
from eds.domains.retail.generators.commerce.payment_generator import (
    PROVIDER_BY_METHOD as PROVIDER_BY_METHOD,
)
from eds.domains.retail.generators.commerce.payment_generator import (
    PaymentConfig as PaymentConfig,
)
from eds.domains.retail.generators.commerce.payment_generator import (
    PaymentStatus as PaymentStatus,
)
from eds.domains.retail.generators.commerce.payment_generator import (
    apply_payment_status as apply_payment_status,
)
from eds.domains.retail.generators.commerce.payment_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.payment_generator import (
    generate_payments as generate_payments,
)
from eds.domains.retail.generators.commerce.payment_generator import (
    iter_payment_batches as iter_payment_batches,
)
from eds.domains.retail.generators.commerce.payment_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.commerce.payment_generator import (
    payment_reference_expression as payment_reference_expression,
)
