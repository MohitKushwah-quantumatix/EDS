"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.journey.wishlist_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.journey.wishlist_generator import (
    WISHLISTS as WISHLISTS,
)
from eds.domains.retail.generators.journey.wishlist_generator import (
    EngagementConfig as EngagementConfig,
)
from eds.domains.retail.generators.journey.wishlist_generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.journey.wishlist_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.journey.wishlist_generator import (
    generate_wishlists as generate_wishlists,
)
from eds.domains.retail.generators.journey.wishlist_generator import (
    iter_wishlist_batches as iter_wishlist_batches,
)
from eds.domains.retail.generators.journey.wishlist_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.journey.wishlist_generator import (
    persona_engagement_profile as persona_engagement_profile,
)
