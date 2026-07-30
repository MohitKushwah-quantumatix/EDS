"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.journey.schema`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.journey.schema import (
    BROWSING_DATASETS as BROWSING_DATASETS,
)
from eds.domains.retail.domain.journey.schema import (
    CATEGORY_VIEWS as CATEGORY_VIEWS,
)
from eds.domains.retail.domain.journey.schema import (
    CUSTOMER_PERSONAS as CUSTOMER_PERSONAS,
)
from eds.domains.retail.domain.journey.schema import (
    ENGAGEMENT_DATASETS as ENGAGEMENT_DATASETS,
)
from eds.domains.retail.domain.journey.schema import (
    JOURNEY_DATASETS as JOURNEY_DATASETS,
)
from eds.domains.retail.domain.journey.schema import (
    PRODUCT_VIEWS as PRODUCT_VIEWS,
)
from eds.domains.retail.domain.journey.schema import (
    SEARCH_HISTORY as SEARCH_HISTORY,
)
from eds.domains.retail.domain.journey.schema import (
    SESSIONS as SESSIONS,
)
from eds.domains.retail.domain.journey.schema import (
    WISHLISTS as WISHLISTS,
)
from eds.domains.retail.domain.journey.schema import (
    Dataset as Dataset,
)
from eds.domains.retail.domain.journey.schema import (
    ForeignKey as ForeignKey,
)
from eds.domains.retail.domain.journey.schema import (
    browsing_dataset_by_name as browsing_dataset_by_name,
)
from eds.domains.retail.domain.journey.schema import (
    browsing_dataset_names as browsing_dataset_names,
)
from eds.domains.retail.domain.journey.schema import (
    engagement_dataset_by_name as engagement_dataset_by_name,
)
from eds.domains.retail.domain.journey.schema import (
    engagement_dataset_names as engagement_dataset_names,
)
from eds.domains.retail.domain.journey.schema import (
    journey_dataset_by_name as journey_dataset_by_name,
)
from eds.domains.retail.domain.journey.schema import (
    journey_dataset_names as journey_dataset_names,
)
