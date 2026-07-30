"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.journey_validation`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.journey_validation import (
    JOURNEY_DATASETS as JOURNEY_DATASETS,
)
from eds.domains.retail.validation.journey_validation import (
    ValidationError as ValidationError,
)
from eds.domains.retail.validation.journey_validation import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.journey_validation import (
    assert_valid_journey_data as assert_valid_journey_data,
)
from eds.domains.retail.validation.journey_validation import (
    validate_journey_data as validate_journey_data,
)
from eds.domains.retail.validation.journey_validation import (
    validate_persona_coverage as validate_persona_coverage,
)
from eds.domains.retail.validation.journey_validation import (
    validate_persona_fields as validate_persona_fields,
)
from eds.domains.retail.validation.journey_validation import (
    validate_referential_integrity as validate_referential_integrity,
)
from eds.domains.retail.validation.journey_validation import (
    validate_session_fields as validate_session_fields,
)
from eds.domains.retail.validation.journey_validation import (
    validate_session_timeline as validate_session_timeline,
)
