"""Tests for the master data orchestrator, covering the F001 success criteria."""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import MasterDataConfig, PlatformConfig, SimulationConfig
from eds.domain.master_data import MASTER_DATA_DATASETS
from eds.generators.master_data import MasterData, generate_master_data
from eds.validation.master_data import validate_master_data

EXPECTED_OUTPUTS = {
    "countries",
    "states",
    "cities",
    "categories",
    "brands",
    "suppliers",
    "products",
    "warehouses",
    "inventory",
    "shipping_methods",
    "payment_methods",
    "tax_codes",
    "coupon_types",
    "return_reasons",
}


def test_all_documented_datasets_are_generated(master_data: MasterData) -> None:
    """Every dataset named in the F001 output list is produced."""
    assert set(master_data.datasets) == EXPECTED_OUTPUTS


def test_datasets_are_emitted_in_dependency_order(master_data: MasterData) -> None:
    """Iteration order matches the registry, so references resolve."""
    assert list(master_data.datasets) == [dataset.name for dataset in MASTER_DATA_DATASETS]


def test_no_dataset_is_empty(master_data: MasterData) -> None:
    """A master dataset with no rows would break downstream features."""
    assert all(count > 0 for count in master_data.row_counts().values())


def test_row_counts_follow_the_configuration(
    master_data: MasterData, small_master_data_config: MasterDataConfig
) -> None:
    """Configured volumes are reflected in the generated frames."""
    counts = master_data.row_counts()

    assert counts["products"] == small_master_data_config.product_count
    assert counts["brands"] == small_master_data_config.brand_count
    assert counts["suppliers"] == small_master_data_config.supplier_count
    assert counts["warehouses"] == small_master_data_config.warehouse_count


def test_generated_data_passes_validation(master_data: MasterData) -> None:
    """The bundle satisfies referential integrity and business rules."""
    assert validate_master_data(master_data.datasets) == []


def test_generation_is_deterministic(simulation_config: SimulationConfig) -> None:
    """The same configuration and seed reproduce identical datasets."""
    first = generate_master_data(simulation_config)
    second = generate_master_data(simulation_config)

    assert first.seed == second.seed
    for name, frame in first:
        assert frame.equals(second[name]), f"{name} differs between runs"


def test_a_different_seed_changes_synthesised_data(
    simulation_config: SimulationConfig,
) -> None:
    """Changing the seed changes generated attributes."""
    other = SimulationConfig(
        platform=PlatformConfig(seed=987_654),
        master_data=simulation_config.master_data,
    )

    baseline = generate_master_data(simulation_config)
    varied = generate_master_data(other)

    assert not baseline["products"].equals(varied["products"])
    # Reference data is seed-independent by design.
    assert baseline["countries"].equals(varied["countries"])


def test_a_null_seed_still_reports_a_reproducible_seed(
    small_master_data_config: MasterDataConfig,
) -> None:
    """A non-deterministic run reports the seed it actually used."""
    config = SimulationConfig(
        platform=PlatformConfig(seed=None), master_data=small_master_data_config
    )

    generated = generate_master_data(config)
    replay = generate_master_data(
        SimulationConfig(
            platform=PlatformConfig(seed=generated.seed), master_data=small_master_data_config
        )
    )

    assert generated["products"].equals(replay["products"])


def test_currency_follows_the_first_configured_country(
    small_master_data_config: MasterDataConfig,
) -> None:
    """A UK-only run prices in GBP."""
    config = SimulationConfig(
        platform=PlatformConfig(seed=5),
        master_data=small_master_data_config.model_copy(update={"countries": ("GB",)}),
    )

    data = generate_master_data(config)

    assert set(data["products"]["currency_code"].to_list()) == {"GBP"}


def test_products_reference_only_generated_parents(master_data: MasterData) -> None:
    """No orphan product references exist."""
    products = master_data["products"]

    assert set(products["brand_id"].to_list()) <= set(master_data["brands"]["brand_id"].to_list())
    assert set(products["supplier_id"].to_list()) <= set(
        master_data["suppliers"]["supplier_id"].to_list()
    )
    assert set(products["tax_code_id"].to_list()) <= set(
        master_data["tax_codes"]["tax_code_id"].to_list()
    )


def test_inventory_references_only_generated_parents(master_data: MasterData) -> None:
    """No orphan inventory references exist."""
    inventory = master_data["inventory"]

    assert set(inventory["product_id"].to_list()) <= set(
        master_data["products"]["product_id"].to_list()
    )
    assert set(inventory["warehouse_id"].to_list()) <= set(
        master_data["warehouses"]["warehouse_id"].to_list()
    )


def test_total_rows_sums_every_dataset(master_data: MasterData) -> None:
    """The reported total matches the sum of the parts."""
    assert master_data.total_rows() == sum(master_data.row_counts().values())


def test_bundle_iteration_yields_name_and_frame(master_data: MasterData) -> None:
    """Iterating the bundle yields usable pairs."""
    for name, frame in master_data:
        assert isinstance(name, str)
        assert isinstance(frame, pl.DataFrame)


def test_unknown_dataset_access_raises(master_data: MasterData) -> None:
    """Requesting a dataset that F001 does not produce fails clearly."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        master_data["customers"]


def test_unknown_country_stops_the_run(small_master_data_config: MasterDataConfig) -> None:
    """A country without reference data aborts generation."""
    config = SimulationConfig(
        platform=PlatformConfig(seed=1),
        master_data=small_master_data_config.model_copy(update={"countries": ("ZZ",)}),
    )

    with pytest.raises(KeyError, match="Supported countries"):
        generate_master_data(config)


def test_multi_country_run_keeps_integrity(
    small_master_data_config: MasterDataConfig,
) -> None:
    """A run spanning several countries still validates cleanly."""
    config = SimulationConfig(
        platform=PlatformConfig(seed=17),
        master_data=small_master_data_config.model_copy(
            update={"countries": ("US", "CA", "GB"), "cities_per_state": 1}
        ),
    )

    data = generate_master_data(config)

    assert data["countries"].height == 3
    assert validate_master_data(data.datasets) == []
