"""Tests for the journey orchestrator and its configuration."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from eds.config import (
    ConfigError,
    JourneyConfig,
    PlatformConfig,
    SimulationConfig,
    load_config,
    load_journey_config,
)
from eds.domain.journey.schema import (
    JOURNEY_DATASETS,
    journey_dataset_by_name,
    journey_dataset_names,
)
from eds.generators.journey.journey import (
    REQUIRED_UPSTREAM_DATASETS,
    JourneyData,
    generate_journey_data,
)
from eds.validation.journey_validation import validate_journey_data

EXPECTED_OUTPUTS = {"customer_personas", "sessions"}


def test_shipped_journey_config_loads() -> None:
    """The committed journey.yaml is valid and matches the documented defaults."""
    config = load_journey_config()

    assert config.bounce_rate == pytest.approx(0.25)
    assert config.max_pages_viewed == 25
    assert config.session_years == 5


def test_journey_config_is_part_of_the_run_configuration() -> None:
    """`load_config` includes the journey section."""
    assert load_config().journey.max_pages_viewed == 25


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bounce_rate", -0.1),
        ("bounce_rate", 1.5),
        ("max_pages_viewed", 1),
        ("session_years", 0),
        ("batch_size", 0),
    ],
)
def test_out_of_range_journey_values_are_rejected(field: str, value: float) -> None:
    """Settings outside their declared bounds fail validation."""
    with pytest.raises(ValueError, match=field):
        JourneyConfig(**{field: value})  # type: ignore[arg-type]


def test_unknown_journey_key_is_rejected() -> None:
    """A misspelled key is an error, not a silent no-op."""
    with pytest.raises(ValueError, match="bounce_rat"):
        JourneyConfig(bounce_rat=0.2)  # type: ignore[call-arg]


def test_invalid_journey_config_file_raises(tmp_path: Path) -> None:
    """An out-of-range value names the offending file."""
    (tmp_path / "journey.yaml").write_text("bounce_rate: 2.0\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="journey.yaml"):
        load_journey_config(tmp_path)


def test_registry_lists_the_two_documented_outputs() -> None:
    """F003.1 declares exactly two output datasets."""
    assert len(JOURNEY_DATASETS) == 2
    assert set(journey_dataset_names()) == EXPECTED_OUTPUTS


def test_dataset_file_names_match_the_specification() -> None:
    """Each dataset maps to the documented Parquet file name."""
    assert journey_dataset_by_name("sessions").file_name == "sessions.parquet"
    assert journey_dataset_by_name("customer_personas").file_name == "customer_personas.parquet"


def test_unknown_journey_dataset_lookup_raises() -> None:
    """Looking up an unregistered dataset fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown journey dataset"):
        journey_dataset_by_name("product_views")


def test_all_documented_datasets_are_generated(journey_data: JourneyData) -> None:
    """Every dataset named in the F003.1 output list is produced."""
    assert set(journey_data.datasets) == EXPECTED_OUTPUTS


def test_datasets_are_emitted_in_dependency_order(journey_data: JourneyData) -> None:
    """Personas come first, so sessions can reference their shape."""
    assert list(journey_data.datasets) == [dataset.name for dataset in JOURNEY_DATASETS]


def test_no_dataset_is_empty(journey_data: JourneyData) -> None:
    """Both journey datasets carry rows."""
    assert all(count > 0 for count in journey_data.row_counts().values())


def test_persona_count_equals_customer_count(
    journey_data: JourneyData, journey_upstream: dict[str, pl.DataFrame]
) -> None:
    """Exactly one persona per customer."""
    assert journey_data.row_counts()["customer_personas"] == (journey_upstream["customers"].height)


def test_generated_data_passes_validation(
    journey_data: JourneyData,
    journey_upstream: dict[str, pl.DataFrame],
    journey_simulation_config: SimulationConfig,
) -> None:
    """The bundle satisfies the F003.1 acceptance criteria."""
    issues = validate_journey_data(
        {**journey_upstream, **journey_data.datasets},
        journey_simulation_config.customers.reference_date,
        journey_simulation_config.journey.session_years,
        journey_simulation_config.journey.max_pages_viewed,
    )

    assert issues == []


def test_generation_is_deterministic(
    journey_simulation_config: SimulationConfig, journey_upstream: dict[str, pl.DataFrame]
) -> None:
    """The same configuration and seed reproduce identical datasets."""
    first = generate_journey_data(journey_simulation_config, journey_upstream)
    second = generate_journey_data(journey_simulation_config, journey_upstream)

    assert first.seed == second.seed
    for name, frame in first:
        assert frame.equals(second[name]), f"{name} differs between runs"


def test_a_different_seed_changes_the_data(
    journey_simulation_config: SimulationConfig, journey_upstream: dict[str, pl.DataFrame]
) -> None:
    """Changing the seed changes generated attributes."""
    other = SimulationConfig(
        platform=PlatformConfig(seed=98_765),
        master_data=journey_simulation_config.master_data,
        customers=journey_simulation_config.customers,
        journey=journey_simulation_config.journey,
    )

    baseline = generate_journey_data(journey_simulation_config, journey_upstream)
    varied = generate_journey_data(other, journey_upstream)

    assert not baseline["customer_personas"].equals(varied["customer_personas"])


def test_a_null_seed_still_reports_a_reproducible_seed(
    journey_simulation_config: SimulationConfig, journey_upstream: dict[str, pl.DataFrame]
) -> None:
    """A non-deterministic run reports the seed it actually used."""
    config = SimulationConfig(
        platform=PlatformConfig(seed=None),
        master_data=journey_simulation_config.master_data,
        customers=journey_simulation_config.customers,
        journey=journey_simulation_config.journey,
    )

    generated = generate_journey_data(config, journey_upstream)
    replay = generate_journey_data(
        SimulationConfig(
            platform=PlatformConfig(seed=generated.seed),
            master_data=config.master_data,
            customers=config.customers,
            journey=config.journey,
        ),
        journey_upstream,
    )

    assert generated["sessions"].equals(replay["sessions"])


@pytest.mark.parametrize("missing", REQUIRED_UPSTREAM_DATASETS)
def test_missing_upstream_data_is_reported(
    journey_simulation_config: SimulationConfig,
    journey_upstream: dict[str, pl.DataFrame],
    missing: str,
) -> None:
    """Each required upstream dataset is checked before generation starts."""
    available = {name: frame for name, frame in journey_upstream.items() if name != missing}

    with pytest.raises(KeyError, match="Missing upstream data"):
        generate_journey_data(journey_simulation_config, available)


def test_missing_upstream_names_both_prerequisite_commands(
    journey_simulation_config: SimulationConfig, journey_upstream: dict[str, pl.DataFrame]
) -> None:
    """The error tells the user which commands to run first."""
    available = {name: frame for name, frame in journey_upstream.items() if name != "cities"}

    with pytest.raises(KeyError, match="generate master-data"):
        generate_journey_data(journey_simulation_config, available)


def test_empty_customers_stops_generation(
    journey_simulation_config: SimulationConfig, journey_upstream: dict[str, pl.DataFrame]
) -> None:
    """An empty customers dataset is reported clearly."""
    available = dict(journey_upstream)
    available["customers"] = available["customers"].clear()

    with pytest.raises(ValueError, match="customers dataset is empty"):
        generate_journey_data(journey_simulation_config, available)


def test_total_rows_sums_every_dataset(journey_data: JourneyData) -> None:
    """The reported total matches the sum of the parts."""
    assert journey_data.total_rows() == sum(journey_data.row_counts().values())


def test_bundle_iteration_yields_name_and_frame(journey_data: JourneyData) -> None:
    """Iterating the bundle yields usable pairs."""
    for name, frame in journey_data:
        assert isinstance(name, str)
        assert isinstance(frame, pl.DataFrame)


def test_unknown_dataset_access_raises(journey_data: JourneyData) -> None:
    """Requesting a dataset F003.1 does not produce fails clearly."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        journey_data["product_views"]


def test_journey_does_not_regenerate_upstream_data(
    journey_data: JourneyData, journey_upstream: dict[str, pl.DataFrame]
) -> None:
    """F003.1 consumes F001 and F002 output; it emits none of their datasets."""
    assert set(journey_data.datasets).isdisjoint(set(journey_upstream))
