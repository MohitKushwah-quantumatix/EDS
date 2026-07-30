"""Tests for the engagement orchestrator and its configuration."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from eds.config import (
    ConfigError,
    EngagementConfig,
    PlatformConfig,
    SimulationConfig,
    load_config,
    load_engagement_config,
)
from eds.domain.journey.schema import (
    BROWSING_DATASETS,
    ENGAGEMENT_DATASETS,
    JOURNEY_DATASETS,
    engagement_dataset_by_name,
    engagement_dataset_names,
)
from eds.generators.journey.engagement import (
    REQUIRED_ENGAGEMENT_DATASETS,
    EngagementData,
    generate_engagement_data,
)
from eds.validation.engagement_validation import validate_engagement_data

EXPECTED_OUTPUTS = {"product_views", "wishlists"}


def test_shipped_engagement_config_loads() -> None:
    """The committed engagement.yaml matches the documented defaults."""
    config = load_engagement_config()

    assert config.min_product_views == 1
    assert config.max_product_views == 8
    assert config.min_view_seconds == 5
    assert config.max_view_seconds == 600


def test_engagement_config_is_part_of_the_run_configuration() -> None:
    """`load_config` includes the engagement section."""
    assert load_config().engagement.max_product_views == 8


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_product_views", 0),
        ("min_view_seconds", 0),
        ("wishlist_view_rate", 1.5),
        ("wishlist_view_rate", -0.1),
        ("batch_size", 0),
    ],
)
def test_out_of_range_engagement_values_are_rejected(field: str, value: float) -> None:
    """Settings outside their declared bounds fail validation."""
    with pytest.raises(ValueError, match=field):
        EngagementConfig(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("low_field", "high_field", "low", "high"),
    [
        ("min_product_views", "max_product_views", 6, 2),
        ("min_view_seconds", "max_view_seconds", 400, 30),
    ],
)
def test_inverted_ranges_are_rejected(low_field: str, high_field: str, low: int, high: int) -> None:
    """A minimum above its maximum is a configuration error."""
    with pytest.raises(ValueError, match="cannot exceed"):
        EngagementConfig(**{low_field: low, high_field: high})


def test_unknown_engagement_key_is_rejected() -> None:
    """A misspelled key is an error, not a silent no-op."""
    with pytest.raises(ValueError, match="wishlist_rate"):
        EngagementConfig(wishlist_rate=0.2)  # type: ignore[call-arg]


def test_invalid_engagement_config_file_raises(tmp_path: Path) -> None:
    """An out-of-range value names the offending file."""
    (tmp_path / "engagement.yaml").write_text("wishlist_view_rate: 3.0\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="engagement.yaml"):
        load_engagement_config(tmp_path)


def test_registry_lists_the_two_documented_outputs() -> None:
    """F003.3 declares exactly two output datasets."""
    assert len(ENGAGEMENT_DATASETS) == 2
    assert set(engagement_dataset_names()) == EXPECTED_OUTPUTS


def test_earlier_registries_are_unchanged() -> None:
    """F003.1 and F003.2 still declare only their own datasets."""
    assert {dataset.name for dataset in JOURNEY_DATASETS} == {
        "customer_personas",
        "sessions",
    }
    assert {dataset.name for dataset in BROWSING_DATASETS} == {
        "category_views",
        "search_history",
    }


def test_dataset_file_names_match_the_specification() -> None:
    """Each dataset maps to the documented Parquet file name."""
    assert engagement_dataset_by_name("product_views").file_name == "product_views.parquet"
    assert engagement_dataset_by_name("wishlists").file_name == "wishlists.parquet"


def test_unknown_engagement_dataset_lookup_raises() -> None:
    """Looking up an unregistered dataset fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown engagement dataset"):
        engagement_dataset_by_name("carts")


def test_all_documented_datasets_are_generated(engagement_data: EngagementData) -> None:
    """Every dataset named in the F003.3 output list is produced."""
    assert set(engagement_data.datasets) == EXPECTED_OUTPUTS


def test_datasets_are_emitted_in_dependency_order(
    engagement_data: EngagementData,
) -> None:
    """Product views come first, so wishlists can reference them."""
    assert list(engagement_data.datasets) == [dataset.name for dataset in ENGAGEMENT_DATASETS]


def test_no_dataset_is_empty(engagement_data: EngagementData) -> None:
    """Both engagement datasets carry rows."""
    assert all(count > 0 for count in engagement_data.row_counts().values())


def test_generated_data_passes_validation(
    engagement_data: EngagementData,
    engagement_upstream: dict[str, pl.DataFrame],
    engagement_simulation_config: SimulationConfig,
) -> None:
    """The bundle satisfies the F003.3 acceptance criteria."""
    settings = engagement_simulation_config.engagement
    issues = validate_engagement_data(
        {**engagement_upstream, **engagement_data.datasets},
        settings.min_view_seconds,
        settings.max_view_seconds,
    )

    assert issues == []


def test_generation_is_deterministic(
    engagement_simulation_config: SimulationConfig,
    engagement_upstream: dict[str, pl.DataFrame],
) -> None:
    """The same configuration and seed reproduce identical datasets."""
    first = generate_engagement_data(engagement_simulation_config, engagement_upstream)
    second = generate_engagement_data(engagement_simulation_config, engagement_upstream)

    assert first.seed == second.seed
    for name, frame in first:
        assert frame.equals(second[name]), f"{name} differs between runs"


def test_a_different_seed_changes_the_data(
    engagement_simulation_config: SimulationConfig,
    engagement_upstream: dict[str, pl.DataFrame],
) -> None:
    """Changing the seed changes generated attributes."""
    other = SimulationConfig(
        platform=PlatformConfig(seed=24_680),
        master_data=engagement_simulation_config.master_data,
        customers=engagement_simulation_config.customers,
        journey=engagement_simulation_config.journey,
        browsing=engagement_simulation_config.browsing,
        engagement=engagement_simulation_config.engagement,
    )

    baseline = generate_engagement_data(engagement_simulation_config, engagement_upstream)
    varied = generate_engagement_data(other, engagement_upstream)

    assert not baseline["product_views"].equals(varied["product_views"])


def test_a_null_seed_still_reports_a_reproducible_seed(
    engagement_simulation_config: SimulationConfig,
    engagement_upstream: dict[str, pl.DataFrame],
) -> None:
    """A non-deterministic run reports the seed it actually used."""
    config = SimulationConfig(
        platform=PlatformConfig(seed=None),
        master_data=engagement_simulation_config.master_data,
        customers=engagement_simulation_config.customers,
        journey=engagement_simulation_config.journey,
        browsing=engagement_simulation_config.browsing,
        engagement=engagement_simulation_config.engagement,
    )

    generated = generate_engagement_data(config, engagement_upstream)
    replay = generate_engagement_data(
        SimulationConfig(
            platform=PlatformConfig(seed=generated.seed),
            master_data=config.master_data,
            customers=config.customers,
            journey=config.journey,
            browsing=config.browsing,
            engagement=config.engagement,
        ),
        engagement_upstream,
    )

    assert generated["product_views"].equals(replay["product_views"])


@pytest.mark.parametrize("missing", REQUIRED_ENGAGEMENT_DATASETS)
def test_missing_upstream_data_is_reported(
    engagement_simulation_config: SimulationConfig,
    engagement_upstream: dict[str, pl.DataFrame],
    missing: str,
) -> None:
    """Each required upstream dataset is checked before generation starts."""
    available = {name: frame for name, frame in engagement_upstream.items() if name != missing}

    with pytest.raises(KeyError, match="Missing upstream data"):
        generate_engagement_data(engagement_simulation_config, available)


def test_missing_upstream_names_the_prerequisite_commands(
    engagement_simulation_config: SimulationConfig,
    engagement_upstream: dict[str, pl.DataFrame],
) -> None:
    """The error tells the user which commands to run first."""
    available = {name: frame for name, frame in engagement_upstream.items() if name != "products"}

    with pytest.raises(KeyError, match="generate master-data"):
        generate_engagement_data(engagement_simulation_config, available)


def test_empty_products_stops_generation(
    engagement_simulation_config: SimulationConfig,
    engagement_upstream: dict[str, pl.DataFrame],
) -> None:
    """An empty products dataset is reported clearly."""
    available = dict(engagement_upstream)
    available["products"] = available["products"].clear()

    with pytest.raises(ValueError, match="products dataset is empty"):
        generate_engagement_data(engagement_simulation_config, available)


def test_total_rows_sums_every_dataset(engagement_data: EngagementData) -> None:
    """The reported total matches the sum of the parts."""
    assert engagement_data.total_rows() == sum(engagement_data.row_counts().values())


def test_bundle_iteration_yields_name_and_frame(
    engagement_data: EngagementData,
) -> None:
    """Iterating the bundle yields usable pairs."""
    for name, frame in engagement_data:
        assert isinstance(name, str)
        assert isinstance(frame, pl.DataFrame)


def test_unknown_dataset_access_raises(engagement_data: EngagementData) -> None:
    """Requesting a dataset F003.3 does not produce fails clearly."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        engagement_data["carts"]


def test_engagement_does_not_regenerate_upstream_data(
    engagement_data: EngagementData, engagement_upstream: dict[str, pl.DataFrame]
) -> None:
    """F003.3 consumes earlier output; it emits none of those datasets."""
    assert set(engagement_data.datasets).isdisjoint(set(engagement_upstream))
