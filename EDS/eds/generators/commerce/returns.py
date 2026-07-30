"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.returns`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.returns import (
    REQUIRED_RETURN_DATASETS as REQUIRED_RETURN_DATASETS,
)
from eds.domains.retail.generators.commerce.returns import (
    RETURN_DATASETS as RETURN_DATASETS,
)
from eds.domains.retail.generators.commerce.returns import (
    ReturnData as ReturnData,
)
from eds.domains.retail.generators.commerce.returns import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.generators.commerce.returns import (
    apply_status_and_timeline as apply_status_and_timeline,
)
from eds.domains.retail.generators.commerce.returns import (
    generate_return_data as generate_return_data,
)
from eds.domains.retail.generators.commerce.returns import (
    generate_return_items as generate_return_items,
)
from eds.domains.retail.generators.commerce.returns import (
    generate_return_status_history as generate_return_status_history,
)
from eds.domains.retail.generators.commerce.returns import (
    generate_returns as generate_returns,
)
from eds.domains.retail.generators.commerce.returns import (
    resolve_seed as resolve_seed,
)
