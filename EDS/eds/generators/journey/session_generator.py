"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.journey.session_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.journey.session_generator import (
    SESSIONS as SESSIONS,
)
from eds.domains.retail.generators.journey.session_generator import (
    Browser as Browser,
)
from eds.domains.retail.generators.journey.session_generator import (
    CustomerConfig as CustomerConfig,
)
from eds.domains.retail.generators.journey.session_generator import (
    DeviceType as DeviceType,
)
from eds.domains.retail.generators.journey.session_generator import (
    ExitPage as ExitPage,
)
from eds.domains.retail.generators.journey.session_generator import (
    JourneyConfig as JourneyConfig,
)
from eds.domains.retail.generators.journey.session_generator import (
    LandingPage as LandingPage,
)
from eds.domains.retail.generators.journey.session_generator import (
    OperatingSystem as OperatingSystem,
)
from eds.domains.retail.generators.journey.session_generator import (
    PersonaName as PersonaName,
)
from eds.domains.retail.generators.journey.session_generator import (
    SessionLocations as SessionLocations,
)
from eds.domains.retail.generators.journey.session_generator import (
    TrafficSource as TrafficSource,
)
from eds.domains.retail.generators.journey.session_generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.journey.session_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.journey.session_generator import (
    generate_sessions as generate_sessions,
)
from eds.domains.retail.generators.journey.session_generator import (
    iter_session_batches as iter_session_batches,
)
from eds.domains.retail.generators.journey.session_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.journey.session_generator import (
    persona_profile as persona_profile,
)
