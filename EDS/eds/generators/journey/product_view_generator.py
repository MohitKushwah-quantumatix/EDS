"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.journey.product_view_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.journey.product_view_generator import (
    PERSONA_ENGAGEMENT_PROFILES as PERSONA_ENGAGEMENT_PROFILES,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    POPULARITY_TIERS as POPULARITY_TIERS,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    PRODUCT_VIEWS as PRODUCT_VIEWS,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    EngagementConfig as EngagementConfig,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    PersonaEngagementProfile as PersonaEngagementProfile,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    PersonaName as PersonaName,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    ProductCatalog as ProductCatalog,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    ViewSource as ViewSource,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    generate_product_views as generate_product_views,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    iter_product_view_batches as iter_product_view_batches,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    persona_engagement_profile as persona_engagement_profile,
)
from eds.domains.retail.generators.journey.product_view_generator import (
    stream_seed as stream_seed,
)
