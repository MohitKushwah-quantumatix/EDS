"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.journey.journey`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.journey.journey import (
    JOURNEY_DATASETS as JOURNEY_DATASETS,
)
from eds.domains.retail.generators.journey.journey import (
    REQUIRED_UPSTREAM_DATASETS as REQUIRED_UPSTREAM_DATASETS,
)
from eds.domains.retail.generators.journey.journey import (
    JourneyData as JourneyData,
)
from eds.domains.retail.generators.journey.journey import (
    SessionLocations as SessionLocations,
)
from eds.domains.retail.generators.journey.journey import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.generators.journey.journey import (
    generate_journey_data as generate_journey_data,
)
from eds.domains.retail.generators.journey.journey import (
    generate_personas as generate_personas,
)
from eds.domains.retail.generators.journey.journey import (
    generate_sessions as generate_sessions,
)
from eds.domains.retail.generators.journey.journey import (
    resolve_seed as resolve_seed,
)
