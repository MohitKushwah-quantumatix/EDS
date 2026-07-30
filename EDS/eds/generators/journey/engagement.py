"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.journey.engagement`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.journey.engagement import (
    ENGAGEMENT_DATASETS as ENGAGEMENT_DATASETS,
)
from eds.domains.retail.generators.journey.engagement import (
    REQUIRED_ENGAGEMENT_DATASETS as REQUIRED_ENGAGEMENT_DATASETS,
)
from eds.domains.retail.generators.journey.engagement import (
    EngagementData as EngagementData,
)
from eds.domains.retail.generators.journey.engagement import (
    ProductCatalog as ProductCatalog,
)
from eds.domains.retail.generators.journey.engagement import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.generators.journey.engagement import (
    generate_engagement_data as generate_engagement_data,
)
from eds.domains.retail.generators.journey.engagement import (
    generate_product_views as generate_product_views,
)
from eds.domains.retail.generators.journey.engagement import (
    generate_wishlists as generate_wishlists,
)
from eds.domains.retail.generators.journey.engagement import (
    resolve_seed as resolve_seed,
)
