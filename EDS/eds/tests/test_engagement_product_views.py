"""Tests for the product view generator."""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import EngagementConfig
from eds.domain.journey.enums import PersonaName, ViewSource
from eds.generators.journey.engagement import EngagementData
from eds.generators.journey.product_view_generator import (
    PERSONA_ENGAGEMENT_PROFILES,
    POPULARITY_TIERS,
    ProductCatalog,
    generate_product_views,
    iter_product_view_batches,
    persona_engagement_profile,
)
from eds.generators.master_data import MasterData

SEED = 5252


@pytest.fixture
def config() -> EngagementConfig:
    """Return an engagement configuration with a small batch size."""
    return EngagementConfig(batch_size=500)


@pytest.fixture
def views(engagement_data: EngagementData) -> pl.DataFrame:
    """Return the generated product views frame."""
    return engagement_data["product_views"]


@pytest.fixture
def sessions(engagement_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the sessions frame."""
    return engagement_upstream["sessions"]


@pytest.fixture
def category_views(engagement_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the category views frame."""
    return engagement_upstream["category_views"]


@pytest.fixture
def searches(engagement_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the search history frame."""
    return engagement_upstream["search_history"]


def test_every_persona_has_an_engagement_profile() -> None:
    """All six personas engage with product pages."""
    assert set(PERSONA_ENGAGEMENT_PROFILES) == {str(member) for member in PersonaName}


def test_researcher_views_most_and_longest() -> None:
    """The researcher has the widest view range and longest dwell scale."""
    researcher = persona_engagement_profile(str(PersonaName.RESEARCHER))
    others = [
        persona_engagement_profile(name)
        for name in PERSONA_ENGAGEMENT_PROFILES
        if name != str(PersonaName.RESEARCHER)
    ]

    assert all(researcher.max_views >= profile.max_views for profile in others)
    assert all(researcher.duration_scale >= profile.duration_scale for profile in others)


def test_impulse_buyer_views_fewest_and_shortest() -> None:
    """The impulse buyer glances at a couple of products."""
    impulse = persona_engagement_profile(str(PersonaName.IMPULSE_BUYER))
    others = [
        persona_engagement_profile(name)
        for name in PERSONA_ENGAGEMENT_PROFILES
        if name != str(PersonaName.IMPULSE_BUYER)
    ]

    assert all(impulse.max_views <= profile.max_views for profile in others)
    assert all(impulse.duration_scale <= profile.duration_scale for profile in others)


def test_seasonal_shopper_has_the_lowest_wishlist_adoption() -> None:
    """Documented wishlist ordering: seasonal lowest, researcher highest."""
    adoption = {
        name: profile.wishlist_adoption for name, profile in PERSONA_ENGAGEMENT_PROFILES.items()
    }

    assert adoption[str(PersonaName.SEASONAL_SHOPPER)] == min(adoption.values())
    assert adoption[str(PersonaName.RESEARCHER)] == max(adoption.values())


def test_unknown_persona_profile_raises() -> None:
    """A persona without a profile fails with the supported list."""
    with pytest.raises(KeyError, match="Supported personas"):
        persona_engagement_profile("TIME_TRAVELLER")


def test_catalog_requires_categories(master_data: MasterData) -> None:
    """There must be categories to resolve products against."""
    with pytest.raises(ValueError, match="categories dataset is empty"):
        ProductCatalog.from_frames(master_data["categories"].clear(), master_data["products"], SEED)


def test_catalog_requires_products(master_data: MasterData) -> None:
    """There must be products to view."""
    with pytest.raises(ValueError, match="products dataset is empty"):
        ProductCatalog.from_frames(master_data["categories"], master_data["products"].clear(), SEED)


def test_catalog_tiers_split_the_documented_shares(
    product_catalog: ProductCatalog, master_data: MasterData
) -> None:
    """Tiers hold 20, 30 and 50 per cent of the catalog."""
    total = master_data["products"].height
    counts = {label: 0 for label, _, _ in POPULARITY_TIERS}
    for tier in product_catalog.tier_by_product.values():
        counts[tier] += 1

    for label, catalog_share, _ in POPULARITY_TIERS:
        assert counts[label] / total == pytest.approx(catalog_share, abs=0.01), label


def test_catalog_pools_include_ancestor_categories(
    product_catalog: ProductCatalog, master_data: MasterData
) -> None:
    """A parent category can surface products from its subtree."""
    categories = master_data["categories"]
    root = categories.filter(pl.col("level") == 1).row(0, named=True)
    leaf = categories.filter(pl.col("is_leaf")).row(0, named=True)

    assert product_catalog.has_products(root["category_id"])
    assert product_catalog.has_products(leaf["category_id"])
    assert len(product_catalog.ids_by_category[root["category_id"]]) > len(
        product_catalog.ids_by_category[leaf["category_id"]]
    )


def test_catalog_sample_returns_none_for_an_unknown_category(
    product_catalog: ProductCatalog,
) -> None:
    """An empty pool yields no product rather than raising."""
    import random

    assert product_catalog.sample(random.Random(0), 999_999) is None


def test_product_view_ids_are_unique_and_sequential(views: pl.DataFrame) -> None:
    """View ids form a dense sequence starting at one."""
    assert views["product_view_id"].to_list() == list(range(1, views.height + 1))


def test_views_per_category_view_average_about_three(
    views: pl.DataFrame, category_views: pl.DataFrame
) -> None:
    """The documented average of roughly three holds."""
    assert views.height / category_views.height == pytest.approx(3.0, abs=0.6)


def test_view_counts_stay_within_the_configured_bounds(
    views: pl.DataFrame, config: EngagementConfig
) -> None:
    """Between one and eight products are viewed per category view."""
    counts = views.group_by("category_view_id").len()["len"].to_list()

    assert min(counts) >= config.min_product_views
    assert max(counts) <= config.max_product_views


def test_durations_respect_the_configured_bounds(
    views: pl.DataFrame, config: EngagementConfig
) -> None:
    """Every product view lasts between five and six hundred seconds."""
    durations = views["view_duration_seconds"].to_list()

    assert min(durations) >= config.min_view_seconds
    assert max(durations) <= config.max_view_seconds


def test_average_duration_is_about_forty_five_seconds(views: pl.DataFrame) -> None:
    """The documented average dwell time holds."""
    durations = views["view_duration_seconds"].to_list()

    assert sum(durations) / len(durations) == pytest.approx(45.0, abs=12.0)


def test_view_sequences_start_at_one_within_each_session(views: pl.DataFrame) -> None:
    """Sequence numbering restarts per session without gaps."""
    grouped = views.group_by("session_id").agg(
        pl.col("view_sequence").min().alias("lowest"),
        pl.col("view_sequence").max().alias("highest"),
        pl.len().alias("total"),
    )

    assert grouped.filter(pl.col("lowest") != 1).height == 0
    assert grouped.filter(pl.col("highest") != pl.col("total")).height == 0


def test_view_sequence_follows_time_order(views: pl.DataFrame) -> None:
    """Sequence numbers ascend with the timestamp inside a session."""
    ordered = views.sort("session_id", "view_sequence")

    for (_,), group in ordered.group_by("session_id", maintain_order=True):
        stamps = group["timestamp"].to_list()
        assert stamps == sorted(stamps)


def test_views_reference_the_category_view_session_and_customer(
    views: pl.DataFrame, category_views: pl.DataFrame
) -> None:
    """Session, customer, and category are inherited from the category view."""
    joined = views.join(
        category_views.select(
            "category_view_id",
            pl.col("session_id").alias("cv_session"),
            pl.col("customer_id").alias("cv_customer"),
            pl.col("category_id").alias("cv_category"),
        ),
        on="category_view_id",
        how="inner",
    )

    assert joined.height == views.height
    assert joined.filter(pl.col("session_id") != pl.col("cv_session")).height == 0
    assert joined.filter(pl.col("customer_id") != pl.col("cv_customer")).height == 0
    assert joined.filter(pl.col("category_id") != pl.col("cv_category")).height == 0


def test_products_sit_under_the_browsed_category(
    views: pl.DataFrame, engagement_upstream: dict[str, pl.DataFrame]
) -> None:
    """A viewed product belongs to the category being browsed, or below it."""
    categories = engagement_upstream["categories"]
    products = engagement_upstream["products"]

    resolved = (
        views.join(
            categories.select("category_id", pl.col("category_path").alias("browsed")),
            on="category_id",
        )
        .join(
            products.select("product_id", pl.col("category_id").alias("product_category_id")),
            on="product_id",
        )
        .join(
            categories.select(
                pl.col("category_id").alias("product_category_id"),
                pl.col("category_path").alias("product_path"),
            ),
            on="product_category_id",
        )
    )

    assert resolved.height == views.height
    outside = resolved.filter(
        ~(
            (pl.col("product_path") == pl.col("browsed"))
            | pl.col("product_path").str.starts_with(pl.col("browsed") + "/")
        )
    )
    assert outside.height == 0


def test_view_sources_are_declared_values(views: pl.DataFrame) -> None:
    """Every source comes from the enum."""
    assert set(views["view_source"].to_list()) <= {str(m) for m in ViewSource}


def test_view_source_distribution_is_approximately_as_specified(
    views: pl.DataFrame,
) -> None:
    """Sources follow roughly the documented 55/25/10/5/5 split."""
    share = {
        row["view_source"]: row["count"] / views.height
        for row in views["view_source"].value_counts().to_dicts()
    }

    assert share[str(ViewSource.CATEGORY)] == pytest.approx(0.55, abs=0.08)
    assert share[str(ViewSource.SEARCH)] == pytest.approx(0.25, abs=0.08)
    assert share[str(ViewSource.RECOMMENDATION)] == pytest.approx(0.10, abs=0.05)
    assert share[str(ViewSource.PROMOTION)] == pytest.approx(0.05, abs=0.05)
    assert share[str(ViewSource.BRAND_PAGE)] == pytest.approx(0.05, abs=0.05)


def test_only_search_sourced_views_carry_a_search(views: pl.DataFrame) -> None:
    """`search_id` is populated exactly when the source is a search."""
    search_sourced = views.filter(pl.col("view_source") == str(ViewSource.SEARCH))
    others = views.filter(pl.col("view_source") != str(ViewSource.SEARCH))

    assert search_sourced.filter(pl.col("search_id").is_null()).height == 0
    assert others.filter(pl.col("search_id").is_not_null()).height == 0


def test_search_sourced_views_match_their_search_category(
    views: pl.DataFrame, searches: pl.DataFrame
) -> None:
    """The search that led to a view is about the same category."""
    joined = views.filter(pl.col("search_id").is_not_null()).join(
        searches.select(
            "search_id",
            pl.col("category_id").alias("search_category"),
            pl.col("timestamp").alias("search_time"),
        ),
        on="search_id",
        how="inner",
    )

    assert joined.filter(pl.col("category_id") != pl.col("search_category")).height == 0
    assert joined.filter(pl.col("timestamp") <= pl.col("search_time")).height == 0


def test_popularity_is_weighted_not_uniform(
    views: pl.DataFrame, product_catalog: ProductCatalog
) -> None:
    """The top fifth of the catalog takes roughly seventy per cent of views."""
    counts = views["product_id"].value_counts()
    shares = {label: 0 for label, _, _ in POPULARITY_TIERS}
    for product_id, count in zip(
        counts["product_id"].to_list(), counts["count"].to_list(), strict=True
    ):
        shares[product_catalog.tier_by_product[product_id]] += count

    total = sum(shares.values())

    assert shares["HOT"] / total == pytest.approx(0.70, abs=0.08)
    assert shares["WARM"] / total == pytest.approx(0.20, abs=0.07)
    assert shares["COLD"] / total == pytest.approx(0.10, abs=0.06)


def test_bargain_hunters_view_more_from_promotions(
    views: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """The documented persona preference shows up in the data."""
    joined = views.join(sessions.select("session_id", "persona_name"), on="session_id")
    bargain = joined.filter(pl.col("persona_name") == str(PersonaName.BARGAIN_HUNTER))
    others = joined.filter(pl.col("persona_name") != str(PersonaName.BARGAIN_HUNTER))

    bargain_share = (
        bargain.filter(pl.col("view_source") == str(ViewSource.PROMOTION)).height / bargain.height
    )
    other_share = (
        others.filter(pl.col("view_source") == str(ViewSource.PROMOTION)).height / others.height
    )

    assert bargain_share > other_share


def test_loyal_customers_view_more_from_brand_pages(
    views: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """Loyal customers return to familiar brands more than others."""
    joined = views.join(sessions.select("session_id", "persona_name"), on="session_id")
    loyal = joined.filter(pl.col("persona_name") == str(PersonaName.LOYAL_CUSTOMER))
    others = joined.filter(pl.col("persona_name") != str(PersonaName.LOYAL_CUSTOMER))

    loyal_share = (
        loyal.filter(pl.col("view_source") == str(ViewSource.BRAND_PAGE)).height / loyal.height
    )
    other_share = (
        others.filter(pl.col("view_source") == str(ViewSource.BRAND_PAGE)).height / others.height
    )

    assert loyal_share > other_share


def test_researchers_dwell_longer_than_impulse_buyers(
    views: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """Persona duration scales are reflected in the generated data."""
    joined = views.join(sessions.select("session_id", "persona_name"), on="session_id")

    researcher = joined.filter(pl.col("persona_name") == str(PersonaName.RESEARCHER))
    impulse = joined.filter(pl.col("persona_name") == str(PersonaName.IMPULSE_BUYER))

    researcher_mean = sum(researcher["view_duration_seconds"].to_list()) / researcher.height
    impulse_mean = sum(impulse["view_duration_seconds"].to_list()) / impulse.height

    assert researcher_mean > impulse_mean


def test_views_fall_inside_their_session(views: pl.DataFrame, sessions: pl.DataFrame) -> None:
    """A product view never starts before or ends after its session."""
    joined = views.join(sessions.select("session_id", "start_time", "end_time"), on="session_id")

    assert joined.filter(pl.col("timestamp") < pl.col("start_time")).height == 0
    assert (
        joined.filter(
            pl.col("timestamp") + pl.duration(seconds=pl.col("view_duration_seconds"))
            > pl.col("end_time")
        ).height
        == 0
    )


def test_views_happen_after_their_category_view(
    views: pl.DataFrame, category_views: pl.DataFrame
) -> None:
    """A product is opened from a category page, never before it."""
    joined = views.join(
        category_views.select("category_view_id", pl.col("timestamp").alias("category_time")),
        on="category_view_id",
    )

    assert joined.filter(pl.col("timestamp") < pl.col("category_time")).height == 0


def test_batching_does_not_change_the_output(
    sessions: pl.DataFrame,
    category_views: pl.DataFrame,
    searches: pl.DataFrame,
    product_catalog: ProductCatalog,
) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = generate_product_views(
        EngagementConfig(batch_size=97),
        sessions,
        category_views,
        searches,
        product_catalog,
        SEED,
    )
    large = generate_product_views(
        EngagementConfig(batch_size=1_000_000),
        sessions,
        category_views,
        searches,
        product_catalog,
        SEED,
    )

    assert small.equals(large)


def test_batches_never_split_a_session(
    sessions: pl.DataFrame,
    category_views: pl.DataFrame,
    searches: pl.DataFrame,
    product_catalog: ProductCatalog,
) -> None:
    """A session's product views always land in one frame."""
    seen: set[int] = set()

    for batch in iter_product_view_batches(
        EngagementConfig(batch_size=300),
        sessions,
        category_views,
        searches,
        product_catalog,
        SEED,
    ):
        in_batch = set(batch["session_id"].to_list())
        assert not (in_batch & seen)
        seen |= in_batch


def test_generation_is_deterministic(
    config: EngagementConfig,
    sessions: pl.DataFrame,
    category_views: pl.DataFrame,
    searches: pl.DataFrame,
    product_catalog: ProductCatalog,
) -> None:
    """The same seed reproduces the same product views."""
    first = generate_product_views(
        config, sessions, category_views, searches, product_catalog, SEED
    )
    second = generate_product_views(
        config, sessions, category_views, searches, product_catalog, SEED
    )

    assert first.equals(second)


def test_generation_varies_with_the_seed(
    config: EngagementConfig,
    sessions: pl.DataFrame,
    category_views: pl.DataFrame,
    searches: pl.DataFrame,
    product_catalog: ProductCatalog,
) -> None:
    """A different seed produces different product views."""
    first = generate_product_views(config, sessions, category_views, searches, product_catalog, 1)
    second = generate_product_views(config, sessions, category_views, searches, product_catalog, 2)

    assert not first.equals(second)


def test_unknown_persona_on_a_session_is_reported(
    config: EngagementConfig,
    sessions: pl.DataFrame,
    category_views: pl.DataFrame,
    searches: pl.DataFrame,
    product_catalog: ProductCatalog,
) -> None:
    """A session naming an unsupported persona fails loudly."""
    broken = sessions.with_columns(pl.lit("TIME_TRAVELLER").alias("persona_name"))

    with pytest.raises(KeyError, match="Supported personas"):
        generate_product_views(config, broken, category_views, searches, product_catalog, SEED)
