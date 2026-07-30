"""Tests for the customer data orchestrator and its configuration."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from eds.config import (
    ConfigError,
    CustomerConfig,
    PlatformConfig,
    SimulationConfig,
    load_config,
    load_customer_config,
)
from eds.domain.customer.schema import (
    CUSTOMER_DATASETS,
    customer_dataset_by_name,
    customer_dataset_names,
)
from eds.generators.customer_data import (
    REQUIRED_MASTER_DATASETS,
    CustomerData,
    generate_customer_data,
)
from eds.generators.master_data import MasterData
from eds.validation.customer_validation import validate_customer_data

EXPECTED_OUTPUTS = {
    "customers",
    "customer_addresses",
    "customer_preferences",
    "customer_loyalty",
}


def test_shipped_customer_config_loads() -> None:
    """The committed customers.yaml is valid and matches the documented defaults."""
    config = load_customer_config()

    assert config.customer_count == 1_000
    assert config.min_addresses == 1
    assert config.max_addresses == 2


def test_customer_config_is_part_of_the_run_configuration() -> None:
    """`load_config` includes the customer section."""
    assert load_config().customers.customer_count == 1_000


def test_earliest_registration_date_follows_the_window() -> None:
    """The registration window is derived from the reference date."""
    config = CustomerConfig(reference_date=date(2026, 1, 1), registration_years=5)

    assert config.earliest_registration_date == date(2021, 1, 2)


def test_inverted_address_bounds_are_rejected() -> None:
    """A minimum above the maximum is a configuration error."""
    with pytest.raises(ValueError, match="cannot exceed"):
        CustomerConfig(min_addresses=3, max_addresses=2)


@pytest.mark.parametrize(
    ("field", "value"),
    [("customer_count", 0), ("min_addresses", 0), ("registration_years", 0), ("batch_size", 0)],
)
def test_out_of_range_customer_values_are_rejected(field: str, value: int) -> None:
    """Counts outside their declared bounds fail validation."""
    with pytest.raises(ValueError, match=field):
        CustomerConfig(**{field: value})  # type: ignore[arg-type]


def test_invalid_customer_config_file_raises(tmp_path: Path) -> None:
    """An out-of-range value names the offending file."""
    (tmp_path / "customers.yaml").write_text("customer_count: 0\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="customers.yaml"):
        load_customer_config(tmp_path)


def test_registry_lists_the_four_documented_outputs() -> None:
    """F002 declares exactly four output datasets."""
    assert len(CUSTOMER_DATASETS) == 4
    assert set(customer_dataset_names()) == EXPECTED_OUTPUTS


def test_dataset_file_names_match_the_specification() -> None:
    """Each dataset maps to the documented Parquet file name."""
    assert customer_dataset_by_name("customers").file_name == "customers.parquet"
    assert customer_dataset_by_name("customer_addresses").file_name == "customer_addresses.parquet"


def test_unknown_customer_dataset_lookup_raises() -> None:
    """Looking up an unregistered dataset fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown customer dataset"):
        customer_dataset_by_name("orders")


def test_all_documented_datasets_are_generated(customer_data: CustomerData) -> None:
    """Every dataset named in the F002 output list is produced."""
    assert set(customer_data.datasets) == EXPECTED_OUTPUTS


def test_datasets_are_emitted_in_dependency_order(customer_data: CustomerData) -> None:
    """Customers come first, so the datasets that reference them resolve."""
    assert list(customer_data.datasets) == [dataset.name for dataset in CUSTOMER_DATASETS]


def test_no_dataset_is_empty(customer_data: CustomerData) -> None:
    """An empty customer dataset would break downstream features."""
    assert all(count > 0 for count in customer_data.row_counts().values())


def test_row_counts_follow_the_configuration(
    customer_data: CustomerData, small_customer_config: CustomerConfig
) -> None:
    """One row per customer in the one-to-one datasets."""
    counts = customer_data.row_counts()
    expected = small_customer_config.customer_count

    assert counts["customers"] == expected
    assert counts["customer_preferences"] == expected
    assert counts["customer_loyalty"] == expected
    assert expected <= counts["customer_addresses"] <= expected * 2


def test_generated_data_passes_validation(
    customer_data: CustomerData, master_data: MasterData, small_customer_config: CustomerConfig
) -> None:
    """The bundle satisfies the F002 data quality rules."""
    issues = validate_customer_data(
        {**master_data.datasets, **customer_data.datasets},
        small_customer_config.min_addresses,
        small_customer_config.max_addresses,
    )

    assert issues == []


def test_generation_is_deterministic(
    customer_simulation_config: SimulationConfig, master_data: MasterData
) -> None:
    """The same configuration and seed reproduce identical datasets."""
    first = generate_customer_data(customer_simulation_config, master_data.datasets)
    second = generate_customer_data(customer_simulation_config, master_data.datasets)

    assert first.seed == second.seed
    for name, frame in first:
        assert frame.equals(second[name]), f"{name} differs between runs"


def test_a_different_seed_changes_the_data(
    customer_simulation_config: SimulationConfig, master_data: MasterData
) -> None:
    """Changing the seed changes generated attributes."""
    other = SimulationConfig(
        platform=PlatformConfig(seed=424_242),
        master_data=customer_simulation_config.master_data,
        customers=customer_simulation_config.customers,
    )

    baseline = generate_customer_data(customer_simulation_config, master_data.datasets)
    varied = generate_customer_data(other, master_data.datasets)

    assert not baseline["customers"].equals(varied["customers"])


def test_a_null_seed_still_reports_a_reproducible_seed(
    customer_simulation_config: SimulationConfig, master_data: MasterData
) -> None:
    """A non-deterministic run reports the seed it actually used."""
    config = SimulationConfig(
        platform=PlatformConfig(seed=None),
        master_data=customer_simulation_config.master_data,
        customers=customer_simulation_config.customers,
    )

    generated = generate_customer_data(config, master_data.datasets)
    replay = generate_customer_data(
        SimulationConfig(
            platform=PlatformConfig(seed=generated.seed),
            master_data=config.master_data,
            customers=config.customers,
        ),
        master_data.datasets,
    )

    assert generated["customers"].equals(replay["customers"])


@pytest.mark.parametrize("missing", REQUIRED_MASTER_DATASETS)
def test_missing_master_data_is_reported(
    customer_simulation_config: SimulationConfig, master_data: MasterData, missing: str
) -> None:
    """Each required F001 dataset is checked before generation starts."""
    available = {name: frame for name, frame in master_data.datasets.items() if name != missing}

    with pytest.raises(KeyError, match="Missing master data"):
        generate_customer_data(customer_simulation_config, available)


def test_empty_master_data_is_reported(
    customer_simulation_config: SimulationConfig, master_data: MasterData
) -> None:
    """An empty cities dataset stops generation with a clear message."""
    available = dict(master_data.datasets)
    available["cities"] = available["cities"].clear()

    with pytest.raises(ValueError, match="cities dataset is empty"):
        generate_customer_data(customer_simulation_config, available)


def test_total_rows_sums_every_dataset(customer_data: CustomerData) -> None:
    """The reported total matches the sum of the parts."""
    assert customer_data.total_rows() == sum(customer_data.row_counts().values())


def test_bundle_iteration_yields_name_and_frame(customer_data: CustomerData) -> None:
    """Iterating the bundle yields usable pairs."""
    for name, frame in customer_data:
        assert isinstance(name, str)
        assert isinstance(frame, pl.DataFrame)


def test_unknown_dataset_access_raises(customer_data: CustomerData) -> None:
    """Requesting a dataset that F002 does not produce fails clearly."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        customer_data["orders"]


def test_customers_do_not_regenerate_master_data(
    customer_data: CustomerData, master_data: MasterData
) -> None:
    """F002 consumes F001 output; it emits no master datasets of its own."""
    assert set(customer_data.datasets).isdisjoint(set(master_data.datasets))
