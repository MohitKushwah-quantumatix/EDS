"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.engagement_validation`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.engagement_validation import (
    ENGAGEMENT_DATASETS as ENGAGEMENT_DATASETS,
)
from eds.domains.retail.validation.engagement_validation import (
    ValidationError as ValidationError,
)
from eds.domains.retail.validation.engagement_validation import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.engagement_validation import (
    assert_valid_engagement_data as assert_valid_engagement_data,
)
from eds.domains.retail.validation.engagement_validation import (
    validate_engagement_data as validate_engagement_data,
)
from eds.domains.retail.validation.engagement_validation import (
    validate_product_category_containment as validate_product_category_containment,
)
from eds.domains.retail.validation.engagement_validation import (
    validate_product_view_sequences as validate_product_view_sequences,
)
from eds.domains.retail.validation.engagement_validation import (
    validate_product_view_timeline as validate_product_view_timeline,
)
from eds.domains.retail.validation.engagement_validation import (
    validate_referential_integrity as validate_referential_integrity,
)
from eds.domains.retail.validation.engagement_validation import (
    validate_search_source as validate_search_source,
)
from eds.domains.retail.validation.engagement_validation import (
    validate_view_durations as validate_view_durations,
)
from eds.domains.retail.validation.engagement_validation import (
    validate_wishlist_origin as validate_wishlist_origin,
)
from eds.domains.retail.validation.engagement_validation import (
    validate_wishlist_timeline as validate_wishlist_timeline,
)
from eds.domains.retail.validation.engagement_validation import (
    validate_wishlist_uniqueness as validate_wishlist_uniqueness,
)
