"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.journey.enums`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.journey.enums import (
    Browser as Browser,
)
from eds.domains.retail.domain.journey.enums import (
    DeviceType as DeviceType,
)
from eds.domains.retail.domain.journey.enums import (
    EntryMethod as EntryMethod,
)
from eds.domains.retail.domain.journey.enums import (
    ExitPage as ExitPage,
)
from eds.domains.retail.domain.journey.enums import (
    LandingPage as LandingPage,
)
from eds.domains.retail.domain.journey.enums import (
    OperatingSystem as OperatingSystem,
)
from eds.domains.retail.domain.journey.enums import (
    PersonaName as PersonaName,
)
from eds.domains.retail.domain.journey.enums import (
    TrafficSource as TrafficSource,
)
from eds.domains.retail.domain.journey.enums import (
    ViewSource as ViewSource,
)
