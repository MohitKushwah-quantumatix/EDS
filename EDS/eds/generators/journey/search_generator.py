"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.journey.search_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.journey.search_generator import (
    CATEGORY_SEARCH_TERMS as CATEGORY_SEARCH_TERMS,
)
from eds.domains.retail.generators.journey.search_generator import (
    PERSONA_SEARCH_RANGES as PERSONA_SEARCH_RANGES,
)
from eds.domains.retail.generators.journey.search_generator import (
    SEARCH_HISTORY as SEARCH_HISTORY,
)
from eds.domains.retail.generators.journey.search_generator import (
    BrowsingConfig as BrowsingConfig,
)
from eds.domains.retail.generators.journey.search_generator import (
    CategoryCatalog as CategoryCatalog,
)
from eds.domains.retail.generators.journey.search_generator import (
    PersonaName as PersonaName,
)
from eds.domains.retail.generators.journey.search_generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.journey.search_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.journey.search_generator import (
    generate_searches as generate_searches,
)
from eds.domains.retail.generators.journey.search_generator import (
    iter_search_batches as iter_search_batches,
)
from eds.domains.retail.generators.journey.search_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.journey.search_generator import (
    search_terms_for_root as search_terms_for_root,
)
