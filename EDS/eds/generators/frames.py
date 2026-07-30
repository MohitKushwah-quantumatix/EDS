"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.core.frames`
instead.
"""

from __future__ import annotations

from eds.core.frames import (
    Dataset as Dataset,
)
from eds.core.frames import (
    build_frame as build_frame,
)
from eds.core.frames import (
    empty_frame as empty_frame,
)
from eds.core.frames import (
    format_code as format_code,
)
