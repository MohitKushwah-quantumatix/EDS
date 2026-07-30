"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.payments`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.payments import (
    PAYMENT_DATASETS as PAYMENT_DATASETS,
)
from eds.domains.retail.generators.commerce.payments import (
    REQUIRED_PAYMENT_DATASETS as REQUIRED_PAYMENT_DATASETS,
)
from eds.domains.retail.generators.commerce.payments import (
    PaymentData as PaymentData,
)
from eds.domains.retail.generators.commerce.payments import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.generators.commerce.payments import (
    apply_payment_status as apply_payment_status,
)
from eds.domains.retail.generators.commerce.payments import (
    generate_payment_data as generate_payment_data,
)
from eds.domains.retail.generators.commerce.payments import (
    generate_payment_status_history as generate_payment_status_history,
)
from eds.domains.retail.generators.commerce.payments import (
    generate_payments as generate_payments,
)
from eds.domains.retail.generators.commerce.payments import (
    resolve_seed as resolve_seed,
)
