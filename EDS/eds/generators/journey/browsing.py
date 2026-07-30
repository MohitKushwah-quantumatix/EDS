"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.journey.browsing`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.journey.browsing import (
    BROWSING_DATASETS as BROWSING_DATASETS,
)
from eds.domains.retail.generators.journey.browsing import (
    REQUIRED_BROWSING_DATASETS as REQUIRED_BROWSING_DATASETS,
)
from eds.domains.retail.generators.journey.browsing import (
    BrowsingData as BrowsingData,
)
from eds.domains.retail.generators.journey.browsing import (
    CategoryCatalog as CategoryCatalog,
)
from eds.domains.retail.generators.journey.browsing import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.generators.journey.browsing import (
    generate_browsing_data as generate_browsing_data,
)
from eds.domains.retail.generators.journey.browsing import (
    generate_category_views as generate_category_views,
)
from eds.domains.retail.generators.journey.browsing import (
    generate_searches as generate_searches,
)
from eds.domains.retail.generators.journey.browsing import (
    resolve_seed as resolve_seed,
)
