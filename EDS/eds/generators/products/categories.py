"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.products.categories`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.products.categories import (
    CATEGORIES as CATEGORIES,
)
from eds.domains.retail.generators.products.categories import (
    ROOT_CATEGORY_NAMES as ROOT_CATEGORY_NAMES,
)
from eds.domains.retail.generators.products.categories import (
    MasterDataConfig as MasterDataConfig,
)
from eds.domains.retail.generators.products.categories import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.products.categories import (
    format_code as format_code,
)
from eds.domains.retail.generators.products.categories import (
    generate_categories as generate_categories,
)
from eds.domains.retail.generators.products.categories import (
    leaf_category_roots as leaf_category_roots,
)
