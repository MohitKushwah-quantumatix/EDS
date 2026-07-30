"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.customers.preference_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.customers.preference_generator import (
    CUSTOMER_PREFERENCES as CUSTOMER_PREFERENCES,
)
from eds.domains.retail.generators.customers.preference_generator import (
    CustomerConfig as CustomerConfig,
)
from eds.domains.retail.generators.customers.preference_generator import (
    CustomerGeography as CustomerGeography,
)
from eds.domains.retail.generators.customers.preference_generator import (
    assign_home_cities as assign_home_cities,
)
from eds.domains.retail.generators.customers.preference_generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.customers.preference_generator import (
    customer_id_batches as customer_id_batches,
)
from eds.domains.retail.generators.customers.preference_generator import (
    generate_preferences as generate_preferences,
)
from eds.domains.retail.generators.customers.preference_generator import (
    iter_preference_batches as iter_preference_batches,
)
from eds.domains.retail.generators.customers.preference_generator import (
    make_rng as make_rng,
)
