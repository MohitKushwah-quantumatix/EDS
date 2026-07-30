"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.validation.referential`
instead.
"""

from __future__ import annotations

from eds.domains.retail.validation.referential import (
    MASTER_DATA_DATASETS as MASTER_DATA_DATASETS,
)
from eds.domains.retail.validation.referential import (
    Dataset as Dataset,
)
from eds.domains.retail.validation.referential import (
    ValidationIssue as ValidationIssue,
)
from eds.domains.retail.validation.referential import (
    validate_foreign_keys as validate_foreign_keys,
)
from eds.domains.retail.validation.referential import (
    validate_primary_key as validate_primary_key,
)
from eds.domains.retail.validation.referential import (
    validate_referential_integrity as validate_referential_integrity,
)
from eds.domains.retail.validation.referential import (
    validate_schema as validate_schema,
)
