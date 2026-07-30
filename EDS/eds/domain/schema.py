"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.core.schema`
instead.
"""

from __future__ import annotations

from eds.core.schema import (
    Dataset as Dataset,
)
from eds.core.schema import (
    ForeignKey as ForeignKey,
)
