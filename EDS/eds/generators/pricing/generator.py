"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.generators.pricing.generator`
instead.
"""

from __future__ import annotations

from eds.domains.retail.generators.pricing.generator import (
    PriceBand as PriceBand,
)
from eds.domains.retail.generators.pricing.generator import (
    PricePoint as PricePoint,
)
from eds.domains.retail.generators.pricing.generator import (
    generate_price_point as generate_price_point,
)
from eds.domains.retail.generators.pricing.generator import (
    price_band_for as price_band_for,
)
