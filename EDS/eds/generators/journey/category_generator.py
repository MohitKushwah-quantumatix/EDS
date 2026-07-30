"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.journey.category_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.journey.category_generator import (
    CATEGORY_VIEWS as CATEGORY_VIEWS,
)
from eds.domains.retail.generators.journey.category_generator import (
    PERSONA_VIEW_PROFILES as PERSONA_VIEW_PROFILES,
)
from eds.domains.retail.generators.journey.category_generator import (
    BrowsingConfig as BrowsingConfig,
)
from eds.domains.retail.generators.journey.category_generator import (
    CategoryCatalog as CategoryCatalog,
)
from eds.domains.retail.generators.journey.category_generator import (
    EntryMethod as EntryMethod,
)
from eds.domains.retail.generators.journey.category_generator import (
    LandingPage as LandingPage,
)
from eds.domains.retail.generators.journey.category_generator import (
    PersonaName as PersonaName,
)
from eds.domains.retail.generators.journey.category_generator import (
    PersonaViewProfile as PersonaViewProfile,
)
from eds.domains.retail.generators.journey.category_generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.journey.category_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.journey.category_generator import (
    generate_category_views as generate_category_views,
)
from eds.domains.retail.generators.journey.category_generator import (
    iter_category_view_batches as iter_category_view_batches,
)
from eds.domains.retail.generators.journey.category_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.journey.category_generator import (
    persona_view_profile as persona_view_profile,
)
