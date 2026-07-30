"""Tests for the search generator, including category/search consistency."""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import BrowsingConfig
from eds.domain.journey.enums import PersonaName
from eds.domain.journey.schema import SEARCH_HISTORY
from eds.generators.journey.browsing import BrowsingData
from eds.generators.journey.category_generator import CategoryCatalog
from eds.generators.journey.journey import JourneyData
from eds.generators.journey.search_generator import (
    CATEGORY_SEARCH_TERMS,
    PERSONA_SEARCH_RANGES,
    generate_searches,
    search_terms_for_root,
)
from eds.generators.master_data import MasterData

SEED = 3131
MAX_SEARCH_WORDS = 4


@pytest.fixture
def sessions(journey_data: JourneyData) -> pl.DataFrame:
    """Return the generated sessions frame."""
    return journey_data["sessions"]


@pytest.fixture
def views(browsing_data: BrowsingData) -> pl.DataFrame:
    """Return the generated category views frame."""
    return browsing_data["category_views"]


@pytest.fixture
def searches(browsing_data: BrowsingData) -> pl.DataFrame:
    """Return the generated search history frame."""
    return browsing_data["search_history"]


@pytest.fixture
def config() -> BrowsingConfig:
    """Return a browsing configuration with a small batch size."""
    return BrowsingConfig(batch_size=400)


def test_specified_vocabularies_are_present() -> None:
    """The five vocabularies named in the specification are included."""
    assert "Gaming Laptop" in CATEGORY_SEARCH_TERMS["Electronics"]
    assert "Office Chair" in CATEGORY_SEARCH_TERMS["Furniture"]
    assert "Running Shoes" in CATEGORY_SEARCH_TERMS["Clothing"]
    assert "Coffee Machine" in CATEGORY_SEARCH_TERMS["Home & Kitchen"]
    assert "Cricket Bat" in CATEGORY_SEARCH_TERMS["Sports & Outdoors"]


def test_every_master_data_root_has_a_vocabulary(master_data: MasterData) -> None:
    """Every browsable top-level category can produce a relevant search."""
    roots = set(master_data["categories"].filter(pl.col("level") == 1)["category_name"].to_list())

    assert roots <= set(CATEGORY_SEARCH_TERMS)


def test_vocabularies_do_not_leak_across_categories() -> None:
    """A furniture phrase never appears in the electronics vocabulary."""
    assert "Coffee Table" not in CATEGORY_SEARCH_TERMS["Electronics"]
    assert "Gaming Laptop" not in CATEGORY_SEARCH_TERMS["Furniture"]


def test_unknown_root_falls_back_to_generic_terms() -> None:
    """A category without a vocabulary still gets product-oriented phrases."""
    terms = search_terms_for_root("Nonexistent Category")

    assert terms
    assert all(1 <= len(term.split()) <= MAX_SEARCH_WORDS for term in terms)


def test_every_vocabulary_phrase_is_short() -> None:
    """Phrases stay within the one-to-four word rule before qualifiers."""
    for root, terms in CATEGORY_SEARCH_TERMS.items():
        for term in terms:
            assert 1 <= len(term.split()) <= 3, f"{root}: {term}"


def test_persona_search_ranges_cover_every_persona() -> None:
    """All six personas have a search range."""
    assert set(PERSONA_SEARCH_RANGES) == {str(member) for member in PersonaName}


def test_search_ids_are_unique_and_sequential(searches: pl.DataFrame) -> None:
    """Search ids form a dense sequence starting at one."""
    assert searches["search_id"].to_list() == list(range(1, searches.height + 1))


def test_search_counts_stay_within_the_configured_bounds(
    searches: pl.DataFrame, config: BrowsingConfig
) -> None:
    """No session exceeds ten searches."""
    counts = searches.group_by("session_id").len()["len"].to_list()

    assert max(counts) <= config.max_searches


def test_average_search_count_is_approximately_two(
    searches: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """The documented average of roughly two searches per session holds."""
    assert searches.height / sessions.height == pytest.approx(2.0, abs=1.0)


def test_some_sessions_perform_no_searches(searches: pl.DataFrame, sessions: pl.DataFrame) -> None:
    """Zero searches is a valid outcome, as the minimum allows."""
    assert searches["session_id"].n_unique() < sessions.height


def test_bounce_sessions_never_search(searches: pl.DataFrame, sessions: pl.DataFrame) -> None:
    """A session that viewed one page and left did not search."""
    bounced = set(sessions.filter(pl.col("bounce"))["session_id"].to_list())

    assert not (set(searches["session_id"].to_list()) & bounced)


def test_search_sequences_start_at_one_and_are_contiguous(
    searches: pl.DataFrame,
) -> None:
    """Sequence numbering restarts per session without gaps."""
    grouped = searches.group_by("session_id").agg(
        pl.col("search_sequence").min().alias("lowest"),
        pl.col("search_sequence").max().alias("highest"),
        pl.len().alias("total"),
    )

    assert grouped.filter(pl.col("lowest") != 1).height == 0
    assert grouped.filter(pl.col("highest") != pl.col("total")).height == 0


def test_search_category_matches_its_category_view(
    searches: pl.DataFrame, views: pl.DataFrame
) -> None:
    """A search is always about the category being viewed."""
    joined = searches.join(
        views.select("category_view_id", pl.col("category_id").alias("view_category_id")),
        on="category_view_id",
        how="inner",
    )

    assert joined.height == searches.height
    assert joined.filter(pl.col("category_id") != pl.col("view_category_id")).height == 0


def test_search_text_comes_from_its_category_vocabulary(
    searches: pl.DataFrame, category_catalog: CategoryCatalog
) -> None:
    """No search drifts to an unrelated category's vocabulary."""
    for category_id, text in zip(
        searches["category_id"].to_list(), searches["search_text"].to_list(), strict=True
    ):
        vocabulary = search_terms_for_root(category_catalog.root_of(category_id))
        assert any(text == term or text.endswith(f" {term}") for term in vocabulary), text


def test_search_text_is_one_to_four_words(searches: pl.DataFrame) -> None:
    """Phrases stay within the documented length."""
    lengths = [len(text.split()) for text in searches["search_text"].to_list()]

    assert min(lengths) >= 1
    assert max(lengths) <= MAX_SEARCH_WORDS


def test_search_text_is_never_empty(searches: pl.DataFrame) -> None:
    """Every search carries text."""
    assert searches.filter(pl.col("search_text").str.len_chars() == 0).height == 0


def test_searches_occur_after_the_first_category_view(
    searches: pl.DataFrame, views: pl.DataFrame
) -> None:
    """Nothing is searched before the customer has seen a category."""
    first = views.group_by("session_id").agg(pl.col("timestamp").min().alias("first_view"))
    joined = searches.join(first, on="session_id", how="inner")

    assert joined.filter(pl.col("timestamp") <= pl.col("first_view")).height == 0


def test_searches_fall_inside_their_session(searches: pl.DataFrame, sessions: pl.DataFrame) -> None:
    """A search never happens outside the session it belongs to."""
    joined = searches.join(sessions.select("session_id", "start_time", "end_time"), on="session_id")

    assert joined.filter(pl.col("timestamp") < pl.col("start_time")).height == 0
    assert joined.filter(pl.col("timestamp") > pl.col("end_time")).height == 0


def test_searches_fall_inside_their_category_view(
    searches: pl.DataFrame, views: pl.DataFrame
) -> None:
    """A search happens while the customer is on that category page."""
    joined = searches.join(
        views.select(
            "category_view_id",
            pl.col("timestamp").alias("view_start"),
            "duration_seconds",
        ),
        on="category_view_id",
        how="inner",
    )

    assert joined.filter(pl.col("timestamp") <= pl.col("view_start")).height == 0
    assert (
        joined.filter(
            pl.col("timestamp")
            > pl.col("view_start") + pl.duration(seconds=pl.col("duration_seconds"))
        ).height
        == 0
    )


def test_results_counts_stay_within_range(searches: pl.DataFrame, config: BrowsingConfig) -> None:
    """Result counts sit between zero and the configured ceiling."""
    counts = searches["results_count"].to_list()

    assert min(counts) >= 0
    assert max(counts) <= config.max_results_count


def test_a_search_with_no_results_is_never_clicked(searches: pl.DataFrame) -> None:
    """A customer cannot click a result that does not exist."""
    assert searches.filter(pl.col("clicked_result") & (pl.col("results_count") == 0)).height == 0


def test_some_searches_return_nothing(searches: pl.DataFrame) -> None:
    """The no-results path is exercised."""
    assert searches.filter(pl.col("results_count") == 0).height > 0


def test_bargain_hunters_search_more_than_impulse_buyers(
    searches: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """Persona search ranges are reflected in the generated data."""
    joined = searches.join(sessions.select("session_id", "persona_name"), on="session_id")
    counts = joined.group_by("session_id", "persona_name").len()

    bargain = counts.filter(pl.col("persona_name") == str(PersonaName.BARGAIN_HUNTER))
    impulse = counts.filter(pl.col("persona_name") == str(PersonaName.IMPULSE_BUYER))

    bargain_mean = sum(bargain["len"].to_list()) / bargain.height
    impulse_mean = sum(impulse["len"].to_list()) / impulse.height

    assert bargain_mean > impulse_mean


def test_searches_reference_the_session_customer(
    searches: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """A search's customer matches the customer who owned the session."""
    joined = searches.join(
        sessions.select("session_id", pl.col("customer_id").alias("session_customer")),
        on="session_id",
    )

    assert joined.filter(pl.col("customer_id") != pl.col("session_customer")).height == 0


def test_batching_does_not_change_the_output(
    sessions: pl.DataFrame, views: pl.DataFrame, category_catalog: CategoryCatalog
) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = generate_searches(
        BrowsingConfig(batch_size=29), sessions, views, category_catalog, SEED
    )
    large = generate_searches(
        BrowsingConfig(batch_size=1_000_000), sessions, views, category_catalog, SEED
    )

    assert small.equals(large)


def test_generation_is_deterministic(
    config: BrowsingConfig,
    sessions: pl.DataFrame,
    views: pl.DataFrame,
    category_catalog: CategoryCatalog,
) -> None:
    """The same seed reproduces the same searches."""
    assert generate_searches(config, sessions, views, category_catalog, SEED).equals(
        generate_searches(config, sessions, views, category_catalog, SEED)
    )


def test_generation_varies_with_the_seed(
    config: BrowsingConfig,
    sessions: pl.DataFrame,
    views: pl.DataFrame,
    category_catalog: CategoryCatalog,
) -> None:
    """A different seed produces different searches."""
    assert not generate_searches(config, sessions, views, category_catalog, 1).equals(
        generate_searches(config, sessions, views, category_catalog, 2)
    )


def test_zero_maximum_searches_produces_none(
    sessions: pl.DataFrame, views: pl.DataFrame, category_catalog: CategoryCatalog
) -> None:
    """Configuring no searches yields an empty, schema-shaped frame."""
    config = BrowsingConfig(min_searches=0, max_searches=0)

    result = generate_searches(config, sessions, views, category_catalog, SEED)

    assert result.height == 0
    assert result.columns == list(SEARCH_HISTORY.column_names)
