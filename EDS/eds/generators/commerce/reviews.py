"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.commerce.reviews`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.commerce.reviews import (
    REQUIRED_REVIEW_DATASETS as REQUIRED_REVIEW_DATASETS,
)
from eds.domains.retail.generators.commerce.reviews import (
    REVIEW_DATASETS as REVIEW_DATASETS,
)
from eds.domains.retail.generators.commerce.reviews import (
    ReviewData as ReviewData,
)
from eds.domains.retail.generators.commerce.reviews import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.generators.commerce.reviews import (
    generate_review_data as generate_review_data,
)
from eds.domains.retail.generators.commerce.reviews import (
    generate_reviews as generate_reviews,
)
from eds.domains.retail.generators.commerce.reviews import (
    resolve_seed as resolve_seed,
)
