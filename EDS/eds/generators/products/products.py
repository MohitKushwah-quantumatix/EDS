"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.products.products`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.products.products import (
    PRODUCTS as PRODUCTS,
)
from eds.domains.retail.generators.products.products import (
    MasterDataConfig as MasterDataConfig,
)
from eds.domains.retail.generators.products.products import (
    ProductInputs as ProductInputs,
)
from eds.domains.retail.generators.products.products import (
    ProductStatus as ProductStatus,
)
from eds.domains.retail.generators.products.products import (
    UnitOfMeasure as UnitOfMeasure,
)
from eds.domains.retail.generators.products.products import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.products.products import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.products.products import (
    format_code as format_code,
)
from eds.domains.retail.generators.products.products import (
    generate_price_point as generate_price_point,
)
from eds.domains.retail.generators.products.products import (
    generate_products as generate_products,
)
from eds.domains.retail.generators.products.products import (
    iter_product_batches as iter_product_batches,
)
from eds.domains.retail.generators.products.products import (
    leaf_category_roots as leaf_category_roots,
)
from eds.domains.retail.generators.products.products import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.products.products import (
    price_band_for as price_band_for,
)
