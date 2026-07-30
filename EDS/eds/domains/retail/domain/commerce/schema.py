"""Schemas for the commerce datasets.

A cart item always references the product view the product was seen on, even
when the customer added it from their wishlist - a wishlist entry itself
records the view it was saved from, so the chain back to a real page view is
never broken.
"""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = [
    "CART_ITEMS",
    "CHECKOUT",
    "CHECKOUT_DATASETS",
    "COMMERCE_DATASETS",
    "ORDERS",
    "ORDER_DATASETS",
    "ORDER_LINES",
    "ORDER_STATUS_HISTORY",
    "PAYMENTS",
    "PAYMENT_DATASETS",
    "PAYMENT_STATUS_HISTORY",
    "RETURNS",
    "RETURN_DATASETS",
    "RETURN_ITEMS",
    "RETURN_STATUS_HISTORY",
    "REVIEWS",
    "REVIEW_DATASETS",
    "SHIPMENTS",
    "SHIPMENT_DATASETS",
    "SHIPMENT_ITEMS",
    "SHIPMENT_STATUS_HISTORY",
    "SHOPPING_CARTS",
    "payment_dataset_by_name",
    "payment_dataset_names",
    "return_dataset_by_name",
    "return_dataset_names",
    "review_dataset_by_name",
    "review_dataset_names",
    "shipment_dataset_by_name",
    "shipment_dataset_names",
    "checkout_dataset_by_name",
    "checkout_dataset_names",
    "commerce_dataset_by_name",
    "commerce_dataset_names",
    "order_dataset_by_name",
    "order_dataset_names",
]

SHOPPING_CARTS = Dataset(
    name="shopping_carts",
    columns={
        "cart_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "session_id": pl.Int64(),
        "cart_status": pl.String(),
        "item_count": pl.Int64(),
        "created_at": pl.Datetime("us"),
        "updated_at": pl.Datetime("us"),
    },
    primary_key="cart_id",
    foreign_keys=(
        ForeignKey("customer_id", "customers", "customer_id"),
        ForeignKey("session_id", "sessions", "session_id"),
    ),
    # A session may have zero or one cart.
    unique_columns=("session_id",),
)

CART_ITEMS = Dataset(
    name="cart_items",
    columns={
        "cart_item_id": pl.Int64(),
        "cart_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "product_id": pl.Int64(),
        "product_view_id": pl.Int64(),
        "wishlist_id": pl.Int64(),
        "quantity": pl.Int64(),
        "unit_price": pl.Float64(),
        "added_from": pl.String(),
        "added_at": pl.Datetime("us"),
        "removed_at": pl.Datetime("us"),
    },
    primary_key="cart_item_id",
    foreign_keys=(
        ForeignKey("cart_id", "shopping_carts", "cart_id"),
        ForeignKey("customer_id", "customers", "customer_id"),
        ForeignKey("product_id", "products", "product_id"),
        ForeignKey("product_view_id", "product_views", "product_view_id"),
        # Only populated when the product came from the wishlist.
        ForeignKey("wishlist_id", "wishlists", "wishlist_id", nullable=True),
    ),
)

CHECKOUT = Dataset(
    name="checkout",
    columns={
        "checkout_id": pl.Int64(),
        "cart_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "session_id": pl.Int64(),
        "shipping_address_id": pl.Int64(),
        "billing_address_id": pl.Int64(),
        "shipping_method": pl.String(),
        "payment_method": pl.String(),
        "checkout_status": pl.String(),
        "subtotal": pl.Float64(),
        "shipping_cost": pl.Float64(),
        "tax_amount": pl.Float64(),
        "discount_amount": pl.Float64(),
        "total_amount": pl.Float64(),
        "started_at": pl.Datetime("us"),
        "completed_at": pl.Datetime("us"),
        "created_at": pl.Datetime("us"),
    },
    primary_key="checkout_id",
    foreign_keys=(
        ForeignKey("cart_id", "shopping_carts", "cart_id"),
        ForeignKey("customer_id", "customers", "customer_id"),
        ForeignKey("session_id", "sessions", "session_id"),
        ForeignKey("shipping_address_id", "customer_addresses", "address_id"),
        ForeignKey("billing_address_id", "customer_addresses", "address_id"),
    ),
    # Each eligible cart generates exactly one checkout.
    unique_columns=("cart_id",),
)

ORDERS = Dataset(
    name="orders",
    columns={
        "order_id": pl.Int64(),
        "order_number": pl.String(),
        "checkout_id": pl.Int64(),
        "cart_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "session_id": pl.Int64(),
        "shipping_address_id": pl.Int64(),
        "billing_address_id": pl.Int64(),
        "current_status": pl.String(),
        "subtotal": pl.Float64(),
        "shipping_cost": pl.Float64(),
        "tax_amount": pl.Float64(),
        "discount_amount": pl.Float64(),
        "total_amount": pl.Float64(),
        "order_date": pl.Date(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="order_id",
    foreign_keys=(
        ForeignKey("checkout_id", "checkout", "checkout_id"),
        ForeignKey("cart_id", "shopping_carts", "cart_id"),
        ForeignKey("customer_id", "customers", "customer_id"),
        ForeignKey("session_id", "sessions", "session_id"),
        ForeignKey("shipping_address_id", "customer_addresses", "address_id"),
        ForeignKey("billing_address_id", "customer_addresses", "address_id"),
    ),
    # Exactly one order per successful checkout, and therefore per cart.
    unique_columns=("order_number", "checkout_id", "cart_id"),
)

ORDER_LINES = Dataset(
    name="order_lines",
    columns={
        "order_line_id": pl.Int64(),
        "order_id": pl.Int64(),
        "product_id": pl.Int64(),
        "quantity": pl.Int64(),
        "unit_price": pl.Float64(),
        "line_total": pl.Float64(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="order_line_id",
    foreign_keys=(
        ForeignKey("order_id", "orders", "order_id"),
        ForeignKey("product_id", "products", "product_id"),
    ),
)

ORDER_STATUS_HISTORY = Dataset(
    name="order_status_history",
    columns={
        "history_id": pl.Int64(),
        "order_id": pl.Int64(),
        "status": pl.String(),
        "sequence": pl.Int64(),
        "status_timestamp": pl.Datetime("us"),
    },
    primary_key="history_id",
    foreign_keys=(ForeignKey("order_id", "orders", "order_id"),),
)

PAYMENTS = Dataset(
    name="payments",
    columns={
        "payment_id": pl.Int64(),
        "payment_reference": pl.String(),
        "order_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "payment_method": pl.String(),
        "payment_provider": pl.String(),
        "currency": pl.String(),
        "payment_amount": pl.Float64(),
        "payment_status": pl.String(),
        "authorized_at": pl.Datetime("us"),
        "captured_at": pl.Datetime("us"),
        "created_at": pl.Datetime("us"),
    },
    primary_key="payment_id",
    foreign_keys=(
        ForeignKey("order_id", "orders", "order_id"),
        ForeignKey("customer_id", "customers", "customer_id"),
    ),
    # Exactly one payment per order.
    unique_columns=("payment_reference", "order_id"),
)

PAYMENT_STATUS_HISTORY = Dataset(
    name="payment_status_history",
    columns={
        "history_id": pl.Int64(),
        "payment_id": pl.Int64(),
        "status": pl.String(),
        "sequence": pl.Int64(),
        "status_timestamp": pl.Datetime("us"),
    },
    primary_key="history_id",
    foreign_keys=(ForeignKey("payment_id", "payments", "payment_id"),),
)

SHIPMENTS = Dataset(
    name="shipments",
    columns={
        "shipment_id": pl.Int64(),
        "shipment_number": pl.String(),
        "order_id": pl.Int64(),
        "payment_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "carrier": pl.String(),
        "shipping_method": pl.String(),
        "tracking_number": pl.String(),
        "current_status": pl.String(),
        "shipped_at": pl.Datetime("us"),
        "estimated_delivery_at": pl.Datetime("us"),
        "delivered_at": pl.Datetime("us"),
        "created_at": pl.Datetime("us"),
    },
    primary_key="shipment_id",
    foreign_keys=(
        ForeignKey("order_id", "orders", "order_id"),
        ForeignKey("payment_id", "payments", "payment_id"),
        ForeignKey("customer_id", "customers", "customer_id"),
    ),
    # Exactly one shipment per captured payment, and therefore per order.
    unique_columns=("shipment_number", "tracking_number", "payment_id", "order_id"),
)

SHIPMENT_ITEMS = Dataset(
    name="shipment_items",
    columns={
        "shipment_item_id": pl.Int64(),
        "shipment_id": pl.Int64(),
        "order_line_id": pl.Int64(),
        "product_id": pl.Int64(),
        "quantity": pl.Int64(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="shipment_item_id",
    foreign_keys=(
        ForeignKey("shipment_id", "shipments", "shipment_id"),
        ForeignKey("order_line_id", "order_lines", "order_line_id"),
        ForeignKey("product_id", "products", "product_id"),
    ),
    # Split shipments are out of scope, so an order line ships exactly once.
    unique_columns=("order_line_id",),
)

SHIPMENT_STATUS_HISTORY = Dataset(
    name="shipment_status_history",
    columns={
        "history_id": pl.Int64(),
        "shipment_id": pl.Int64(),
        "status": pl.String(),
        "sequence": pl.Int64(),
        "status_timestamp": pl.Datetime("us"),
    },
    primary_key="history_id",
    foreign_keys=(ForeignKey("shipment_id", "shipments", "shipment_id"),),
)

RETURNS = Dataset(
    name="returns",
    columns={
        "return_id": pl.Int64(),
        "return_number": pl.String(),
        "shipment_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "return_reason": pl.String(),
        "refund_type": pl.String(),
        "current_status": pl.String(),
        "requested_at": pl.Datetime("us"),
        "approved_at": pl.Datetime("us"),
        "received_at": pl.Datetime("us"),
        "completed_at": pl.Datetime("us"),
        "created_at": pl.Datetime("us"),
    },
    primary_key="return_id",
    foreign_keys=(
        ForeignKey("shipment_id", "shipments", "shipment_id"),
        ForeignKey("customer_id", "customers", "customer_id"),
        # The reason vocabulary is master data, not a literal in the generator.
        ForeignKey("return_reason", "return_reasons", "reason_code"),
    ),
    # At most one return request per delivered shipment.
    unique_columns=("return_number", "shipment_id"),
)

RETURN_ITEMS = Dataset(
    name="return_items",
    columns={
        "return_item_id": pl.Int64(),
        "return_id": pl.Int64(),
        "shipment_item_id": pl.Int64(),
        "order_line_id": pl.Int64(),
        "product_id": pl.Int64(),
        "quantity": pl.Int64(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="return_item_id",
    foreign_keys=(
        ForeignKey("return_id", "returns", "return_id"),
        ForeignKey("shipment_item_id", "shipment_items", "shipment_item_id"),
        ForeignKey("order_line_id", "order_lines", "order_line_id"),
        ForeignKey("product_id", "products", "product_id"),
    ),
    # A shipped item comes back at most once: exchanges are out of scope.
    unique_columns=("shipment_item_id",),
)

RETURN_STATUS_HISTORY = Dataset(
    name="return_status_history",
    columns={
        "history_id": pl.Int64(),
        "return_id": pl.Int64(),
        "status": pl.String(),
        "sequence": pl.Int64(),
        "status_timestamp": pl.Datetime("us"),
    },
    primary_key="history_id",
    foreign_keys=(ForeignKey("return_id", "returns", "return_id"),),
)

REVIEWS = Dataset(
    name="reviews",
    columns={
        "review_id": pl.Int64(),
        "review_number": pl.String(),
        "shipment_item_id": pl.Int64(),
        "shipment_id": pl.Int64(),
        "order_id": pl.Int64(),
        "product_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "rating": pl.Int64(),
        "review_title": pl.String(),
        "review_text": pl.String(),
        "verified_purchase": pl.Boolean(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="review_id",
    foreign_keys=(
        ForeignKey("shipment_item_id", "shipment_items", "shipment_item_id"),
        ForeignKey("shipment_id", "shipments", "shipment_id"),
        ForeignKey("order_id", "orders", "order_id"),
        ForeignKey("product_id", "products", "product_id"),
        ForeignKey("customer_id", "customers", "customer_id"),
    ),
    # A delivered item is reviewed at most once: edits are out of scope.
    unique_columns=("review_number", "shipment_item_id"),
)

COMMERCE_DATASETS: tuple[Dataset, ...] = (SHOPPING_CARTS, CART_ITEMS)

#: The F005 checkout dataset, generated on top of the commerce datasets.
CHECKOUT_DATASETS: tuple[Dataset, ...] = (CHECKOUT,)

#: The F006 order datasets, generated on top of the checkout dataset. Lines
#: and status history are separate datasets under ADR-011 and ADR-010: a
#: collection is never stored inside its parent, and state over time is never
#: a mutable field.
ORDER_DATASETS: tuple[Dataset, ...] = (ORDERS, ORDER_LINES, ORDER_STATUS_HISTORY)

#: The F007 payment datasets, generated on top of the order datasets. The
#: status history is a separate dataset under ADR-010, and the payment itself
#: is immutable under ADR-012.
PAYMENT_DATASETS: tuple[Dataset, ...] = (PAYMENTS, PAYMENT_STATUS_HISTORY)

#: The F008 shipment datasets, generated on top of the payment datasets. Items
#: and status history are separate datasets under ADR-011 and ADR-010, and the
#: shipment itself is immutable under ADR-012.
SHIPMENT_DATASETS: tuple[Dataset, ...] = (
    SHIPMENTS,
    SHIPMENT_ITEMS,
    SHIPMENT_STATUS_HISTORY,
)

#: The F009 return datasets, generated on top of the shipment datasets. Items
#: and status history are separate datasets under ADR-011 and ADR-010, and the
#: return request itself is immutable under ADR-012.
RETURN_DATASETS: tuple[Dataset, ...] = (
    RETURNS,
    RETURN_ITEMS,
    RETURN_STATUS_HISTORY,
)

#: The F010 review dataset, generated on top of the shipment and return
#: datasets. A review has no collection of its own and no lifecycle - it is
#: written once and never changes - so unlike every other commerce feature this
#: one produces a single dataset.
REVIEW_DATASETS: tuple[Dataset, ...] = (REVIEWS,)

_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in COMMERCE_DATASETS}
_CHECKOUT_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in CHECKOUT_DATASETS}


_ORDER_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in ORDER_DATASETS}


_PAYMENT_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in PAYMENT_DATASETS}


_SHIPMENT_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in SHIPMENT_DATASETS}


_RETURN_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in RETURN_DATASETS}


_REVIEW_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in REVIEW_DATASETS}


def review_dataset_names() -> tuple[str, ...]:
    """Return every review dataset name."""
    return tuple(_REVIEW_BY_NAME)


def review_dataset_by_name(name: str) -> Dataset:
    """Look up a review dataset declaration by name.

    Args:
        name: Dataset name, such as ``"reviews"``.

    Returns:
        The matching dataset declaration.

    Raises:
        KeyError: If no review dataset with that name is registered.
    """
    try:
        return _REVIEW_BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown review dataset: {name!r}. Known datasets: {review_dataset_names()}"
        ) from None


def return_dataset_names() -> tuple[str, ...]:
    """Return every return dataset name in dependency order."""
    return tuple(_RETURN_BY_NAME)


def return_dataset_by_name(name: str) -> Dataset:
    """Look up a return dataset declaration by name.

    Args:
        name: Dataset name, such as ``"return_items"``.

    Returns:
        The matching dataset declaration.

    Raises:
        KeyError: If no return dataset with that name is registered.
    """
    try:
        return _RETURN_BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown return dataset: {name!r}. Known datasets: {return_dataset_names()}"
        ) from None


def shipment_dataset_names() -> tuple[str, ...]:
    """Return every shipment dataset name in dependency order."""
    return tuple(_SHIPMENT_BY_NAME)


def shipment_dataset_by_name(name: str) -> Dataset:
    """Look up a shipment dataset declaration by name.

    Args:
        name: Dataset name, such as ``"shipment_items"``.

    Returns:
        The matching dataset declaration.

    Raises:
        KeyError: If no shipment dataset with that name is registered.
    """
    try:
        return _SHIPMENT_BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown shipment dataset: {name!r}. Known datasets: {shipment_dataset_names()}"
        ) from None


def payment_dataset_names() -> tuple[str, ...]:
    """Return every payment dataset name in dependency order."""
    return tuple(_PAYMENT_BY_NAME)


def payment_dataset_by_name(name: str) -> Dataset:
    """Look up a payment dataset declaration by name.

    Args:
        name: Dataset name, such as ``"payment_status_history"``.

    Returns:
        The matching dataset declaration.

    Raises:
        KeyError: If no payment dataset with that name is registered.
    """
    try:
        return _PAYMENT_BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown payment dataset: {name!r}. Known datasets: {payment_dataset_names()}"
        ) from None


def order_dataset_names() -> tuple[str, ...]:
    """Return every order dataset name in dependency order."""
    return tuple(_ORDER_BY_NAME)


def order_dataset_by_name(name: str) -> Dataset:
    """Look up an order dataset declaration by name.

    Args:
        name: Dataset name, such as ``"order_lines"``.

    Returns:
        The matching dataset declaration.

    Raises:
        KeyError: If no order dataset with that name is registered.
    """
    try:
        return _ORDER_BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown order dataset: {name!r}. Known datasets: {order_dataset_names()}"
        ) from None


def checkout_dataset_names() -> tuple[str, ...]:
    """Return every checkout dataset name."""
    return tuple(_CHECKOUT_BY_NAME)


def checkout_dataset_by_name(name: str) -> Dataset:
    """Look up a checkout dataset declaration by name.

    Args:
        name: Dataset name, such as ``"checkout"``.

    Returns:
        The matching dataset declaration.

    Raises:
        KeyError: If no checkout dataset with that name is registered.
    """
    try:
        return _CHECKOUT_BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown checkout dataset: {name!r}. Known datasets: {checkout_dataset_names()}"
        ) from None


def commerce_dataset_names() -> tuple[str, ...]:
    """Return every commerce dataset name in dependency order."""
    return tuple(_BY_NAME)


def commerce_dataset_by_name(name: str) -> Dataset:
    """Look up a commerce dataset declaration by name.

    Args:
        name: Dataset name, such as ``"cart_items"``.

    Returns:
        The matching dataset declaration.

    Raises:
        KeyError: If no commerce dataset with that name is registered.
    """
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown commerce dataset: {name!r}. Known datasets: {commerce_dataset_names()}"
        ) from None
