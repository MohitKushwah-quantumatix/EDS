"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.return_status_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.return_status_generator import (
    RETURN_LIFECYCLE as RETURN_LIFECYCLE,
)
from eds.domains.retail.generators.commerce.return_status_generator import (
    RETURN_STATUS_HISTORY as RETURN_STATUS_HISTORY,
)
from eds.domains.retail.generators.commerce.return_status_generator import (
    ReturnConfig as ReturnConfig,
)
from eds.domains.retail.generators.commerce.return_status_generator import (
    ReturnStatus as ReturnStatus,
)
from eds.domains.retail.generators.commerce.return_status_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.return_status_generator import (
    generate_return_status_history as generate_return_status_history,
)
from eds.domains.retail.generators.commerce.return_status_generator import (
    iter_return_status_batches as iter_return_status_batches,
)
from eds.domains.retail.generators.commerce.return_status_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.commerce.return_status_generator import (
    return_lifecycle_position as return_lifecycle_position,
)
