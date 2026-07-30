"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.return_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.return_generator import (
    RETURN_NUMBER_SEQUENCE_WIDTH as RETURN_NUMBER_SEQUENCE_WIDTH,
)
from eds.domains.retail.generators.commerce.return_generator import (
    RETURNS as RETURNS,
)
from eds.domains.retail.generators.commerce.return_generator import (
    ReturnConfig as ReturnConfig,
)
from eds.domains.retail.generators.commerce.return_generator import (
    ReturnStatus as ReturnStatus,
)
from eds.domains.retail.generators.commerce.return_generator import (
    ShipmentStatus as ShipmentStatus,
)
from eds.domains.retail.generators.commerce.return_generator import (
    apply_status_and_timeline as apply_status_and_timeline,
)
from eds.domains.retail.generators.commerce.return_generator import (
    eligible_shipments as eligible_shipments,
)
from eds.domains.retail.generators.commerce.return_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.return_generator import (
    generate_returns as generate_returns,
)
from eds.domains.retail.generators.commerce.return_generator import (
    iter_return_batches as iter_return_batches,
)
from eds.domains.retail.generators.commerce.return_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.commerce.return_generator import (
    return_number_expression as return_number_expression,
)
