"""Schemas for the customer journey datasets.

Personas are one-to-one with customers; sessions are many-to-one. Sessions
carry the geography keys of the customer's primary address, declared as
foreign keys so the shared referential validator resolves them against the
F001 geography datasets.
"""

from __future__ import annotations

import polars as pl

from eds.core.schema import Dataset, ForeignKey

__all__ = [
    "BROWSING_DATASETS",
    "CATEGORY_VIEWS",
    "CUSTOMER_PERSONAS",
    "ENGAGEMENT_DATASETS",
    "JOURNEY_DATASETS",
    "PRODUCT_VIEWS",
    "SEARCH_HISTORY",
    "SESSIONS",
    "WISHLISTS",
    "browsing_dataset_by_name",
    "browsing_dataset_names",
    "engagement_dataset_by_name",
    "engagement_dataset_names",
    "journey_dataset_by_name",
    "journey_dataset_names",
]

CUSTOMER_PERSONAS = Dataset(
    name="customer_personas",
    columns={
        "persona_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "persona_name": pl.String(),
        "purchase_intent": pl.Float64(),
        "price_sensitivity": pl.Float64(),
        "brand_loyalty": pl.Float64(),
        "research_depth": pl.Float64(),
        "session_frequency": pl.Int64(),
        "average_session_minutes": pl.Float64(),
        "wishlist_probability": pl.Float64(),
        "cart_probability": pl.Float64(),
        "purchase_probability": pl.Float64(),
        "description": pl.String(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="persona_id",
    foreign_keys=(ForeignKey("customer_id", "customers", "customer_id"),),
    unique_columns=("customer_id",),
)

SESSIONS = Dataset(
    name="sessions",
    columns={
        "session_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "persona_name": pl.String(),
        "device_type": pl.String(),
        "browser": pl.String(),
        "operating_system": pl.String(),
        "traffic_source": pl.String(),
        "landing_page": pl.String(),
        "exit_page": pl.String(),
        "country_id": pl.Int64(),
        "state_id": pl.Int64(),
        "city_id": pl.Int64(),
        "ip_address": pl.String(),
        "start_time": pl.Datetime("us"),
        "end_time": pl.Datetime("us"),
        "duration_seconds": pl.Int64(),
        "pages_viewed": pl.Int64(),
        "bounce": pl.Boolean(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="session_id",
    foreign_keys=(
        ForeignKey("customer_id", "customers", "customer_id"),
        ForeignKey("country_id", "countries", "country_id"),
        ForeignKey("state_id", "states", "state_id"),
        ForeignKey("city_id", "cities", "city_id"),
    ),
)

CATEGORY_VIEWS = Dataset(
    name="category_views",
    columns={
        "category_view_id": pl.Int64(),
        "session_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "category_id": pl.Int64(),
        "view_sequence": pl.Int64(),
        "entry_method": pl.String(),
        "timestamp": pl.Datetime("us"),
        "duration_seconds": pl.Int64(),
        "created_at": pl.Datetime("us"),
    },
    primary_key="category_view_id",
    foreign_keys=(
        ForeignKey("session_id", "sessions", "session_id"),
        ForeignKey("customer_id", "customers", "customer_id"),
        ForeignKey("category_id", "categories", "category_id"),
    ),
)

SEARCH_HISTORY = Dataset(
    name="search_history",
    columns={
        "search_id": pl.Int64(),
        "session_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "category_view_id": pl.Int64(),
        "category_id": pl.Int64(),
        "search_sequence": pl.Int64(),
        "search_text": pl.String(),
        "results_count": pl.Int64(),
        "clicked_result": pl.Boolean(),
        "timestamp": pl.Datetime("us"),
        "created_at": pl.Datetime("us"),
    },
    primary_key="search_id",
    foreign_keys=(
        ForeignKey("session_id", "sessions", "session_id"),
        ForeignKey("customer_id", "customers", "customer_id"),
        ForeignKey("category_view_id", "category_views", "category_view_id"),
        ForeignKey("category_id", "categories", "category_id"),
    ),
)

PRODUCT_VIEWS = Dataset(
    name="product_views",
    columns={
        "product_view_id": pl.Int64(),
        "session_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "category_view_id": pl.Int64(),
        "search_id": pl.Int64(),
        "category_id": pl.Int64(),
        "product_id": pl.Int64(),
        "view_sequence": pl.Int64(),
        "view_source": pl.String(),
        "view_duration_seconds": pl.Int64(),
        "timestamp": pl.Datetime("us"),
        "created_at": pl.Datetime("us"),
    },
    primary_key="product_view_id",
    foreign_keys=(
        ForeignKey("session_id", "sessions", "session_id"),
        ForeignKey("customer_id", "customers", "customer_id"),
        ForeignKey("category_view_id", "category_views", "category_view_id"),
        # Only populated when the view originated from a search.
        ForeignKey("search_id", "search_history", "search_id", nullable=True),
        ForeignKey("category_id", "categories", "category_id"),
        ForeignKey("product_id", "products", "product_id"),
    ),
)

WISHLISTS = Dataset(
    name="wishlists",
    columns={
        "wishlist_id": pl.Int64(),
        "customer_id": pl.Int64(),
        "product_view_id": pl.Int64(),
        "product_id": pl.Int64(),
        "added_from_source": pl.String(),
        "timestamp": pl.Datetime("us"),
        "created_at": pl.Datetime("us"),
    },
    primary_key="wishlist_id",
    foreign_keys=(
        ForeignKey("customer_id", "customers", "customer_id"),
        ForeignKey("product_view_id", "product_views", "product_view_id"),
        ForeignKey("product_id", "products", "product_id"),
    ),
)

JOURNEY_DATASETS: tuple[Dataset, ...] = (CUSTOMER_PERSONAS, SESSIONS)

#: The F003.2 browsing datasets, generated on top of the journey datasets.
BROWSING_DATASETS: tuple[Dataset, ...] = (CATEGORY_VIEWS, SEARCH_HISTORY)

#: The F003.3 engagement datasets, generated on top of the browsing datasets.
ENGAGEMENT_DATASETS: tuple[Dataset, ...] = (PRODUCT_VIEWS, WISHLISTS)

_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in JOURNEY_DATASETS}
_BROWSING_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in BROWSING_DATASETS}
_ENGAGEMENT_BY_NAME: dict[str, Dataset] = {dataset.name: dataset for dataset in ENGAGEMENT_DATASETS}


def engagement_dataset_names() -> tuple[str, ...]:
    """Return every engagement dataset name in dependency order."""
    return tuple(_ENGAGEMENT_BY_NAME)


def engagement_dataset_by_name(name: str) -> Dataset:
    """Look up an engagement dataset declaration by name.

    Args:
        name: Dataset name, such as ``"wishlists"``.

    Returns:
        The matching dataset declaration.

    Raises:
        KeyError: If no engagement dataset with that name is registered.
    """
    try:
        return _ENGAGEMENT_BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown engagement dataset: {name!r}. Known datasets: {engagement_dataset_names()}"
        ) from None


def browsing_dataset_names() -> tuple[str, ...]:
    """Return every browsing dataset name in dependency order."""
    return tuple(_BROWSING_BY_NAME)


def browsing_dataset_by_name(name: str) -> Dataset:
    """Look up a browsing dataset declaration by name.

    Args:
        name: Dataset name, such as ``"search_history"``.

    Returns:
        The matching dataset declaration.

    Raises:
        KeyError: If no browsing dataset with that name is registered.
    """
    try:
        return _BROWSING_BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown browsing dataset: {name!r}. Known datasets: {browsing_dataset_names()}"
        ) from None


def journey_dataset_names() -> tuple[str, ...]:
    """Return every journey dataset name in dependency order."""
    return tuple(_BY_NAME)


def journey_dataset_by_name(name: str) -> Dataset:
    """Look up a journey dataset declaration by name.

    Args:
        name: Dataset name, such as ``"sessions"``.

    Returns:
        The matching dataset declaration.

    Raises:
        KeyError: If no journey dataset with that name is registered.
    """
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"Unknown journey dataset: {name!r}. Known datasets: {journey_dataset_names()}"
        ) from None
