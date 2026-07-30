"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.review_validation`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.review_validation import (
    MAX_RATING as MAX_RATING,
)
from eds.domains.retail.validation.review_validation import (
    MIN_RATING as MIN_RATING,
)
from eds.domains.retail.validation.review_validation import (
    REVIEW_DATASETS as REVIEW_DATASETS,
)
from eds.domains.retail.validation.review_validation import (
    REVIEW_NUMBER_PATTERN as REVIEW_NUMBER_PATTERN,
)
from eds.domains.retail.validation.review_validation import (
    ShipmentStatus as ShipmentStatus,
)
from eds.domains.retail.validation.review_validation import (
    ValidationError as ValidationError,
)
from eds.domains.retail.validation.review_validation import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.review_validation import (
    assert_valid_review_data as assert_valid_review_data,
)
from eds.domains.retail.validation.review_validation import (
    validate_referential_integrity as validate_referential_integrity,
)
from eds.domains.retail.validation.review_validation import (
    validate_review_content as validate_review_content,
)
from eds.domains.retail.validation.review_validation import (
    validate_review_data as validate_review_data,
)
from eds.domains.retail.validation.review_validation import (
    validate_review_eligibility as validate_review_eligibility,
)
from eds.domains.retail.validation.review_validation import (
    validate_review_numbers as validate_review_numbers,
)
from eds.domains.retail.validation.review_validation import (
    validate_review_ratings as validate_review_ratings,
)
from eds.domains.retail.validation.review_validation import (
    validate_review_timeline as validate_review_timeline,
)
