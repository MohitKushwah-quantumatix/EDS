"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.geography.schema`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.geography.schema import (
    CITIES as CITIES,
)
from eds.domains.retail.domain.geography.schema import (
    COUNTRIES as COUNTRIES,
)
from eds.domains.retail.domain.geography.schema import (
    GEOGRAPHY_DATASETS as GEOGRAPHY_DATASETS,
)
from eds.domains.retail.domain.geography.schema import (
    STATES as STATES,
)
from eds.domains.retail.domain.geography.schema import (
    Dataset as Dataset,
)
from eds.domains.retail.domain.geography.schema import (
    ForeignKey as ForeignKey,
)
