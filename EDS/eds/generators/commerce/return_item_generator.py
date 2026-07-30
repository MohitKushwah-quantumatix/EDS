"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.return_item_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.return_item_generator import (
    RETURN_ITEMS as RETURN_ITEMS,
)
from eds.domains.retail.generators.commerce.return_item_generator import (
    ReturnConfig as ReturnConfig,
)
from eds.domains.retail.generators.commerce.return_item_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.return_item_generator import (
    generate_return_items as generate_return_items,
)
from eds.domains.retail.generators.commerce.return_item_generator import (
    iter_return_item_batches as iter_return_item_batches,
)
from eds.domains.retail.generators.commerce.return_item_generator import (
    make_rng as make_rng,
)
