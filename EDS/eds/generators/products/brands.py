"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.products.brands`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.products.brands import (
    BRANDS as BRANDS,
)
from eds.domains.retail.generators.products.brands import (
    MasterDataConfig as MasterDataConfig,
)
from eds.domains.retail.generators.products.brands import (
    build_frame as build_frame,
)
from eds.domains.retail.generators.products.brands import (
    format_code as format_code,
)
from eds.domains.retail.generators.products.brands import (
    generate_brands as generate_brands,
)
from eds.domains.retail.generators.products.brands import (
    make_faker as make_faker,
)
from eds.domains.retail.generators.products.brands import (
    make_rng as make_rng,
)
