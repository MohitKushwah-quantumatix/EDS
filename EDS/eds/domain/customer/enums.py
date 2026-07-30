"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.customer.enums`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.customer.enums import (
    AcquisitionChannel as AcquisitionChannel,
)
from eds.domains.retail.domain.customer.enums import (
    AddressType as AddressType,
)
from eds.domains.retail.domain.customer.enums import (
    CustomerSegment as CustomerSegment,
)
from eds.domains.retail.domain.customer.enums import (
    CustomerStatus as CustomerStatus,
)
from eds.domains.retail.domain.customer.enums import (
    Gender as Gender,
)
from eds.domains.retail.domain.customer.enums import (
    LifecycleStage as LifecycleStage,
)
from eds.domains.retail.domain.customer.enums import (
    LoyaltyStatus as LoyaltyStatus,
)
from eds.domains.retail.domain.customer.enums import (
    LoyaltyTier as LoyaltyTier,
)
from eds.domains.retail.domain.customer.enums import (
    RegistrationSource as RegistrationSource,
)
