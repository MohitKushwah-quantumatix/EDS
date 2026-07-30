"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.browsing_validation`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.browsing_validation import (
    BROWSING_DATASETS as BROWSING_DATASETS,
)
from eds.domains.retail.validation.browsing_validation import (
    ValidationError as ValidationError,
)
from eds.domains.retail.validation.browsing_validation import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.browsing_validation import (
    assert_valid_browsing_data as assert_valid_browsing_data,
)
from eds.domains.retail.validation.browsing_validation import (
    validate_browsing_data as validate_browsing_data,
)
from eds.domains.retail.validation.browsing_validation import (
    validate_category_view_timeline as validate_category_view_timeline,
)
from eds.domains.retail.validation.browsing_validation import (
    validate_referential_integrity as validate_referential_integrity,
)
from eds.domains.retail.validation.browsing_validation import (
    validate_search_category_consistency as validate_search_category_consistency,
)
from eds.domains.retail.validation.browsing_validation import (
    validate_search_results as validate_search_results,
)
from eds.domains.retail.validation.browsing_validation import (
    validate_search_timeline as validate_search_timeline,
)
from eds.domains.retail.validation.browsing_validation import (
    validate_sequences as validate_sequences,
)
from eds.domains.retail.validation.browsing_validation import (
    validate_view_durations as validate_view_durations,
)
