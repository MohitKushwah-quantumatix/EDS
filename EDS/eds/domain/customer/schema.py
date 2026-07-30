"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.customer.schema`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.customer.schema import (
    CUSTOMER_ADDRESSES as CUSTOMER_ADDRESSES,
)
from eds.domains.retail.domain.customer.schema import (
    CUSTOMER_DATASETS as CUSTOMER_DATASETS,
)
from eds.domains.retail.domain.customer.schema import (
    CUSTOMER_LOYALTY as CUSTOMER_LOYALTY,
)
from eds.domains.retail.domain.customer.schema import (
    CUSTOMER_PREFERENCES as CUSTOMER_PREFERENCES,
)
from eds.domains.retail.domain.customer.schema import (
    CUSTOMERS as CUSTOMERS,
)
from eds.domains.retail.domain.customer.schema import (
    Dataset as Dataset,
)
from eds.domains.retail.domain.customer.schema import (
    ForeignKey as ForeignKey,
)
from eds.domains.retail.domain.customer.schema import (
    customer_dataset_by_name as customer_dataset_by_name,
)
from eds.domains.retail.domain.customer.schema import (
    customer_dataset_names as customer_dataset_names,
)
