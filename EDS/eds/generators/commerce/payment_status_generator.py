"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.payment_status_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.payment_status_generator import (
    PAYMENT_STATUS_HISTORY as PAYMENT_STATUS_HISTORY,
)
from eds.domains.retail.generators.commerce.payment_status_generator import (
    PaymentConfig as PaymentConfig,
)
from eds.domains.retail.generators.commerce.payment_status_generator import (
    PaymentStatus as PaymentStatus,
)
from eds.domains.retail.generators.commerce.payment_status_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.payment_status_generator import (
    generate_payment_status_history as generate_payment_status_history,
)
from eds.domains.retail.generators.commerce.payment_status_generator import (
    iter_payment_status_batches as iter_payment_status_batches,
)
from eds.domains.retail.generators.commerce.payment_status_generator import (
    make_rng as make_rng,
)
