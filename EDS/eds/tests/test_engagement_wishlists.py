"""Tests for the wishlist generator."""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import EngagementConfig
from eds.generators.journey.engagement import EngagementData
from eds.generators.journey.wishlist_generator import (
    generate_wishlists,
    iter_wishlist_batches,
)

SEED = 5252


@pytest.fixture
def config() -> EngagementConfig:
    """Return an engagement configuration with a small batch size."""
    return EngagementConfig(batch_size=500)


@pytest.fixture
def wishlists(engagement_data: EngagementData) -> pl.DataFrame:
    """Return the generated wishlists frame."""
    return engagement_data["wishlists"]


@pytest.fixture
def product_views(engagement_data: EngagementData) -> pl.DataFrame:
    """Return the generated product views frame."""
    return engagement_data["product_views"]


@pytest.fixture
def personas(engagement_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the customer personas frame."""
    return engagement_upstream["customer_personas"]


@pytest.fixture
def sessions(engagement_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the sessions frame."""
    return engagement_upstream["sessions"]


def test_wishlist_ids_are_unique_and_sequential(wishlists: pl.DataFrame) -> None:
    """Wishlist ids form a dense sequence starting at one."""
    assert wishlists["wishlist_id"].to_list() == list(range(1, wishlists.height + 1))


def test_every_entry_originates_from_a_product_view(
    wishlists: pl.DataFrame, product_views: pl.DataFrame
) -> None:
    """No wishlist product was invented."""
    assert set(wishlists["product_view_id"].to_list()) <= set(
        product_views["product_view_id"].to_list()
    )


def test_entry_matches_the_product_that_was_viewed(
    wishlists: pl.DataFrame, product_views: pl.DataFrame
) -> None:
    """Product, customer, and source all come from the originating view."""
    joined = wishlists.join(
        product_views.select(
            "product_view_id",
            pl.col("product_id").alias("viewed_product"),
            pl.col("customer_id").alias("viewing_customer"),
            pl.col("view_source").alias("origin_source"),
        ),
        on="product_view_id",
        how="inner",
    )

    assert joined.height == wishlists.height
    assert joined.filter(pl.col("product_id") != pl.col("viewed_product")).height == 0
    assert joined.filter(pl.col("customer_id") != pl.col("viewing_customer")).height == 0
    assert joined.filter(pl.col("added_from_source") != pl.col("origin_source")).height == 0


def test_a_customer_never_saves_the_same_product_twice(
    wishlists: pl.DataFrame,
) -> None:
    """Customer and product form a natural composite key."""
    pairs = wishlists.select("customer_id", "product_id")

    assert pairs.n_unique() == pairs.height


def test_entries_are_saved_after_the_product_was_viewed(
    wishlists: pl.DataFrame, product_views: pl.DataFrame
) -> None:
    """Chronology holds: view first, then save."""
    joined = wishlists.join(
        product_views.select("product_view_id", pl.col("timestamp").alias("view_time")),
        on="product_view_id",
    )

    assert joined.filter(pl.col("timestamp") <= pl.col("view_time")).height == 0


def test_entries_stay_inside_their_session(
    wishlists: pl.DataFrame, product_views: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """A wishlist entry never outlives the session it was saved in."""
    joined = wishlists.join(
        product_views.select("product_view_id", "session_id"), on="product_view_id"
    ).join(sessions.select("session_id", "start_time", "end_time"), on="session_id")

    assert joined.filter(pl.col("timestamp") < pl.col("start_time")).height == 0
    assert joined.filter(pl.col("timestamp") > pl.col("end_time")).height == 0


def test_only_a_minority_of_customers_use_the_wishlist(
    wishlists: pl.DataFrame, personas: pl.DataFrame
) -> None:
    """Between eight and twelve per cent of customers create a wishlist."""
    share = wishlists["customer_id"].n_unique() / personas.height

    assert 0.05 <= share <= 0.16


def test_wishlist_users_save_several_products(
    wishlists: pl.DataFrame,
) -> None:
    """A wishlist user saves more than a single product on average."""
    per_customer = wishlists.group_by("customer_id").len()["len"].to_list()

    assert sum(per_customer) / len(per_customer) > 1.0


def test_added_from_source_uses_declared_values(
    wishlists: pl.DataFrame, product_views: pl.DataFrame
) -> None:
    """The source vocabulary matches the product view sources."""
    assert set(wishlists["added_from_source"].to_list()) <= set(
        product_views["view_source"].to_list()
    )


def test_batching_does_not_change_the_output(
    personas: pl.DataFrame, product_views: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = generate_wishlists(
        EngagementConfig(batch_size=17), personas, product_views, sessions, SEED
    )
    large = generate_wishlists(
        EngagementConfig(batch_size=1_000_000), personas, product_views, sessions, SEED
    )

    assert small.equals(large)


def test_batches_are_bounded_by_the_configured_size(
    personas: pl.DataFrame, product_views: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """No batch exceeds the configured size."""
    batches = list(
        iter_wishlist_batches(
            EngagementConfig(batch_size=50), personas, product_views, sessions, SEED
        )
    )

    assert batches
    assert all(batch.height <= 50 for batch in batches)


def test_generation_is_deterministic(
    config: EngagementConfig,
    personas: pl.DataFrame,
    product_views: pl.DataFrame,
    sessions: pl.DataFrame,
) -> None:
    """The same seed reproduces the same wishlists."""
    first = generate_wishlists(config, personas, product_views, sessions, SEED)
    second = generate_wishlists(config, personas, product_views, sessions, SEED)

    assert first.equals(second)


def test_generation_varies_with_the_seed(
    config: EngagementConfig,
    personas: pl.DataFrame,
    product_views: pl.DataFrame,
    sessions: pl.DataFrame,
) -> None:
    """A different seed produces different wishlists."""
    first = generate_wishlists(config, personas, product_views, sessions, 1)
    second = generate_wishlists(config, personas, product_views, sessions, 2)

    assert not first.equals(second)


def test_zero_view_rate_produces_no_wishlists(
    personas: pl.DataFrame, product_views: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """Turning the rate off yields an empty, schema-shaped frame."""
    config = EngagementConfig(wishlist_view_rate=0.0)

    result = generate_wishlists(config, personas, product_views, sessions, SEED)

    assert result.height == 0
    assert result.columns == [
        "wishlist_id",
        "customer_id",
        "product_view_id",
        "product_id",
        "added_from_source",
        "timestamp",
        "created_at",
    ]


def test_no_product_views_produces_no_wishlists(
    config: EngagementConfig,
    personas: pl.DataFrame,
    product_views: pl.DataFrame,
    sessions: pl.DataFrame,
) -> None:
    """Without product views there is nothing to save."""
    result = generate_wishlists(config, personas, product_views.clear(), sessions, SEED)

    assert result.height == 0


def test_unknown_persona_is_reported(
    config: EngagementConfig,
    personas: pl.DataFrame,
    product_views: pl.DataFrame,
    sessions: pl.DataFrame,
) -> None:
    """A customer naming an unsupported persona fails loudly."""
    broken = personas.with_columns(pl.lit("TIME_TRAVELLER").alias("persona_name"))

    with pytest.raises(KeyError, match="Supported personas"):
        generate_wishlists(config, broken, product_views, sessions, SEED)
