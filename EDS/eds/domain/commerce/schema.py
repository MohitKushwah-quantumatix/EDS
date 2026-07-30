"""Backward-compatible alias.

Pre-platform import path, kept working unchanged (PADR-005).
New code should import from :mod:`eds.domains.retail.domain.commerce.schema`
instead.
"""

from __future__ import annotations

from eds.domains.retail.domain.commerce.schema import (
    CART_ITEMS as CART_ITEMS,
)
from eds.domains.retail.domain.commerce.schema import (
    CHECKOUT as CHECKOUT,
)
from eds.domains.retail.domain.commerce.schema import (
    CHECKOUT_DATASETS as CHECKOUT_DATASETS,
)
from eds.domains.retail.domain.commerce.schema import (
    COMMERCE_DATASETS as COMMERCE_DATASETS,
)
from eds.domains.retail.domain.commerce.schema import (
    ORDER_DATASETS as ORDER_DATASETS,
)
from eds.domains.retail.domain.commerce.schema import (
    ORDER_LINES as ORDER_LINES,
)
from eds.domains.retail.domain.commerce.schema import (
    ORDER_STATUS_HISTORY as ORDER_STATUS_HISTORY,
)
from eds.domains.retail.domain.commerce.schema import (
    ORDERS as ORDERS,
)
from eds.domains.retail.domain.commerce.schema import (
    PAYMENT_DATASETS as PAYMENT_DATASETS,
)
from eds.domains.retail.domain.commerce.schema import (
    PAYMENT_STATUS_HISTORY as PAYMENT_STATUS_HISTORY,
)
from eds.domains.retail.domain.commerce.schema import (
    PAYMENTS as PAYMENTS,
)
from eds.domains.retail.domain.commerce.schema import (
    RETURN_DATASETS as RETURN_DATASETS,
)
from eds.domains.retail.domain.commerce.schema import (
    RETURN_ITEMS as RETURN_ITEMS,
)
from eds.domains.retail.domain.commerce.schema import (
    RETURN_STATUS_HISTORY as RETURN_STATUS_HISTORY,
)
from eds.domains.retail.domain.commerce.schema import (
    RETURNS as RETURNS,
)
from eds.domains.retail.domain.commerce.schema import (
    REVIEW_DATASETS as REVIEW_DATASETS,
)
from eds.domains.retail.domain.commerce.schema import (
    REVIEWS as REVIEWS,
)
from eds.domains.retail.domain.commerce.schema import (
    SHIPMENT_DATASETS as SHIPMENT_DATASETS,
)
from eds.domains.retail.domain.commerce.schema import (
    SHIPMENT_ITEMS as SHIPMENT_ITEMS,
)
from eds.domains.retail.domain.commerce.schema import (
    SHIPMENT_STATUS_HISTORY as SHIPMENT_STATUS_HISTORY,
)
from eds.domains.retail.domain.commerce.schema import (
    SHIPMENTS as SHIPMENTS,
)
from eds.domains.retail.domain.commerce.schema import (
    SHOPPING_CARTS as SHOPPING_CARTS,
)
from eds.domains.retail.domain.commerce.schema import (
    Dataset as Dataset,
)
from eds.domains.retail.domain.commerce.schema import (
    ForeignKey as ForeignKey,
)
from eds.domains.retail.domain.commerce.schema import (
    checkout_dataset_by_name as checkout_dataset_by_name,
)
from eds.domains.retail.domain.commerce.schema import (
    checkout_dataset_names as checkout_dataset_names,
)
from eds.domains.retail.domain.commerce.schema import (
    commerce_dataset_by_name as commerce_dataset_by_name,
)
from eds.domains.retail.domain.commerce.schema import (
    commerce_dataset_names as commerce_dataset_names,
)
from eds.domains.retail.domain.commerce.schema import (
    order_dataset_by_name as order_dataset_by_name,
)
from eds.domains.retail.domain.commerce.schema import (
    order_dataset_names as order_dataset_names,
)
from eds.domains.retail.domain.commerce.schema import (
    payment_dataset_by_name as payment_dataset_by_name,
)
from eds.domains.retail.domain.commerce.schema import (
    payment_dataset_names as payment_dataset_names,
)
from eds.domains.retail.domain.commerce.schema import (
    return_dataset_by_name as return_dataset_by_name,
)
from eds.domains.retail.domain.commerce.schema import (
    return_dataset_names as return_dataset_names,
)
from eds.domains.retail.domain.commerce.schema import (
    review_dataset_by_name as review_dataset_by_name,
)
from eds.domains.retail.domain.commerce.schema import (
    review_dataset_names as review_dataset_names,
)
from eds.domains.retail.domain.commerce.schema import (
    shipment_dataset_by_name as shipment_dataset_by_name,
)
from eds.domains.retail.domain.commerce.schema import (
    shipment_dataset_names as shipment_dataset_names,
)
