"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.customers.customer_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.customers.customer_generator import (
    CUSTOMERS as CUSTOMERS,
)
from eds.domains.retail.generators.customers.customer_generator import (
    AcquisitionChannel as AcquisitionChannel,
)
from eds.domains.retail.generators.customers.customer_generator import (
    CustomerConfig as CustomerConfig,
)
from eds.domains.retail.generators.customers.customer_generator import (
    CustomerGeography as CustomerGeography,
)
from eds.domains.retail.generators.customers.customer_generator import (
    CustomerSegment as CustomerSegment,
)
from eds.domains.retail.generators.customers.customer_generator import (
    CustomerStatus as CustomerStatus,
)
from eds.domains.retail.generators.customers.customer_generator import (
    Gender as Gender,
)
from eds.domains.retail.generators.customers.customer_generator import (
    LifecycleStage as LifecycleStage,
)
from eds.domains.retail.generators.customers.customer_generator import (
    RegistrationSource as RegistrationSource,
)
from eds.domains.retail.generators.customers.customer_generator import (
    assign_home_cities as assign_home_cities,
)
from eds.domains.retail.generators.customers.customer_generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.customers.customer_generator import (
    customer_id_batches as customer_id_batches,
)
from eds.domains.retail.generators.customers.customer_generator import (
    format_code as format_code,
)
from eds.domains.retail.generators.customers.customer_generator import (
    generate_customers as generate_customers,
)
from eds.domains.retail.generators.customers.customer_generator import (
    iter_customer_batches as iter_customer_batches,
)
from eds.domains.retail.generators.customers.customer_generator import (
    make_faker as make_faker,
)
from eds.domains.retail.generators.customers.customer_generator import (
    make_rng as make_rng,
)
