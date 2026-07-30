"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.journey.persona_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.journey.persona_generator import (
    CUSTOMER_PERSONAS as CUSTOMER_PERSONAS,
)
from eds.domains.retail.generators.journey.persona_generator import (
    PERSONA_PROFILES as PERSONA_PROFILES,
)
from eds.domains.retail.generators.journey.persona_generator import (
    CustomerConfig as CustomerConfig,
)
from eds.domains.retail.generators.journey.persona_generator import (
    JourneyConfig as JourneyConfig,
)
from eds.domains.retail.generators.journey.persona_generator import (
    PersonaName as PersonaName,
)
from eds.domains.retail.generators.journey.persona_generator import (
    PersonaProfile as PersonaProfile,
)
from eds.domains.retail.generators.journey.persona_generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.journey.persona_generator import (
    generate_personas as generate_personas,
)
from eds.domains.retail.generators.journey.persona_generator import (
    iter_persona_batches as iter_persona_batches,
)
from eds.domains.retail.generators.journey.persona_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.journey.persona_generator import (
    persona_profile as persona_profile,
)
