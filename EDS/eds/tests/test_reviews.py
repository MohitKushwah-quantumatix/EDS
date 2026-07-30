"""Tests for the review generator."""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import pytest

from eds.config import (
    DEFAULT_RATING_WEIGHTS,
    DEFAULT_REVIEW_TEXTS,
    DEFAULT_REVIEW_TITLES,
    ConfigError,
    PlatformConfig,
    ReviewConfig,
    SimulationConfig,
    load_config,
    load_review_config,
)
from eds.domain.commerce.enums import ShipmentStatus
from eds.domain.commerce.schema import (
    RETURN_DATASETS,
    REVIEW_DATASETS,
    SHIPMENT_DATASETS,
    review_dataset_by_name,
    review_dataset_names,
)
from eds.generators.commerce.review_generator import (
    eligible_items,
    generate_reviews,
    iter_review_batches,
)
from eds.generators.commerce.reviews import (
    REQUIRED_REVIEW_DATASETS,
    ReviewData,
    generate_review_data,
)
from eds.validation.review_validation import REVIEW_NUMBER_PATTERN, validate_review_data

SEED = 4242

#: How many times the shipment fixture is repeated to measure a distribution.
REPLICATION_FACTOR = 40

EXPECTED_OUTPUTS = {"reviews"}


@pytest.fixture
def config() -> ReviewConfig:
    """Return a review configuration with a small batch size."""
    return ReviewConfig(review_rate=0.70, batch_size=25)


@pytest.fixture
def reviews(review_data: ReviewData) -> pl.DataFrame:
    """Return the generated reviews frame."""
    return review_data["reviews"]


@pytest.fixture
def shipments(review_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the shipments frame."""
    return review_upstream["shipments"]


@pytest.fixture
def shipment_items(review_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the shipment items frame."""
    return review_upstream["shipment_items"]


@pytest.fixture
def return_items(review_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the return items frame."""
    return review_upstream["return_items"]


@pytest.fixture
def many_shipments(shipments: pl.DataFrame) -> pl.DataFrame:
    """Return the shipments repeated enough times to measure a distribution."""
    copies = [
        shipments.with_columns(
            (pl.col("shipment_id") + index * shipments.height).alias("shipment_id")
        )
        for index in range(REPLICATION_FACTOR)
    ]
    return pl.concat(copies, how="vertical")


@pytest.fixture
def many_shipment_items(shipment_items: pl.DataFrame, shipments: pl.DataFrame) -> pl.DataFrame:
    """Return shipment items aligned with :func:`many_shipments`."""
    copies = [
        shipment_items.with_columns(
            (pl.col("shipment_id") + index * shipments.height).alias("shipment_id"),
            (pl.col("shipment_item_id") + index * shipment_items.height).alias("shipment_item_id"),
        )
        for index in range(REPLICATION_FACTOR)
    ]
    return pl.concat(copies, how="vertical")


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_shipped_review_config_loads() -> None:
    """The committed reviews.yaml matches the documented defaults."""
    config = load_review_config()

    assert config.review_rate == pytest.approx(0.18)
    assert config.rating_weights[5] == pytest.approx(0.40)
    assert config.rating_weights[1] == pytest.approx(0.05)
    assert config.review_number_prefix == "REV"
    assert config.min_review_days == 1
    assert config.max_review_days == 30


def test_review_config_is_part_of_the_run_configuration() -> None:
    """`load_config` includes the reviews section."""
    assert load_config().reviews.review_rate == pytest.approx(0.18)


def test_shipped_config_offers_the_documented_wording() -> None:
    """Titles and bodies both come from the shipped file."""
    config = load_review_config()

    assert "Excellent Product" in config.titles[5]
    assert "Very Disappointed" in config.titles[1]
    assert "The product exceeded my expectations." in config.texts[5]
    assert "The product did not meet expectations." in config.texts[1]


def test_every_rating_has_wording() -> None:
    """A drawn rating always has something to say."""
    config = load_review_config()

    for rating in config.rating_weights:
        assert config.titles[rating], rating
        assert config.texts[rating], rating


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("review_rate", 1.5),
        ("review_rate", -0.1),
        ("min_review_days", -1),
        ("batch_size", 0),
    ],
)
def test_out_of_range_review_values_are_rejected(field: str, value: float) -> None:
    """Settings outside their declared bounds fail validation."""
    with pytest.raises(ValueError, match=field):
        ReviewConfig(**{field: value})  # type: ignore[arg-type]


def test_rating_weights_must_total_one() -> None:
    """Every review gets exactly one rating."""
    with pytest.raises(ValueError, match="must sum to 1.0"):
        ReviewConfig(rating_weights={5: 0.5, 4: 0.2})


def test_an_empty_rating_table_is_rejected() -> None:
    """A review with no rating to draw is a configuration error."""
    with pytest.raises(ValueError, match="at least one rating"):
        ReviewConfig(rating_weights={})


def test_a_rating_outside_one_to_five_is_rejected() -> None:
    """Stars run from one to five."""
    with pytest.raises(ValueError, match="outside the 1-5 star range"):
        ReviewConfig(
            rating_weights={6: 1.0},
            titles={6: ("Six stars",)},
            texts={6: ("Beyond excellent.",)},
        )


def test_a_negative_rating_share_is_rejected() -> None:
    """A share below zero is meaningless."""
    with pytest.raises(ValueError, match="cannot be negative"):
        ReviewConfig(rating_weights={5: 1.5, 4: -0.5})


@pytest.mark.parametrize("table", ["titles", "texts"])
def test_wording_must_cover_every_rating(table: str) -> None:
    """A rating with nothing to say cannot be generated."""
    with pytest.raises(ValueError, match="must cover every rating"):
        ReviewConfig(**{table: {5: ("Only five stars",)}})  # type: ignore[arg-type]


@pytest.mark.parametrize("table", ["titles", "texts"])
def test_an_empty_phrase_list_is_rejected(table: str) -> None:
    """A rating must offer at least one phrase."""
    empty = dict.fromkeys(DEFAULT_RATING_WEIGHTS, ())
    with pytest.raises(ValueError, match="at least one phrase"):
        ReviewConfig(**{table: empty})  # type: ignore[arg-type]


def test_inverted_delay_range_is_rejected() -> None:
    """A minimum above its maximum is a configuration error."""
    with pytest.raises(ValueError, match="cannot exceed"):
        ReviewConfig(min_review_days=40, max_review_days=5)


def test_unknown_review_key_is_rejected() -> None:
    """A misspelled key is an error, not a silent no-op."""
    with pytest.raises(ValueError, match="reviews_rate"):
        ReviewConfig(reviews_rate=0.5)  # type: ignore[call-arg]


def test_invalid_review_config_file_raises(tmp_path: Path) -> None:
    """An out-of-range value names the offending file."""
    (tmp_path / "reviews.yaml").write_text("review_rate: 5.0\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="reviews.yaml"):
        load_review_config(tmp_path)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_registry_lists_the_single_documented_output() -> None:
    """F010 declares exactly one output dataset."""
    assert len(REVIEW_DATASETS) == 1
    assert set(review_dataset_names()) == EXPECTED_OUTPUTS


def test_earlier_registries_are_unchanged() -> None:
    """Adding reviews did not disturb the F008 or F009 registries."""
    assert {dataset.name for dataset in SHIPMENT_DATASETS} == {
        "shipments",
        "shipment_items",
        "shipment_status_history",
    }
    assert {dataset.name for dataset in RETURN_DATASETS} == {
        "returns",
        "return_items",
        "return_status_history",
    }


def test_dataset_file_name_matches_the_specification() -> None:
    """The dataset maps to the documented Parquet file name."""
    assert review_dataset_by_name("reviews").file_name == "reviews.parquet"


def test_unknown_review_dataset_lookup_raises() -> None:
    """Looking up an unregistered dataset fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown review dataset"):
        review_dataset_by_name("review_votes")


def test_reviews_have_no_status_history() -> None:
    """A review is written once: there is no lifecycle to record."""
    assert "review_status_history" not in review_dataset_names()
    assert "current_status" not in review_dataset_by_name("reviews").column_names


# --------------------------------------------------------------------------
# Eligibility
# --------------------------------------------------------------------------


def test_reviews_come_only_from_delivered_shipments(
    reviews: pl.DataFrame, shipments: pl.DataFrame
) -> None:
    """A parcel still travelling has not been seen, so nothing is reviewed."""
    delivered = set(
        shipments.filter(pl.col("current_status") == str(ShipmentStatus.DELIVERED))[
            "shipment_id"
        ].to_list()
    )

    assert set(reviews["shipment_id"].to_list()) <= delivered


def test_undelivered_shipments_produce_no_review(
    reviews: pl.DataFrame, shipments: pl.DataFrame
) -> None:
    """Only delivery makes an item reviewable."""
    undelivered = set(
        shipments.filter(pl.col("current_status") != str(ShipmentStatus.DELIVERED))[
            "shipment_id"
        ].to_list()
    )

    assert not (set(reviews["shipment_id"].to_list()) & undelivered)
    assert undelivered, "the sample should contain undelivered shipments"


def test_returned_items_never_generate_reviews(
    reviews: pl.DataFrame, return_items: pl.DataFrame
) -> None:
    """An item the customer sent back is no longer theirs to comment on."""
    returned = set(return_items["shipment_item_id"].to_list())

    assert returned, "the sample should contain returned items"
    assert not (set(reviews["shipment_item_id"].to_list()) & returned)


def test_eligibility_excludes_both_undelivered_and_returned(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_items: pl.DataFrame
) -> None:
    """Both halves of the rule are applied, not just one."""
    eligible = eligible_items(shipments, shipment_items, return_items)
    delivered = set(
        shipments.filter(pl.col("current_status") == str(ShipmentStatus.DELIVERED))[
            "shipment_id"
        ].to_list()
    )
    returned = set(return_items["shipment_item_id"].to_list())

    assert set(eligible["shipment_id"].to_list()) <= delivered
    assert not (set(eligible["shipment_item_id"].to_list()) & returned)


def test_an_item_is_reviewed_at_most_once(reviews: pl.DataFrame) -> None:
    """Review edits are out of scope, so there is never a second one."""
    assert reviews["shipment_item_id"].n_unique() == reviews.height


def test_review_ids_are_unique_and_sequential(reviews: pl.DataFrame) -> None:
    """Review ids form a dense sequence starting at one."""
    assert reviews["review_id"].to_list() == list(range(1, reviews.height + 1))


def test_the_review_rate_is_configurable(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_items: pl.DataFrame
) -> None:
    """A rate of zero reviews nothing; a rate of one reviews everything."""
    eligible = eligible_items(shipments, shipment_items, return_items).height

    none = generate_reviews(
        ReviewConfig(review_rate=0.0), shipments, shipment_items, return_items, SEED
    )
    every = generate_reviews(
        ReviewConfig(review_rate=1.0), shipments, shipment_items, return_items, SEED
    )

    assert none.height == 0
    assert every.height == eligible


def test_the_review_rate_is_approximately_honoured(
    many_shipments: pl.DataFrame,
    many_shipment_items: pl.DataFrame,
    return_items: pl.DataFrame,
) -> None:
    """Roughly the configured share of eligible items is reviewed."""
    settings = ReviewConfig(review_rate=0.18)
    eligible = eligible_items(many_shipments, many_shipment_items, return_items).height

    generated = generate_reviews(settings, many_shipments, many_shipment_items, return_items, SEED)

    assert eligible >= 500, "the replicated sample should be large enough to read"
    assert generated.height / eligible == pytest.approx(0.18, abs=0.03)


# --------------------------------------------------------------------------
# Lineage
# --------------------------------------------------------------------------


def test_the_product_comes_from_the_shipment_item(
    reviews: pl.DataFrame, shipment_items: pl.DataFrame
) -> None:
    """ADR-008: the shipment item is the review's single parent."""
    joined = reviews.join(shipment_items, on="shipment_item_id", how="inner", suffix="_item")

    assert joined.height == reviews.height
    assert joined.filter(pl.col("product_id") != pl.col("product_id_item")).height == 0
    assert joined.filter(pl.col("shipment_id") != pl.col("shipment_id_item")).height == 0


def test_the_order_and_customer_come_from_the_shipment(
    reviews: pl.DataFrame, shipments: pl.DataFrame
) -> None:
    """Everything else is copied down the parent chain."""
    joined = reviews.join(shipments, on="shipment_id", how="inner", suffix="_shp")

    assert joined.height == reviews.height
    for column in ("order_id", "customer_id"):
        assert joined.filter(pl.col(column) != pl.col(f"{column}_shp")).height == 0, column


# --------------------------------------------------------------------------
# Rating and wording
# --------------------------------------------------------------------------


def test_every_rating_is_in_range(reviews: pl.DataFrame) -> None:
    """Stars run from one to five."""
    assert reviews.filter((pl.col("rating") < 1) | (pl.col("rating") > 5)).height == 0


def test_verified_purchase_is_always_true(reviews: pl.DataFrame) -> None:
    """Every review comes from a delivered shipment."""
    assert reviews["verified_purchase"].all()
    assert reviews["verified_purchase"].null_count() == 0


def test_wording_matches_the_rating_it_sits_beside(reviews: pl.DataFrame) -> None:
    """A three-star review never carries five-star wording."""
    for row in reviews.select("rating", "review_title", "review_text").unique().to_dicts():
        assert row["review_title"] in DEFAULT_REVIEW_TITLES[row["rating"]], row
        assert row["review_text"] in DEFAULT_REVIEW_TEXTS[row["rating"]], row


def test_wording_is_never_empty(reviews: pl.DataFrame) -> None:
    """Every review says something."""
    assert reviews.filter(pl.col("review_title").str.len_chars() == 0).height == 0
    assert reviews.filter(pl.col("review_text").str.len_chars() == 0).height == 0


def test_review_text_is_one_sentence(reviews: pl.DataFrame) -> None:
    """The bodies are short fixed phrases, not generated paragraphs."""
    for text in reviews["review_text"].unique().to_list():
        assert text.count(".") == 1, text
        assert text.endswith("."), text
        assert len(text) < 120, text


def test_configured_wording_reaches_the_data(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_items: pl.DataFrame
) -> None:
    """Titles and bodies are read from configuration, never hardcoded."""
    settings = ReviewConfig(
        review_rate=0.70,
        rating_weights={5: 1.0},
        titles={5: ("Custom Title",)},
        texts={5: ("A custom sentence.",)},
    )

    generated = generate_reviews(settings, shipments, shipment_items, return_items, SEED)

    assert generated["review_title"].unique().to_list() == ["Custom Title"]
    assert generated["review_text"].unique().to_list() == ["A custom sentence."]


def test_a_single_rating_configuration_yields_only_that_rating(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_items: pl.DataFrame
) -> None:
    """The rating draw honours the configured weights."""
    settings = ReviewConfig(
        review_rate=0.70,
        rating_weights={2: 1.0},
        titles={2: ("Could Be Better",)},
        texts={2: ("The product is not quite what I expected.",)},
    )

    generated = generate_reviews(settings, shipments, shipment_items, return_items, SEED)

    assert generated["rating"].unique().to_list() == [2]


def test_rating_distribution_is_approximately_as_specified(
    many_shipments: pl.DataFrame,
    many_shipment_items: pl.DataFrame,
    return_items: pl.DataFrame,
) -> None:
    """Roughly 40 / 30 / 15 / 10 / 5 per cent across five stars down to one."""
    settings = ReviewConfig(review_rate=1.0)
    generated = generate_reviews(settings, many_shipments, many_shipment_items, return_items, SEED)

    total = generated.height
    share = {
        row["rating"]: row["count"] / total for row in generated["rating"].value_counts().to_dicts()
    }

    assert total >= 500, "the replicated sample should be large enough to read"
    for rating, expected in DEFAULT_RATING_WEIGHTS.items():
        assert share.get(rating, 0.0) == pytest.approx(expected, abs=0.04), rating


# --------------------------------------------------------------------------
# Review numbers
# --------------------------------------------------------------------------


def test_review_numbers_are_unique(reviews: pl.DataFrame) -> None:
    """The business identifier is never reused."""
    assert reviews["review_number"].n_unique() == reviews.height


def test_review_numbers_match_the_documented_format(reviews: pl.DataFrame) -> None:
    """Every number reads as PREFIX-YYYYMMDD-NNNNNN."""
    pattern = re.compile(REVIEW_NUMBER_PATTERN)

    for number in reviews["review_number"].to_list():
        assert pattern.match(number), number


def test_review_number_embeds_its_own_date(reviews: pl.DataFrame) -> None:
    """The date inside the number is the day the review was written."""
    mismatched = reviews.filter(
        pl.col("review_number").str.slice(-15, 8) != pl.col("created_at").dt.strftime("%Y%m%d")
    )

    assert mismatched.height == 0


def test_review_numbers_are_sequential_within_a_date(reviews: pl.DataFrame) -> None:
    """The sequence restarts each day and runs 1..n without gaps."""
    numbered = (
        reviews.with_columns(pl.col("created_at").dt.date().alias("day"))
        .group_by("day")
        .agg(
            pl.col("review_number").str.slice(-6).cast(pl.Int64).min().alias("lowest"),
            pl.col("review_number").str.slice(-6).cast(pl.Int64).max().alias("highest"),
            pl.len().alias("total"),
        )
    )

    assert numbered.filter(pl.col("lowest") != 1).height == 0
    assert numbered.filter(pl.col("highest") != pl.col("total")).height == 0


def test_the_prefix_is_configurable(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_items: pl.DataFrame
) -> None:
    """A different prefix changes every number."""
    settings = ReviewConfig(review_rate=0.70, review_number_prefix="RVW")

    custom = generate_reviews(settings, shipments, shipment_items, return_items, SEED)

    assert all(number.startswith("RVW-") for number in custom["review_number"].to_list())


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


def test_reviews_are_written_after_delivery(reviews: pl.DataFrame, shipments: pl.DataFrame) -> None:
    """created_at must be after shipment.delivered_at."""
    joined = reviews.join(
        shipments.select("shipment_id", pl.col("delivered_at").alias("arrived_at")),
        on="shipment_id",
    )

    assert joined.filter(pl.col("created_at") < pl.col("arrived_at")).height == 0


def test_review_delays_stay_inside_the_configured_window(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_items: pl.DataFrame
) -> None:
    """Every review falls in the configured day range after delivery."""
    settings = ReviewConfig(review_rate=1.0, min_review_days=4, max_review_days=9)

    generated = generate_reviews(settings, shipments, shipment_items, return_items, SEED).join(
        shipments.select("shipment_id", "delivered_at"), on="shipment_id"
    )
    measured = generated.with_columns(
        (pl.col("created_at") - pl.col("delivered_at")).dt.total_days().alias("days")
    )

    assert measured.height > 0
    assert measured.filter((pl.col("days") < 4) | (pl.col("days") > 9)).height == 0


# --------------------------------------------------------------------------
# Orchestration, batching and determinism
# --------------------------------------------------------------------------


def test_all_documented_datasets_are_generated(review_data: ReviewData) -> None:
    """Every dataset named in the F010 output list is produced."""
    assert set(review_data.datasets) == EXPECTED_OUTPUTS


def test_the_dataset_is_not_empty(review_data: ReviewData) -> None:
    """The review dataset carries rows."""
    assert all(count > 0 for count in review_data.row_counts().values())


def test_generated_data_passes_validation(
    review_data: ReviewData, review_upstream: dict[str, pl.DataFrame]
) -> None:
    """The bundle satisfies the F010 acceptance criteria."""
    issues = validate_review_data(
        {**review_upstream, **review_data.datasets},
        DEFAULT_REVIEW_TITLES,
        DEFAULT_REVIEW_TEXTS,
    )

    assert issues == []


def test_batching_does_not_change_the_output(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_items: pl.DataFrame
) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = ReviewConfig(review_rate=0.70, batch_size=7)
    large = ReviewConfig(review_rate=0.70, batch_size=1_000_000)

    assert generate_reviews(small, shipments, shipment_items, return_items, SEED).equals(
        generate_reviews(large, shipments, shipment_items, return_items, SEED)
    )


def test_batches_are_bounded_by_the_configured_size(
    shipments: pl.DataFrame, shipment_items: pl.DataFrame, return_items: pl.DataFrame
) -> None:
    """No batch exceeds the configured size."""
    settings = ReviewConfig(review_rate=1.0, batch_size=10)

    batches = list(iter_review_batches(settings, shipments, shipment_items, return_items, SEED))

    assert batches
    assert all(batch.height <= 10 for batch in batches)


def test_generation_is_deterministic(
    review_simulation_config: SimulationConfig, review_upstream: dict[str, pl.DataFrame]
) -> None:
    """The same configuration and seed reproduce identical datasets."""
    first = generate_review_data(review_simulation_config, review_upstream)
    second = generate_review_data(review_simulation_config, review_upstream)

    assert first.seed == second.seed
    for name, frame in first:
        assert frame.equals(second[name]), f"{name} differs between runs"


def test_a_different_seed_changes_the_reviews(
    review_simulation_config: SimulationConfig, review_upstream: dict[str, pl.DataFrame]
) -> None:
    """The seed drives who reviews, how they rate it, and what they say."""
    other = SimulationConfig(
        platform=PlatformConfig(seed=97_531),
        master_data=review_simulation_config.master_data,
        customers=review_simulation_config.customers,
        journey=review_simulation_config.journey,
        browsing=review_simulation_config.browsing,
        engagement=review_simulation_config.engagement,
        commerce=review_simulation_config.commerce,
        checkout=review_simulation_config.checkout,
        orders=review_simulation_config.orders,
        payments=review_simulation_config.payments,
        shipments=review_simulation_config.shipments,
        returns=review_simulation_config.returns,
        reviews=review_simulation_config.reviews,
    )

    baseline = generate_review_data(review_simulation_config, review_upstream)
    varied = generate_review_data(other, review_upstream)

    assert not baseline["reviews"].equals(varied["reviews"])


@pytest.mark.parametrize("missing", REQUIRED_REVIEW_DATASETS)
def test_missing_upstream_data_is_reported(
    review_simulation_config: SimulationConfig,
    review_upstream: dict[str, pl.DataFrame],
    missing: str,
) -> None:
    """Each required upstream dataset is checked before generation starts."""
    available = {name: frame for name, frame in review_upstream.items() if name != missing}

    with pytest.raises(KeyError, match="Missing upstream data"):
        generate_review_data(review_simulation_config, available)


def test_missing_upstream_names_the_prerequisite_commands(
    review_simulation_config: SimulationConfig,
    review_upstream: dict[str, pl.DataFrame],
) -> None:
    """The error tells the user which commands to run first."""
    available = {name: frame for name, frame in review_upstream.items() if name != "shipment_items"}

    with pytest.raises(KeyError, match="generate commerce"):
        generate_review_data(review_simulation_config, available)


def test_no_delivered_shipments_produces_an_empty_frame(
    config: ReviewConfig,
    shipments: pl.DataFrame,
    shipment_items: pl.DataFrame,
    return_items: pl.DataFrame,
) -> None:
    """A run where nothing arrived yields an empty, schema-shaped frame."""
    none_delivered = shipments.with_columns(
        pl.lit(str(ShipmentStatus.IN_TRANSIT)).alias("current_status")
    )

    generated = generate_reviews(config, none_delivered, shipment_items, return_items, SEED)

    assert generated.height == 0
    assert "review_id" in generated.columns


def test_everything_returned_produces_an_empty_frame(
    config: ReviewConfig, shipments: pl.DataFrame, shipment_items: pl.DataFrame
) -> None:
    """If every item came back, nobody is left to review anything."""
    everything = shipment_items.select("shipment_item_id")

    generated = generate_reviews(config, shipments, shipment_items, everything, SEED)

    assert generated.height == 0
    assert "review_id" in generated.columns


def test_bundle_reports_row_counts(review_data: ReviewData) -> None:
    """The bundle exposes counts for the CLI report."""
    assert review_data.total_rows() == sum(review_data.row_counts().values())


def test_unknown_dataset_access_raises(review_data: ReviewData) -> None:
    """Requesting a dataset F010 does not produce fails clearly."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        review_data["review_votes"]


def test_reviews_do_not_regenerate_upstream_data(
    review_data: ReviewData, review_upstream: dict[str, pl.DataFrame]
) -> None:
    """F010 consumes earlier output; it emits none of those datasets."""
    assert set(review_data.datasets).isdisjoint(set(review_upstream))
