"""Tests for the browsing orchestrator and its configuration."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from eds.config import (
    BrowsingConfig,
    ConfigError,
    PlatformConfig,
    SimulationConfig,
    load_browsing_config,
    load_config,
)
from eds.domain.journey.schema import (
    BROWSING_DATASETS,
    JOURNEY_DATASETS,
    browsing_dataset_by_name,
    browsing_dataset_names,
)
from eds.generators.journey.browsing import (
    REQUIRED_BROWSING_DATASETS,
    BrowsingData,
    generate_browsing_data,
)
from eds.validation.browsing_validation import validate_browsing_data

EXPECTED_OUTPUTS = {"category_views", "search_history"}


def test_shipped_browsing_config_loads() -> None:
    """The committed browsing.yaml is valid and matches the documented defaults."""
    config = load_browsing_config()

    assert config.min_category_views == 1
    assert config.max_category_views == 10
    assert config.min_view_seconds == 5
    assert config.max_view_seconds == 180
    assert config.max_searches == 10
    assert config.max_results_count == 250


def test_browsing_config_is_part_of_the_run_configuration() -> None:
    """`load_config` includes the browsing section."""
    assert load_config().browsing.max_category_views == 10


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_category_views", 0),
        ("min_view_seconds", 0),
        ("max_results_count", -1),
        ("no_results_rate", 1.5),
        ("click_through_rate", -0.1),
        ("batch_size", 0),
    ],
)
def test_out_of_range_browsing_values_are_rejected(field: str, value: float) -> None:
    """Settings outside their declared bounds fail validation."""
    with pytest.raises(ValueError, match=field):
        BrowsingConfig(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("low_field", "high_field", "low", "high"),
    [
        ("min_category_views", "max_category_views", 8, 4),
        ("min_view_seconds", "max_view_seconds", 200, 10),
        ("min_searches", "max_searches", 6, 2),
    ],
)
def test_inverted_ranges_are_rejected(low_field: str, high_field: str, low: int, high: int) -> None:
    """A minimum above its maximum is a configuration error."""
    with pytest.raises(ValueError, match="cannot exceed"):
        BrowsingConfig(**{low_field: low, high_field: high})


def test_unknown_browsing_key_is_rejected() -> None:
    """A misspelled key is an error, not a silent no-op."""
    with pytest.raises(ValueError, match="bounce_rate"):
        BrowsingConfig(bounce_rate=0.2)  # type: ignore[call-arg]


def test_invalid_browsing_config_file_raises(tmp_path: Path) -> None:
    """An out-of-range value names the offending file."""
    (tmp_path / "browsing.yaml").write_text("max_results_count: -5\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="browsing.yaml"):
        load_browsing_config(tmp_path)


def test_registry_lists_the_two_documented_outputs() -> None:
    """F003.2 declares exactly two output datasets."""
    assert len(BROWSING_DATASETS) == 2
    assert set(browsing_dataset_names()) == EXPECTED_OUTPUTS


def test_journey_registry_is_unchanged() -> None:
    """F003.1's registry still declares only its own two datasets."""
    assert {dataset.name for dataset in JOURNEY_DATASETS} == {
        "customer_personas",
        "sessions",
    }


def test_dataset_file_names_match_the_specification() -> None:
    """Each dataset maps to the documented Parquet file name."""
    assert browsing_dataset_by_name("category_views").file_name == "category_views.parquet"
    assert browsing_dataset_by_name("search_history").file_name == "search_history.parquet"


def test_unknown_browsing_dataset_lookup_raises() -> None:
    """Looking up an unregistered dataset fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown browsing dataset"):
        browsing_dataset_by_name("product_views")


def test_all_documented_datasets_are_generated(browsing_data: BrowsingData) -> None:
    """Every dataset named in the F003.2 output list is produced."""
    assert set(browsing_data.datasets) == EXPECTED_OUTPUTS


def test_datasets_are_emitted_in_dependency_order(browsing_data: BrowsingData) -> None:
    """Category views come first, so searches can reference them."""
    assert list(browsing_data.datasets) == [dataset.name for dataset in BROWSING_DATASETS]


def test_no_dataset_is_empty(browsing_data: BrowsingData) -> None:
    """Both browsing datasets carry rows."""
    assert all(count > 0 for count in browsing_data.row_counts().values())


def test_generated_data_passes_validation(
    browsing_data: BrowsingData,
    browsing_upstream: dict[str, pl.DataFrame],
    browsing_simulation_config: SimulationConfig,
) -> None:
    """The bundle satisfies the F003.2 acceptance criteria."""
    settings = browsing_simulation_config.browsing
    issues = validate_browsing_data(
        {**browsing_upstream, **browsing_data.datasets},
        settings.min_view_seconds,
        settings.max_view_seconds,
        settings.max_results_count,
    )

    assert issues == []


def test_generation_is_deterministic(
    browsing_simulation_config: SimulationConfig,
    browsing_upstream: dict[str, pl.DataFrame],
) -> None:
    """The same configuration and seed reproduce identical datasets."""
    first = generate_browsing_data(browsing_simulation_config, browsing_upstream)
    second = generate_browsing_data(browsing_simulation_config, browsing_upstream)

    assert first.seed == second.seed
    for name, frame in first:
        assert frame.equals(second[name]), f"{name} differs between runs"


def test_a_different_seed_changes_the_data(
    browsing_simulation_config: SimulationConfig,
    browsing_upstream: dict[str, pl.DataFrame],
) -> None:
    """Changing the seed changes generated attributes."""
    other = SimulationConfig(
        platform=PlatformConfig(seed=13_579),
        master_data=browsing_simulation_config.master_data,
        customers=browsing_simulation_config.customers,
        journey=browsing_simulation_config.journey,
        browsing=browsing_simulation_config.browsing,
    )

    baseline = generate_browsing_data(browsing_simulation_config, browsing_upstream)
    varied = generate_browsing_data(other, browsing_upstream)

    assert not baseline["category_views"].equals(varied["category_views"])


def test_a_null_seed_still_reports_a_reproducible_seed(
    browsing_simulation_config: SimulationConfig,
    browsing_upstream: dict[str, pl.DataFrame],
) -> None:
    """A non-deterministic run reports the seed it actually used."""
    config = SimulationConfig(
        platform=PlatformConfig(seed=None),
        master_data=browsing_simulation_config.master_data,
        customers=browsing_simulation_config.customers,
        journey=browsing_simulation_config.journey,
        browsing=browsing_simulation_config.browsing,
    )

    generated = generate_browsing_data(config, browsing_upstream)
    replay = generate_browsing_data(
        SimulationConfig(
            platform=PlatformConfig(seed=generated.seed),
            master_data=config.master_data,
            customers=config.customers,
            journey=config.journey,
            browsing=config.browsing,
        ),
        browsing_upstream,
    )

    assert generated["category_views"].equals(replay["category_views"])


@pytest.mark.parametrize("missing", REQUIRED_BROWSING_DATASETS)
def test_missing_upstream_data_is_reported(
    browsing_simulation_config: SimulationConfig,
    browsing_upstream: dict[str, pl.DataFrame],
    missing: str,
) -> None:
    """Each required upstream dataset is checked before generation starts."""
    available = {name: frame for name, frame in browsing_upstream.items() if name != missing}

    with pytest.raises(KeyError, match="Missing upstream data"):
        generate_browsing_data(browsing_simulation_config, available)


def test_missing_upstream_names_the_prerequisite_commands(
    browsing_simulation_config: SimulationConfig,
    browsing_upstream: dict[str, pl.DataFrame],
) -> None:
    """The error tells the user which commands to run first."""
    available = {name: frame for name, frame in browsing_upstream.items() if name != "categories"}

    with pytest.raises(KeyError, match="generate master-data"):
        generate_browsing_data(browsing_simulation_config, available)


def test_empty_categories_stops_generation(
    browsing_simulation_config: SimulationConfig,
    browsing_upstream: dict[str, pl.DataFrame],
) -> None:
    """An empty categories dataset is reported clearly."""
    available = dict(browsing_upstream)
    available["categories"] = available["categories"].clear()

    with pytest.raises(ValueError, match="categories dataset is empty"):
        generate_browsing_data(browsing_simulation_config, available)


def test_total_rows_sums_every_dataset(browsing_data: BrowsingData) -> None:
    """The reported total matches the sum of the parts."""
    assert browsing_data.total_rows() == sum(browsing_data.row_counts().values())


def test_bundle_iteration_yields_name_and_frame(browsing_data: BrowsingData) -> None:
    """Iterating the bundle yields usable pairs."""
    for name, frame in browsing_data:
        assert isinstance(name, str)
        assert isinstance(frame, pl.DataFrame)


def test_unknown_dataset_access_raises(browsing_data: BrowsingData) -> None:
    """Requesting a dataset F003.2 does not produce fails clearly."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        browsing_data["product_views"]


def test_browsing_does_not_regenerate_upstream_data(
    browsing_data: BrowsingData, browsing_upstream: dict[str, pl.DataFrame]
) -> None:
    """F003.2 consumes earlier output; it emits none of those datasets."""
    assert set(browsing_data.datasets).isdisjoint(set(browsing_upstream))
