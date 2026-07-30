"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.customers.address_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.customers.address_generator import (
    CUSTOMER_ADDRESSES as CUSTOMER_ADDRESSES,
)
from eds.domains.retail.generators.customers.address_generator import (
    AddressType as AddressType,
)
from eds.domains.retail.generators.customers.address_generator import (
    CustomerConfig as CustomerConfig,
)
from eds.domains.retail.generators.customers.address_generator import (
    CustomerGeography as CustomerGeography,
)
from eds.domains.retail.generators.customers.address_generator import (
    assign_home_cities as assign_home_cities,
)
from eds.domains.retail.generators.customers.address_generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.customers.address_generator import (
    customer_id_batches as customer_id_batches,
)
from eds.domains.retail.generators.customers.address_generator import (
    generate_addresses as generate_addresses,
)
from eds.domains.retail.generators.customers.address_generator import (
    iter_address_batches as iter_address_batches,
)
from eds.domains.retail.generators.customers.address_generator import (
    make_faker as make_faker,
)
from eds.domains.retail.generators.customers.address_generator import (
    make_rng as make_rng,
)
