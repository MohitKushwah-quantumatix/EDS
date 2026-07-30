"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.geography.generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.geography.generator import (
    CITIES as CITIES,
)
from eds.domains.retail.generators.geography.generator import (
    COUNTRIES as COUNTRIES,
)
from eds.domains.retail.generators.geography.generator import (
    STATES as STATES,
)
from eds.domains.retail.generators.geography.generator import (
    CountryReference as CountryReference,
)
from eds.domains.retail.generators.geography.generator import (
    MasterDataConfig as MasterDataConfig,
)
from eds.domains.retail.generators.geography.generator import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.geography.generator import (
    country_by_code as country_by_code,
)
from eds.domains.retail.generators.geography.generator import (
    generate_cities as generate_cities,
)
from eds.domains.retail.generators.geography.generator import (
    generate_countries as generate_countries,
)
from eds.domains.retail.generators.geography.generator import (
    generate_states as generate_states,
)
from eds.domains.retail.generators.geography.generator import (
    make_faker as make_faker,
)
from eds.domains.retail.generators.geography.generator import (
    make_rng as make_rng,
)
