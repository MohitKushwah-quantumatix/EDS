"""Tests for the catalog generators: categories, brands, pricing, products."""

from __future__ import annotations

import random

import polars as pl
import pytest

from eds.config import MasterDataConfig
from eds.domain.enums import ProductStatus, UnitOfMeasure
from eds.generators.commercial.generator import generate_tax_codes
from eds.generators.geography.generator import generate_cities, generate_countries
from eds.generators.pricing.generator import PriceBand, generate_price_point, price_band_for
from eds.generators.products.brands import generate_brands
from eds.generators.products.categories import generate_categories, leaf_category_roots
from eds.generators.products.products import ProductInputs, generate_products, iter_product_batches
from eds.generators.suppliers.generator import generate_suppliers

SEED = 4321


@pytest.fixture
def settings() -> MasterDataConfig:
    """Return a small catalog configuration."""
    return MasterDataConfig(
        countries=("US",),
        cities_per_state=1,
        category_depth=3,
        root_categories=2,
        children_per_category=2,
        brand_count=5,
        supplier_count=4,
        warehouse_count=3,
        product_count=40,
        warehouses_per_product=2,
        batch_size=15,
    )


@pytest.fixture
def catalog_inputs(settings: MasterDataConfig) -> ProductInputs:
    """Return the foreign key pools products depend on."""
    countries = generate_countries(settings)
    cities = generate_cities(settings, SEED)
    return ProductInputs(
        generate_categories(settings),
        generate_brands(settings, countries, SEED),
        generate_suppliers(settings, cities, SEED),
        generate_tax_codes(settings),
    )


def test_category_tree_has_the_expected_shape(settings: MasterDataConfig) -> None:
    """Depth 3 with 2 roots and 2 children yields 2 + 4 + 8 categories."""
    categories = generate_categories(settings)

    assert categories.height == 2 + 4 + 8
    assert categories.filter(pl.col("level") == 1).height == 2
    assert categories.filter(pl.col("is_leaf")).height == 8


def test_root_categories_have_no_parent(settings: MasterDataConfig) -> None:
    """Level-1 categories are tree roots."""
    roots = generate_categories(settings).filter(pl.col("level") == 1)

    assert roots["parent_category_id"].null_count() == roots.height


def test_child_categories_reference_an_existing_parent(settings: MasterDataConfig) -> None:
    """Every non-root parent id resolves to a generated category."""
    categories = generate_categories(settings)
    known = set(categories["category_id"].to_list())
    parents = categories["parent_category_id"].drop_nulls().to_list()

    assert set(parents) <= known


def test_category_paths_are_unique_and_nested(settings: MasterDataConfig) -> None:
    """Paths are unique and a child's path extends its parent's."""
    categories = generate_categories(settings)

    assert categories["category_path"].n_unique() == categories.height
    leaves = categories.filter(pl.col("level") == 3)
    assert all(path.count("/") == 2 for path in leaves["category_path"].to_list())


def test_depth_one_tree_makes_roots_leaves() -> None:
    """With depth 1 the root categories are themselves leaves."""
    categories = generate_categories(MasterDataConfig(category_depth=1, root_categories=3))

    assert categories.height == 3
    assert categories["is_leaf"].all()


def test_leaf_category_roots_maps_to_level_one_names(settings: MasterDataConfig) -> None:
    """Each leaf resolves to its top-level ancestor name."""
    categories = generate_categories(settings)
    roots = leaf_category_roots(categories)

    assert len(roots) == categories.filter(pl.col("is_leaf")).height
    assert set(roots.values()) <= set(categories["category_name"].to_list())


def test_brand_names_are_unique(settings: MasterDataConfig) -> None:
    """Brand names form a natural key even when Faker repeats itself."""
    brands = generate_brands(settings, generate_countries(settings), SEED)

    assert brands["brand_name"].n_unique() == brands.height


def test_brands_are_deterministic(settings: MasterDataConfig) -> None:
    """Brand generation is reproducible for a fixed seed."""
    countries = generate_countries(settings)

    assert generate_brands(settings, countries, SEED).equals(
        generate_brands(settings, countries, SEED)
    )


def test_brands_require_countries(settings: MasterDataConfig) -> None:
    """Brands cannot be generated without a country to originate from."""
    empty = generate_countries(settings).clear()

    with pytest.raises(ValueError, match="countries dataset is empty"):
        generate_brands(settings, empty, SEED)


def test_price_band_lookup_falls_back_to_a_default() -> None:
    """An unknown category still receives a usable band."""
    assert price_band_for("Electronics") != price_band_for("Nonexistent Category")
    assert price_band_for("Nonexistent Category").min_price > 0


def test_generated_price_is_above_cost() -> None:
    """The core pricing invariant holds across many samples."""
    rng = random.Random(0)
    band = price_band_for("Electronics")

    for _ in range(500):
        point = generate_price_point(rng, band)
        assert 0 < point.unit_cost < point.list_price


def test_prices_stay_within_an_order_of_the_band() -> None:
    """Sampling is bounded by the configured band, allowing charm rounding."""
    rng = random.Random(0)
    band = price_band_for("Grocery")

    prices = [generate_price_point(rng, band).list_price for _ in range(300)]

    assert min(prices) >= 0.99
    assert max(prices) <= band.max_price * 1.05


def test_invalid_price_band_is_rejected() -> None:
    """A band with an inverted price range is a configuration error."""
    with pytest.raises(ValueError, match="invalid price range"):
        generate_price_point(random.Random(0), PriceBand(100.0, 10.0, 0.1, 0.2))


def test_invalid_margin_band_is_rejected() -> None:
    """A margin of 100 percent would drive cost to zero."""
    with pytest.raises(ValueError, match="invalid margin range"):
        generate_price_point(random.Random(0), PriceBand(1.0, 10.0, 0.1, 1.0))


def test_products_have_sequential_ids_and_unique_skus(
    settings: MasterDataConfig, catalog_inputs: ProductInputs
) -> None:
    """Product ids run from one and SKUs are unique."""
    products = pl.concat(list(iter_product_batches(settings, catalog_inputs, SEED)))

    assert products["product_id"].to_list() == list(range(1, settings.product_count + 1))
    assert products["sku"].n_unique() == products.height


def test_products_are_split_into_batches(
    settings: MasterDataConfig, catalog_inputs: ProductInputs
) -> None:
    """Batching yields ceil(count / batch_size) frames."""
    batches = list(iter_product_batches(settings, catalog_inputs, SEED))

    assert len(batches) == 3
    assert [batch.height for batch in batches] == [15, 15, 10]


def test_batch_size_does_not_change_the_output(
    settings: MasterDataConfig, catalog_inputs: ProductInputs
) -> None:
    """Batching is an implementation detail, not a data change."""
    small = pl.concat(list(iter_product_batches(settings, catalog_inputs, SEED)))
    large_settings = settings.model_copy(update={"batch_size": 10_000})
    large = pl.concat(list(iter_product_batches(large_settings, catalog_inputs, SEED)))

    assert small.equals(large)


def test_products_attach_only_to_leaf_categories(settings: MasterDataConfig) -> None:
    """A product never hangs off an intermediate category."""
    countries = generate_countries(settings)
    cities = generate_cities(settings, SEED)
    categories = generate_categories(settings)
    products = generate_products(
        settings,
        categories,
        generate_brands(settings, countries, SEED),
        generate_suppliers(settings, cities, SEED),
        generate_tax_codes(settings),
        SEED,
    )
    leaf_ids = set(categories.filter(pl.col("is_leaf"))["category_id"].to_list())

    assert set(products["category_id"].to_list()) <= leaf_ids


def test_product_enum_columns_use_known_values(
    settings: MasterDataConfig, catalog_inputs: ProductInputs
) -> None:
    """Status and unit of measure are drawn from the declared enums."""
    products = pl.concat(list(iter_product_batches(settings, catalog_inputs, SEED)))

    assert set(products["status"].to_list()) <= {str(member) for member in ProductStatus}
    assert set(products["unit_of_measure"].to_list()) <= {str(member) for member in UnitOfMeasure}


def test_product_physical_attributes_are_positive(
    settings: MasterDataConfig, catalog_inputs: ProductInputs
) -> None:
    """Weight and dimensions are strictly positive."""
    products = pl.concat(list(iter_product_batches(settings, catalog_inputs, SEED)))

    for column in ("weight_kg", "length_cm", "width_cm", "height_cm"):
        assert products.filter(pl.col(column) <= 0).height == 0


def test_product_currency_is_configurable(
    settings: MasterDataConfig, catalog_inputs: ProductInputs
) -> None:
    """The currency code is stamped onto every product."""
    products = pl.concat(list(iter_product_batches(settings, catalog_inputs, SEED, "GBP")))

    assert set(products["currency_code"].to_list()) == {"GBP"}


def test_products_require_non_empty_inputs(settings: MasterDataConfig) -> None:
    """An empty upstream dataset stops generation with a clear message."""
    countries = generate_countries(settings)
    cities = generate_cities(settings, SEED)
    categories = generate_categories(settings)
    brands = generate_brands(settings, countries, SEED)
    suppliers = generate_suppliers(settings, cities, SEED)
    tax_codes = generate_tax_codes(settings)

    with pytest.raises(ValueError, match="brands dataset is empty"):
        ProductInputs(categories, brands.clear(), suppliers, tax_codes)

    with pytest.raises(ValueError, match="suppliers dataset is empty"):
        ProductInputs(categories, brands, suppliers.clear(), tax_codes)

    with pytest.raises(ValueError, match="tax codes dataset is empty"):
        ProductInputs(categories, brands, suppliers, tax_codes.clear())

    with pytest.raises(ValueError, match="no leaf categories"):
        ProductInputs(categories.clear(), brands, suppliers, tax_codes)
