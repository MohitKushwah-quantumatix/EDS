"""Tests for the category view generator."""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import BrowsingConfig
from eds.domain.journey.enums import EntryMethod, LandingPage, PersonaName
from eds.generators.journey.category_generator import (
    PERSONA_VIEW_PROFILES,
    CategoryCatalog,
    generate_category_views,
    iter_category_view_batches,
    persona_view_profile,
)
from eds.generators.journey.journey import JourneyData
from eds.generators.master_data import MasterData

SEED = 3131


@pytest.fixture
def sessions(journey_data: JourneyData) -> pl.DataFrame:
    """Return the generated sessions frame."""
    return journey_data["sessions"]


@pytest.fixture
def config() -> BrowsingConfig:
    """Return a browsing configuration with a small batch size."""
    return BrowsingConfig(batch_size=400)


@pytest.fixture
def views(
    config: BrowsingConfig, sessions: pl.DataFrame, category_catalog: CategoryCatalog
) -> pl.DataFrame:
    """Return generated category views."""
    return generate_category_views(config, sessions, category_catalog, SEED)


def test_every_persona_has_a_browsing_profile() -> None:
    """All six personas can browse."""
    assert set(PERSONA_VIEW_PROFILES) == {str(member) for member in PersonaName}


def test_profile_ranges_match_the_specification() -> None:
    """View ranges are the documented per-persona bands."""
    expected = {
        str(PersonaName.RESEARCHER): (6, 10),
        str(PersonaName.WINDOW_SHOPPER): (5, 8),
        str(PersonaName.BARGAIN_HUNTER): (4, 7),
        str(PersonaName.LOYAL_CUSTOMER): (3, 6),
        str(PersonaName.IMPULSE_BUYER): (1, 3),
        str(PersonaName.SEASONAL_SHOPPER): (1, 4),
    }

    for name, (low, high) in expected.items():
        profile = persona_view_profile(name)
        assert (profile.min_views, profile.max_views) == (low, high), name


def test_researcher_browses_longest() -> None:
    """The researcher's page dwell time exceeds every other persona's."""
    researcher = persona_view_profile(str(PersonaName.RESEARCHER))
    others = [
        persona_view_profile(name)
        for name in PERSONA_VIEW_PROFILES
        if name != str(PersonaName.RESEARCHER)
    ]

    assert all(researcher.max_seconds >= profile.max_seconds for profile in others)


def test_impulse_buyer_browses_shortest() -> None:
    """The impulse buyer has the shortest dwell time."""
    impulse = persona_view_profile(str(PersonaName.IMPULSE_BUYER))
    others = [
        persona_view_profile(name)
        for name in PERSONA_VIEW_PROFILES
        if name != str(PersonaName.IMPULSE_BUYER)
    ]

    assert all(impulse.max_seconds <= profile.max_seconds for profile in others)


def test_unknown_persona_profile_raises() -> None:
    """A persona without a profile fails with the supported list."""
    with pytest.raises(KeyError, match="Supported personas"):
        persona_view_profile("TIME_TRAVELLER")


def test_catalog_requires_categories(master_data: MasterData) -> None:
    """There must be something to browse."""
    with pytest.raises(ValueError, match="categories dataset is empty"):
        CategoryCatalog.from_frame(master_data["categories"].clear())


def test_catalog_resolves_roots(category_catalog: CategoryCatalog, master_data: MasterData) -> None:
    """Every category resolves to its level-1 ancestor."""
    categories = master_data["categories"]
    roots = set(categories.filter(pl.col("level") == 1)["category_name"].to_list())

    assert len(category_catalog.category_ids) == categories.height
    assert set(category_catalog.ids_by_root) == roots


def test_every_session_has_at_least_one_view(views: pl.DataFrame, sessions: pl.DataFrame) -> None:
    """No session is left without a category view."""
    assert views["session_id"].n_unique() == sessions.height


def test_view_ids_are_unique_and_sequential(views: pl.DataFrame) -> None:
    """View ids form a dense sequence starting at one."""
    assert views["category_view_id"].to_list() == list(range(1, views.height + 1))


def test_view_counts_stay_within_the_configured_bounds(
    views: pl.DataFrame, config: BrowsingConfig
) -> None:
    """Sessions view between one and ten categories."""
    counts = views.group_by("session_id").len()["len"].to_list()

    assert min(counts) >= config.min_category_views
    assert max(counts) <= config.max_category_views


def test_average_view_count_is_approximately_five(views: pl.DataFrame) -> None:
    """The documented average of roughly five holds."""
    counts = views.group_by("session_id").len()["len"].to_list()

    assert sum(counts) / len(counts) == pytest.approx(5.0, abs=1.0)


def test_bounce_sessions_view_exactly_one_category(
    views: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """A bounce viewed one page, so it viewed one category."""
    bounced = sessions.filter(pl.col("bounce")).select("session_id")
    counts = views.join(bounced, on="session_id", how="inner").group_by("session_id").len()

    assert set(counts["len"].to_list()) == {1}


def test_view_sequences_start_at_one_and_are_contiguous(views: pl.DataFrame) -> None:
    """Sequence numbering restarts per session without gaps."""
    grouped = views.group_by("session_id").agg(
        pl.col("view_sequence").min().alias("lowest"),
        pl.col("view_sequence").max().alias("highest"),
        pl.len().alias("total"),
    )

    assert grouped.filter(pl.col("lowest") != 1).height == 0
    assert grouped.filter(pl.col("highest") != pl.col("total")).height == 0


def test_durations_respect_the_configured_bounds(
    views: pl.DataFrame, config: BrowsingConfig
) -> None:
    """Every view lasts between five and one hundred and eighty seconds."""
    durations = views["duration_seconds"].to_list()

    assert min(durations) >= config.min_view_seconds
    assert max(durations) <= config.max_view_seconds


def test_views_fall_inside_their_session(views: pl.DataFrame, sessions: pl.DataFrame) -> None:
    """A view never starts before or ends after its session."""
    joined = views.join(sessions.select("session_id", "start_time", "end_time"), on="session_id")

    assert joined.filter(pl.col("timestamp") < pl.col("start_time")).height == 0
    assert (
        joined.filter(
            pl.col("timestamp") + pl.duration(seconds=pl.col("duration_seconds"))
            > pl.col("end_time")
        ).height
        == 0
    )


def test_views_are_chronological_within_a_session(views: pl.DataFrame) -> None:
    """View timestamps ascend with the sequence number."""
    ordered = views.sort("session_id", "view_sequence")

    for (_,), group in ordered.group_by("session_id", maintain_order=True):
        stamps = group["timestamp"].to_list()
        assert stamps == sorted(stamps)


def test_views_reference_real_categories(views: pl.DataFrame, master_data: MasterData) -> None:
    """Every category exists in the F001 catalog."""
    assert set(views["category_id"].to_list()) <= set(
        master_data["categories"]["category_id"].to_list()
    )


def test_views_reference_the_session_customer(views: pl.DataFrame, sessions: pl.DataFrame) -> None:
    """A view's customer matches the customer who owned the session."""
    joined = views.join(
        sessions.select("session_id", pl.col("customer_id").alias("session_customer")),
        on="session_id",
    )

    assert joined.filter(pl.col("customer_id") != pl.col("session_customer")).height == 0


def test_entry_methods_are_declared_values(views: pl.DataFrame) -> None:
    """Every entry method comes from the enum."""
    assert set(views["entry_method"].to_list()) <= {str(m) for m in EntryMethod}


def test_first_view_entry_method_follows_the_landing_page(
    views: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """The visit's first category is entered the way the session landed."""
    first = views.filter(pl.col("view_sequence") == 1).join(
        sessions.select("session_id", "landing_page"), on="session_id"
    )
    homepage = first.filter(pl.col("landing_page") == str(LandingPage.HOMEPAGE))
    search = first.filter(pl.col("landing_page") == str(LandingPage.SEARCH))

    assert set(homepage["entry_method"].to_list()) == {str(EntryMethod.HOMEPAGE)}
    assert set(search["entry_method"].to_list()) == {str(EntryMethod.SEARCH_RESULT)}


def test_bargain_hunters_prefer_promotion_banners(
    views: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """The documented persona preference shows up in the data."""
    joined = views.filter(pl.col("view_sequence") > 1).join(
        sessions.select("session_id", "persona_name"), on="session_id"
    )
    bargain = joined.filter(pl.col("persona_name") == str(PersonaName.BARGAIN_HUNTER))
    others = joined.filter(pl.col("persona_name") != str(PersonaName.BARGAIN_HUNTER))

    bargain_share = (
        bargain.filter(pl.col("entry_method") == str(EntryMethod.PROMOTION_BANNER)).height
        / bargain.height
    )
    other_share = (
        others.filter(pl.col("entry_method") == str(EntryMethod.PROMOTION_BANNER)).height
        / others.height
    )

    assert bargain_share > other_share


def test_loyal_customers_prefer_the_homepage(views: pl.DataFrame, sessions: pl.DataFrame) -> None:
    """Loyal customers return through the homepage more than others."""
    joined = views.filter(pl.col("view_sequence") > 1).join(
        sessions.select("session_id", "persona_name"), on="session_id"
    )
    loyal = joined.filter(pl.col("persona_name") == str(PersonaName.LOYAL_CUSTOMER))
    others = joined.filter(pl.col("persona_name") != str(PersonaName.LOYAL_CUSTOMER))

    loyal_share = (
        loyal.filter(pl.col("entry_method") == str(EntryMethod.HOMEPAGE)).height / loyal.height
    )
    other_share = (
        others.filter(pl.col("entry_method") == str(EntryMethod.HOMEPAGE)).height / others.height
    )

    assert loyal_share > other_share


def test_researchers_view_more_categories_than_impulse_buyers(
    views: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """Persona view ranges are reflected in the generated data."""
    joined = views.join(sessions.select("session_id", "persona_name"), on="session_id")
    per_session = joined.group_by("session_id", "persona_name").len()

    researcher = per_session.filter(pl.col("persona_name") == str(PersonaName.RESEARCHER))
    impulse = per_session.filter(pl.col("persona_name") == str(PersonaName.IMPULSE_BUYER))

    researcher_mean = sum(researcher["len"].to_list()) / researcher.height
    impulse_mean = sum(impulse["len"].to_list()) / impulse.height

    assert researcher_mean > impulse_mean


def test_browsing_stays_within_a_section_most_of_the_time(
    views: pl.DataFrame, category_catalog: CategoryCatalog
) -> None:
    """Consecutive views usually share a top-level category."""
    ordered = views.sort("session_id", "view_sequence")
    session_ids = ordered["session_id"].to_list()
    category_ids = ordered["category_id"].to_list()

    transitions = 0
    same_section = 0
    for index in range(1, len(session_ids)):
        if session_ids[index] != session_ids[index - 1]:
            continue
        transitions += 1
        if category_catalog.root_of(category_ids[index]) == category_catalog.root_of(
            category_ids[index - 1]
        ):
            same_section += 1

    assert transitions > 0
    assert same_section / transitions > 0.5


def test_batching_does_not_change_the_output(
    sessions: pl.DataFrame, category_catalog: CategoryCatalog
) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = generate_category_views(BrowsingConfig(batch_size=37), sessions, category_catalog, SEED)
    large = generate_category_views(
        BrowsingConfig(batch_size=1_000_000), sessions, category_catalog, SEED
    )

    assert small.equals(large)


def test_batches_never_split_a_session(
    sessions: pl.DataFrame, category_catalog: CategoryCatalog
) -> None:
    """A session's views always land in one frame."""
    seen: set[int] = set()

    for batch in iter_category_view_batches(
        BrowsingConfig(batch_size=200), sessions, category_catalog, SEED
    ):
        in_batch = set(batch["session_id"].to_list())
        assert not (in_batch & seen)
        seen |= in_batch


def test_generation_is_deterministic(
    config: BrowsingConfig, sessions: pl.DataFrame, category_catalog: CategoryCatalog
) -> None:
    """The same seed reproduces the same views."""
    assert generate_category_views(config, sessions, category_catalog, SEED).equals(
        generate_category_views(config, sessions, category_catalog, SEED)
    )


def test_generation_varies_with_the_seed(
    config: BrowsingConfig, sessions: pl.DataFrame, category_catalog: CategoryCatalog
) -> None:
    """A different seed produces different views."""
    assert not generate_category_views(config, sessions, category_catalog, 1).equals(
        generate_category_views(config, sessions, category_catalog, 2)
    )


def test_unknown_persona_on_a_session_is_reported(
    config: BrowsingConfig, sessions: pl.DataFrame, category_catalog: CategoryCatalog
) -> None:
    """A session naming an unsupported persona fails loudly."""
    broken = sessions.with_columns(pl.lit("TIME_TRAVELLER").alias("persona_name"))

    with pytest.raises(KeyError, match="Supported personas"):
        generate_category_views(config, broken, category_catalog, SEED)
