"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.core.validation.issues`
instead.
"""

from __future__ import annotations

from eds.core.validation.issues import (
    ValidationError as ValidationError,
)
from eds.core.validation.issues import (
    ValidationIssue as ValidationIssue,
)
from eds.core.validation.issues import (
    format_issues as format_issues,
)
