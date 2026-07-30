"""Tests for the commerce orchestrator and its configuration."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from eds.config import (
    CommerceConfig,
    ConfigError,
    PlatformConfig,
    SimulationConfig,
    load_commerce_config,
    load_config,
)
from eds.domain.commerce.schema import (
    COMMERCE_DATASETS,
    commerce_dataset_by_name,
    commerce_dataset_names,
)
from eds.domain.journey.schema import ENGAGEMENT_DATASETS, JOURNEY_DATASETS
from eds.generators.commerce.commerce import (
    REQUIRED_COMMERCE_DATASETS,
    CommerceData,
    generate_commerce_data,
)
from eds.validation.commerce_validation import validate_commerce_data

EXPECTED_OUTPUTS = {"shopping_carts", "cart_items"}


def test_shipped_commerce_config_loads() -> None:
    """The committed commerce.yaml matches the documented defaults."""
    config = load_commerce_config()

    assert config.min_quantity == 1
    assert config.max_quantity == 5
    assert config.max_cart_items == 7


def test_commerce_config_is_part_of_the_run_configuration() -> None:
    """`load_config` includes the commerce section."""
    assert load_config().commerce.max_quantity == 5


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cart_session_rate", 1.5),
        ("cart_session_rate", -0.1),
        ("min_quantity", 0),
        ("max_cart_items", 0),
        ("removal_rate", 2.0),
        ("batch_size", 0),
    ],
)
def test_out_of_range_commerce_values_are_rejected(field: str, value: float) -> None:
    """Settings outside their declared bounds fail validation."""
    with pytest.raises(ValueError, match=field):
        CommerceConfig(**{field: value})  # type: ignore[arg-type]


def test_inverted_quantity_range_is_rejected() -> None:
    """A minimum above its maximum is a configuration error."""
    with pytest.raises(ValueError, match="cannot exceed"):
        CommerceConfig(min_quantity=4, max_quantity=2)


def test_unknown_commerce_key_is_rejected() -> None:
    """A misspelled key is an error, not a silent no-op."""
    with pytest.raises(ValueError, match="cart_rate"):
        CommerceConfig(cart_rate=0.2)  # type: ignore[call-arg]


def test_invalid_commerce_config_file_raises(tmp_path: Path) -> None:
    """An out-of-range value names the offending file."""
    (tmp_path / "commerce.yaml").write_text("cart_session_rate: 3.0\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="commerce.yaml"):
        load_commerce_config(tmp_path)


def test_registry_lists_the_two_documented_outputs() -> None:
    """F004 declares exactly two output datasets."""
    assert len(COMMERCE_DATASETS) == 2
    assert set(commerce_dataset_names()) == EXPECTED_OUTPUTS


def test_earlier_registries_are_unchanged() -> None:
    """Adding commerce did not disturb the journey registries."""
    assert {dataset.name for dataset in JOURNEY_DATASETS} == {
        "customer_personas",
        "sessions",
    }
    assert {dataset.name for dataset in ENGAGEMENT_DATASETS} == {
        "product_views",
        "wishlists",
    }


def test_dataset_file_names_match_the_specification() -> None:
    """Each dataset maps to the documented Parquet file name."""
    assert commerce_dataset_by_name("shopping_carts").file_name == "shopping_carts.parquet"
    assert commerce_dataset_by_name("cart_items").file_name == "cart_items.parquet"


def test_unknown_commerce_dataset_lookup_raises() -> None:
    """Looking up an unregistered dataset fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown commerce dataset"):
        commerce_dataset_by_name("orders")


def test_all_documented_datasets_are_generated(commerce_data: CommerceData) -> None:
    """Every dataset named in the F004 output list is produced."""
    assert set(commerce_data.datasets) == EXPECTED_OUTPUTS


def test_datasets_are_emitted_in_dependency_order(commerce_data: CommerceData) -> None:
    """Carts come first, so items can reference them."""
    assert list(commerce_data.datasets) == [dataset.name for dataset in COMMERCE_DATASETS]


def test_no_dataset_is_empty(commerce_data: CommerceData) -> None:
    """Both commerce datasets carry rows."""
    assert all(count > 0 for count in commerce_data.row_counts().values())


def test_generated_data_passes_validation(
    commerce_data: CommerceData,
    commerce_upstream: dict[str, pl.DataFrame],
    commerce_simulation_config: SimulationConfig,
) -> None:
    """The bundle satisfies the F004 acceptance criteria."""
    settings = commerce_simulation_config.commerce
    issues = validate_commerce_data(
        {**commerce_upstream, **commerce_data.datasets},
        settings.min_quantity,
        settings.max_quantity,
    )

    assert issues == []


def test_generation_is_deterministic(
    commerce_simulation_config: SimulationConfig,
    commerce_upstream: dict[str, pl.DataFrame],
) -> None:
    """The same configuration and seed reproduce identical datasets."""
    first = generate_commerce_data(commerce_simulation_config, commerce_upstream)
    second = generate_commerce_data(commerce_simulation_config, commerce_upstream)

    assert first.seed == second.seed
    for name, frame in first:
        assert frame.equals(second[name]), f"{name} differs between runs"


def test_a_different_seed_changes_the_data(
    commerce_simulation_config: SimulationConfig,
    commerce_upstream: dict[str, pl.DataFrame],
) -> None:
    """Changing the seed changes generated attributes."""
    other = SimulationConfig(
        platform=PlatformConfig(seed=86_420),
        master_data=commerce_simulation_config.master_data,
        customers=commerce_simulation_config.customers,
        journey=commerce_simulation_config.journey,
        browsing=commerce_simulation_config.browsing,
        engagement=commerce_simulation_config.engagement,
        commerce=commerce_simulation_config.commerce,
    )

    baseline = generate_commerce_data(commerce_simulation_config, commerce_upstream)
    varied = generate_commerce_data(other, commerce_upstream)

    assert not baseline["shopping_carts"].equals(varied["shopping_carts"])


def test_a_null_seed_still_reports_a_reproducible_seed(
    commerce_simulation_config: SimulationConfig,
    commerce_upstream: dict[str, pl.DataFrame],
) -> None:
    """A non-deterministic run reports the seed it actually used."""
    config = SimulationConfig(
        platform=PlatformConfig(seed=None),
        master_data=commerce_simulation_config.master_data,
        customers=commerce_simulation_config.customers,
        journey=commerce_simulation_config.journey,
        browsing=commerce_simulation_config.browsing,
        engagement=commerce_simulation_config.engagement,
        commerce=commerce_simulation_config.commerce,
    )

    generated = generate_commerce_data(config, commerce_upstream)
    replay = generate_commerce_data(
        SimulationConfig(
            platform=PlatformConfig(seed=generated.seed),
            master_data=config.master_data,
            customers=config.customers,
            journey=config.journey,
            browsing=config.browsing,
            engagement=config.engagement,
            commerce=config.commerce,
        ),
        commerce_upstream,
    )

    assert generated["cart_items"].equals(replay["cart_items"])


@pytest.mark.parametrize("missing", REQUIRED_COMMERCE_DATASETS)
def test_missing_upstream_data_is_reported(
    commerce_simulation_config: SimulationConfig,
    commerce_upstream: dict[str, pl.DataFrame],
    missing: str,
) -> None:
    """Each required upstream dataset is checked before generation starts."""
    available = {name: frame for name, frame in commerce_upstream.items() if name != missing}

    with pytest.raises(KeyError, match="Missing upstream data"):
        generate_commerce_data(commerce_simulation_config, available)


def test_missing_upstream_names_the_prerequisite_commands(
    commerce_simulation_config: SimulationConfig,
    commerce_upstream: dict[str, pl.DataFrame],
) -> None:
    """The error tells the user which commands to run first."""
    available = {
        name: frame for name, frame in commerce_upstream.items() if name != "product_views"
    }

    with pytest.raises(KeyError, match="generate journey"):
        generate_commerce_data(commerce_simulation_config, available)


def test_empty_product_views_stops_generation(
    commerce_simulation_config: SimulationConfig,
    commerce_upstream: dict[str, pl.DataFrame],
) -> None:
    """An empty product views dataset is reported clearly."""
    available = dict(commerce_upstream)
    available["product_views"] = available["product_views"].clear()

    with pytest.raises(ValueError, match="product views dataset is empty"):
        generate_commerce_data(commerce_simulation_config, available)


def test_cart_volume_is_in_the_documented_range(
    commerce_data: CommerceData, commerce_upstream: dict[str, pl.DataFrame]
) -> None:
    """Carts are a modest fraction of sessions, not one per session."""
    carts = commerce_data.row_counts()["shopping_carts"]
    sessions = commerce_upstream["sessions"].height

    assert 0.05 < carts / sessions < 0.35


def test_items_outnumber_carts(commerce_data: CommerceData) -> None:
    """Carts average more than one item."""
    counts = commerce_data.row_counts()

    assert counts["cart_items"] > counts["shopping_carts"]


def test_total_rows_sums_every_dataset(commerce_data: CommerceData) -> None:
    """The reported total matches the sum of the parts."""
    assert commerce_data.total_rows() == sum(commerce_data.row_counts().values())


def test_bundle_iteration_yields_name_and_frame(commerce_data: CommerceData) -> None:
    """Iterating the bundle yields usable pairs."""
    for name, frame in commerce_data:
        assert isinstance(name, str)
        assert isinstance(frame, pl.DataFrame)


def test_unknown_dataset_access_raises(commerce_data: CommerceData) -> None:
    """Requesting a dataset F004 does not produce fails clearly."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        commerce_data["orders"]


def test_commerce_does_not_regenerate_upstream_data(
    commerce_data: CommerceData, commerce_upstream: dict[str, pl.DataFrame]
) -> None:
    """F004 consumes earlier output; it emits none of those datasets."""
    assert set(commerce_data.datasets).isdisjoint(set(commerce_upstream))
