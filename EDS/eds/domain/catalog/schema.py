"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.catalog.schema`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.catalog.schema import (
    BRANDS as BRANDS,
)
from eds.domains.retail.domain.catalog.schema import (
    CATALOG_DATASETS as CATALOG_DATASETS,
)
from eds.domains.retail.domain.catalog.schema import (
    CATEGORIES as CATEGORIES,
)
from eds.domains.retail.domain.catalog.schema import (
    PRODUCTS as PRODUCTS,
)
from eds.domains.retail.domain.catalog.schema import (
    Dataset as Dataset,
)
from eds.domains.retail.domain.catalog.schema import (
    ForeignKey as ForeignKey,
)
