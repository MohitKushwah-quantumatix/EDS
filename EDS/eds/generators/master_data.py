"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.master_data`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.master_data import (
    MASTER_DATA_DATASETS as MASTER_DATA_DATASETS,
)
from eds.domains.retail.generators.master_data import (
    MasterData as MasterData,
)
from eds.domains.retail.generators.master_data import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.generators.master_data import (
    country_by_code as country_by_code,
)
from eds.domains.retail.generators.master_data import (
    generate_brands as generate_brands,
)
from eds.domains.retail.generators.master_data import (
    generate_categories as generate_categories,
)
from eds.domains.retail.generators.master_data import (
    generate_cities as generate_cities,
)
from eds.domains.retail.generators.master_data import (
    generate_countries as generate_countries,
)
from eds.domains.retail.generators.master_data import (
    generate_coupon_types as generate_coupon_types,
)
from eds.domains.retail.generators.master_data import (
    generate_inventory as generate_inventory,
)
from eds.domains.retail.generators.master_data import (
    generate_master_data as generate_master_data,
)
from eds.domains.retail.generators.master_data import (
    generate_payment_methods as generate_payment_methods,
)
from eds.domains.retail.generators.master_data import (
    generate_products as generate_products,
)
from eds.domains.retail.generators.master_data import (
    generate_return_reasons as generate_return_reasons,
)
from eds.domains.retail.generators.master_data import (
    generate_shipping_methods as generate_shipping_methods,
)
from eds.domains.retail.generators.master_data import (
    generate_states as generate_states,
)
from eds.domains.retail.generators.master_data import (
    generate_suppliers as generate_suppliers,
)
from eds.domains.retail.generators.master_data import (
    generate_tax_codes as generate_tax_codes,
)
from eds.domains.retail.generators.master_data import (
    generate_warehouses as generate_warehouses,
)
from eds.domains.retail.generators.master_data import (
    resolve_seed as resolve_seed,
)
