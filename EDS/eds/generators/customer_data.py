"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.customer_data`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.customer_data import (
    CUSTOMER_DATASETS as CUSTOMER_DATASETS,
)
from eds.domains.retail.generators.customer_data import (
    REQUIRED_MASTER_DATASETS as REQUIRED_MASTER_DATASETS,
)
from eds.domains.retail.generators.customer_data import (
    CustomerData as CustomerData,
)
from eds.domains.retail.generators.customer_data import (
    CustomerGeography as CustomerGeography,
)
from eds.domains.retail.generators.customer_data import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.generators.customer_data import (
    generate_addresses as generate_addresses,
)
from eds.domains.retail.generators.customer_data import (
    generate_customer_data as generate_customer_data,
)
from eds.domains.retail.generators.customer_data import (
    generate_customers as generate_customers,
)
from eds.domains.retail.generators.customer_data import (
    generate_loyalty as generate_loyalty,
)
from eds.domains.retail.generators.customer_data import (
    generate_preferences as generate_preferences,
)
from eds.domains.retail.generators.customer_data import (
    resolve_seed as resolve_seed,
)
