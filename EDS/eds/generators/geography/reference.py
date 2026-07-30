"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.geography.reference`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.geography.reference import (
    COUNTRY_REFERENCE as COUNTRY_REFERENCE,
)
from eds.domains.retail.generators.geography.reference import (
    CountryReference as CountryReference,
)
from eds.domains.retail.generators.geography.reference import (
    StateReference as StateReference,
)
from eds.domains.retail.generators.geography.reference import (
    country_by_code as country_by_code,
)
from eds.domains.retail.generators.geography.reference import (
    supported_countries as supported_countries,
)
