"""Tests for the supplier, warehouse, and inventory generators."""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import MasterDataConfig
from eds.domain.enums import SupplierTier, WarehouseStatus
from eds.generators.geography.generator import generate_cities
from eds.generators.inventory.generator import (
    generate_inventory,
    stockable_warehouse_ids,
)
from eds.generators.products.products import generate_products
from eds.generators.suppliers.generator import generate_suppliers
from eds.generators.warehouses.generator import generate_warehouses

SEED = 909


@pytest.fixture
def settings() -> MasterDataConfig:
    """Return a small supply chain configuration."""
    return MasterDataConfig(
        countries=("US",),
        cities_per_state=1,
        supplier_count=12,
        warehouse_count=8,
        product_count=30,
        warehouses_per_product=3,
        batch_size=1_000,
    )


@pytest.fixture
def cities(settings: MasterDataConfig) -> pl.DataFrame:
    """Return generated cities to anchor supply chain locations."""
    return generate_cities(settings, SEED)


def test_supplier_count_matches_configuration(
    settings: MasterDataConfig, cities: pl.DataFrame
) -> None:
    """Exactly the configured number of suppliers is produced."""
    suppliers = generate_suppliers(settings, cities, SEED)

    assert suppliers.height == settings.supplier_count
    assert suppliers["supplier_code"].n_unique() == suppliers.height


def test_supplier_city_and_country_agree(settings: MasterDataConfig, cities: pl.DataFrame) -> None:
    """A supplier's country matches the country of its city."""
    suppliers = generate_suppliers(settings, cities, SEED)
    joined = suppliers.join(cities, on="city_id", how="inner", suffix="_city")

    assert joined.height == suppliers.height
    assert joined.filter(pl.col("country_id") != pl.col("country_id_city")).height == 0


def test_supplier_tiers_are_known_values(settings: MasterDataConfig, cities: pl.DataFrame) -> None:
    """Tiers come from the declared enum."""
    suppliers = generate_suppliers(settings, cities, SEED)

    assert set(suppliers["tier"].to_list()) <= {str(member) for member in SupplierTier}


def test_supplier_lead_times_and_reliability_are_sane(
    settings: MasterDataConfig, cities: pl.DataFrame
) -> None:
    """Lead time is positive and reliability is a probability."""
    suppliers = generate_suppliers(settings, cities, SEED)

    assert suppliers.filter(pl.col("lead_time_days") <= 0).height == 0
    assert (
        suppliers.filter(
            (pl.col("reliability_score") < 0) | (pl.col("reliability_score") > 1)
        ).height
        == 0
    )


def test_strategic_suppliers_beat_transactional_ones(cities: pl.DataFrame) -> None:
    """Tier correlates with lead time, as documented."""
    settings = MasterDataConfig(supplier_count=400, warehouse_count=5, warehouses_per_product=2)
    suppliers = generate_suppliers(settings, cities, SEED)

    strategic = suppliers.filter(pl.col("tier") == str(SupplierTier.STRATEGIC))
    transactional = suppliers.filter(pl.col("tier") == str(SupplierTier.TRANSACTIONAL))

    slowest_strategic = max(strategic["lead_time_days"].to_list())
    fastest_transactional = min(transactional["lead_time_days"].to_list())

    assert slowest_strategic <= fastest_transactional


def test_suppliers_require_cities(settings: MasterDataConfig, cities: pl.DataFrame) -> None:
    """Suppliers cannot be placed without geography."""
    with pytest.raises(ValueError, match="cities dataset is empty"):
        generate_suppliers(settings, cities.clear(), SEED)


def test_warehouse_count_and_codes(settings: MasterDataConfig, cities: pl.DataFrame) -> None:
    """Warehouse codes are unique and the count is honoured."""
    warehouses = generate_warehouses(settings, cities, SEED)

    assert warehouses.height == settings.warehouse_count
    assert warehouses["warehouse_code"].n_unique() == warehouses.height


def test_warehouse_inherits_city_geography(
    settings: MasterDataConfig, cities: pl.DataFrame
) -> None:
    """State, country, and coordinates are copied from the chosen city."""
    warehouses = generate_warehouses(settings, cities, SEED)
    joined = warehouses.join(cities, on="city_id", how="inner", suffix="_city")

    assert joined.filter(pl.col("state_id") != pl.col("state_id_city")).height == 0
    assert joined.filter(pl.col("country_id") != pl.col("country_id_city")).height == 0
    assert joined.filter(pl.col("latitude") != pl.col("latitude_city")).height == 0


def test_warehouse_capacity_is_positive(settings: MasterDataConfig, cities: pl.DataFrame) -> None:
    """Every warehouse can hold stock."""
    warehouses = generate_warehouses(settings, cities, SEED)

    assert warehouses.filter(pl.col("capacity_units") <= 0).height == 0


def test_warehouse_statuses_are_known_values(
    settings: MasterDataConfig, cities: pl.DataFrame
) -> None:
    """Statuses come from the declared enum."""
    warehouses = generate_warehouses(settings, cities, SEED)

    assert set(warehouses["status"].to_list()) <= {str(member) for member in WarehouseStatus}


def test_warehouses_require_cities(settings: MasterDataConfig, cities: pl.DataFrame) -> None:
    """Warehouses cannot be placed without geography."""
    with pytest.raises(ValueError, match="cities dataset is empty"):
        generate_warehouses(settings, cities.clear(), SEED)


def build_products(settings: MasterDataConfig, cities: pl.DataFrame) -> pl.DataFrame:
    """Generate a products frame for inventory tests.

    Args:
        settings: Master data configuration.
        cities: Generated cities.

    Returns:
        The generated products frame.
    """
    from eds.generators.commercial.generator import generate_tax_codes
    from eds.generators.geography.generator import generate_countries
    from eds.generators.products.brands import generate_brands
    from eds.generators.products.categories import generate_categories

    countries = generate_countries(settings)
    return generate_products(
        settings,
        generate_categories(settings),
        generate_brands(settings, countries, SEED),
        generate_suppliers(settings, cities, SEED),
        generate_tax_codes(settings),
        SEED,
    )


def test_inventory_row_count_matches_the_stocking_policy(
    settings: MasterDataConfig, cities: pl.DataFrame
) -> None:
    """Each product is stocked in the configured number of warehouses."""
    products = build_products(settings, cities)
    warehouses = generate_warehouses(settings, cities, SEED)
    inventory = generate_inventory(settings, products, warehouses, SEED)

    stockable = len(stockable_warehouse_ids(warehouses))
    expected_per_product = min(settings.warehouses_per_product, stockable)

    assert inventory.height == products.height * expected_per_product


def test_inventory_never_stocks_a_closed_warehouse(
    settings: MasterDataConfig, cities: pl.DataFrame
) -> None:
    """Closed and inactive warehouses hold no stock."""
    products = build_products(settings, cities)
    warehouses = generate_warehouses(settings, cities, SEED)
    inventory = generate_inventory(settings, products, warehouses, SEED)

    allowed = set(stockable_warehouse_ids(warehouses))

    assert set(inventory["warehouse_id"].to_list()) <= allowed


def test_a_product_is_not_stocked_twice_in_one_warehouse(
    settings: MasterDataConfig, cities: pl.DataFrame
) -> None:
    """Product and warehouse form a natural composite key."""
    products = build_products(settings, cities)
    warehouses = generate_warehouses(settings, cities, SEED)
    inventory = generate_inventory(settings, products, warehouses, SEED)

    pairs = inventory.select("product_id", "warehouse_id")

    assert pairs.n_unique() == pairs.height


def test_reserved_stock_never_exceeds_stock_on_hand(
    settings: MasterDataConfig, cities: pl.DataFrame
) -> None:
    """Reservations are bounded by physical stock."""
    products = build_products(settings, cities)
    warehouses = generate_warehouses(settings, cities, SEED)
    inventory = generate_inventory(settings, products, warehouses, SEED)

    assert inventory.filter(pl.col("quantity_reserved") > pl.col("quantity_on_hand")).height == 0


def test_inventory_unit_cost_matches_the_product(
    settings: MasterDataConfig, cities: pl.DataFrame
) -> None:
    """Stock is valued at the product's unit cost."""
    products = build_products(settings, cities)
    warehouses = generate_warehouses(settings, cities, SEED)
    inventory = generate_inventory(settings, products, warehouses, SEED)

    joined = inventory.join(
        products.select("product_id", "unit_cost"), on="product_id", suffix="_p"
    )

    assert joined.filter(pl.col("unit_cost") != pl.col("unit_cost_p")).height == 0


def test_inventory_requires_a_stockable_warehouse(
    settings: MasterDataConfig, cities: pl.DataFrame
) -> None:
    """With every warehouse closed there is nowhere to put stock."""
    products = build_products(settings, cities)
    warehouses = generate_warehouses(settings, cities, SEED).with_columns(
        pl.lit(str(WarehouseStatus.CLOSED)).alias("status")
    )

    with pytest.raises(ValueError, match="no warehouse has a stockable status"):
        generate_inventory(settings, products, warehouses, SEED)
