"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.review_generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.review_generator import (
    REVIEW_NUMBER_SEQUENCE_WIDTH as REVIEW_NUMBER_SEQUENCE_WIDTH,
)
from eds.domains.retail.generators.commerce.review_generator import (
    REVIEWS as REVIEWS,
)
from eds.domains.retail.generators.commerce.review_generator import (
    ReviewConfig as ReviewConfig,
)
from eds.domains.retail.generators.commerce.review_generator import (
    ShipmentStatus as ShipmentStatus,
)
from eds.domains.retail.generators.commerce.review_generator import (
    eligible_items as eligible_items,
)
from eds.domains.retail.generators.commerce.review_generator import (
    empty_frame as empty_frame,
)
from eds.domains.retail.generators.commerce.review_generator import (
    generate_reviews as generate_reviews,
)
from eds.domains.retail.generators.commerce.review_generator import (
    iter_review_batches as iter_review_batches,
)
from eds.domains.retail.generators.commerce.review_generator import (
    make_rng as make_rng,
)
from eds.domains.retail.generators.commerce.review_generator import (
    review_number_expression as review_number_expression,
)
