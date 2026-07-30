"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.core.random_streams`
instead.
"""

from __future__ import annotations

from eds.core.random_streams import (
    make_faker as make_faker,
)
from eds.core.random_streams import (
    make_rng as make_rng,
)
from eds.core.random_streams import (
    resolve_seed as resolve_seed,
)
from eds.core.random_streams import (
    stream_seed as stream_seed,
)
