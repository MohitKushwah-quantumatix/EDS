"""Tests for referential integrity and business rule validation.

Each failure path deliberately corrupts a valid bundle, so the tests prove the
validators catch real defects rather than merely passing on clean data.
"""

from __future__ import annotations

import polars as pl
import pytest

from eds.domain.geography.schema import COUNTRIES
from eds.generators.master_data import MasterData
from eds.validation.business_rules import (
    validate_business_rules,
    validate_categories,
    validate_inventory,
    validate_products,
    validate_suppliers,
    validate_warehouses,
)
from eds.validation.issues import ValidationError, ValidationIssue, format_issues
from eds.validation.master_data import assert_valid_master_data, validate_master_data
from eds.validation.referential import (
    validate_foreign_keys,
    validate_primary_key,
    validate_referential_integrity,
    validate_schema,
)


@pytest.fixture
def datasets(master_data: MasterData) -> dict[str, pl.DataFrame]:
    """Return a mutable copy of the generated datasets."""
    return dict(master_data.datasets)


def rules(issues: list[ValidationIssue]) -> set[str]:
    """Return the rule identifiers present in a list of issues.

    Args:
        issues: Issues to summarise.

    Returns:
        The set of rule names.
    """
    return {issue.rule for issue in issues}


def test_clean_data_produces_no_issues(datasets: dict[str, pl.DataFrame]) -> None:
    """A freshly generated bundle validates cleanly."""
    assert validate_master_data(datasets) == []


def test_assert_valid_passes_on_clean_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper does not raise for valid data."""
    assert_valid_master_data(datasets)


def test_missing_dataset_is_reported(datasets: dict[str, pl.DataFrame]) -> None:
    """A dataset that was never generated is an integrity failure."""
    del datasets["brands"]

    assert "missing_dataset" in rules(validate_referential_integrity(datasets))


def test_orphan_foreign_key_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A product pointing at a non-existent brand is an orphan."""
    datasets["products"] = datasets["products"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias("brand_id")
    )

    issues = validate_referential_integrity(datasets)

    assert "orphan_reference" in rules(issues)
    assert any("brands.brand_id" in issue.detail for issue in issues)


def test_null_in_non_nullable_foreign_key_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A null supplier on a product is not permitted."""
    datasets["products"] = datasets["products"].with_columns(
        pl.lit(None).cast(pl.Int64).alias("supplier_id")
    )

    assert "null_foreign_key" in rules(validate_referential_integrity(datasets))


def test_nullable_foreign_key_allows_nulls(datasets: dict[str, pl.DataFrame]) -> None:
    """Root categories legitimately have a null parent."""
    issues = validate_referential_integrity(datasets)

    assert not any(
        issue.dataset == "categories" and issue.rule == "null_foreign_key" for issue in issues
    )


def test_duplicate_primary_key_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Repeating a primary key value is a defect."""
    datasets["brands"] = datasets["brands"].with_columns(pl.lit(1).cast(pl.Int64).alias("brand_id"))

    assert "duplicate_primary_key" in rules(validate_referential_integrity(datasets))


def test_null_primary_key_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A null identifier is a defect."""
    datasets["brands"] = datasets["brands"].with_columns(
        pl.lit(None).cast(pl.Int64).alias("brand_id")
    )

    assert "null_primary_key" in rules(validate_referential_integrity(datasets))


def test_duplicate_unique_column_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """SKUs must not repeat."""
    datasets["products"] = datasets["products"].with_columns(pl.lit("SKU-1").alias("sku"))

    assert "duplicate_unique_column" in rules(validate_referential_integrity(datasets))


def test_dtype_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A column with the wrong dtype would corrupt the Parquet schema."""
    datasets["brands"] = datasets["brands"].with_columns(
        pl.col("brand_id").cast(pl.Int32).alias("brand_id")
    )

    assert "dtype_mismatch" in rules(validate_schema_for(datasets, "brands"))


def validate_schema_for(datasets: dict[str, pl.DataFrame], name: str) -> list[ValidationIssue]:
    """Run schema validation for one dataset.

    Args:
        datasets: All datasets.
        name: Dataset to validate.

    Returns:
        The schema issues found.
    """
    from eds.domain.master_data import dataset_by_name

    return validate_schema(dataset_by_name(name), datasets[name])


def test_unexpected_column_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """An extra column is refused, keeping output schemas stable."""
    datasets["brands"] = datasets["brands"].with_columns(pl.lit(1).alias("surprise"))

    assert "unexpected_column" in rules(validate_schema_for(datasets, "brands"))


def test_missing_column_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A dropped column is reported rather than silently exported."""
    datasets["brands"] = datasets["brands"].drop("is_premium")

    assert "missing_column" in rules(validate_schema_for(datasets, "brands"))


def test_missing_primary_key_column_is_reported() -> None:
    """A frame without its key column reports one clear issue."""
    frame = pl.DataFrame({"country_code": ["US"]})

    issues = validate_primary_key(COUNTRIES, frame)

    assert rules(issues) == {"missing_primary_key"}


def test_missing_reference_dataset_is_reported(datasets: dict[str, pl.DataFrame]) -> None:
    """A foreign key whose target is absent is reported precisely."""
    from eds.domain.master_data import dataset_by_name

    issues = validate_foreign_keys(
        dataset_by_name("products"), datasets["products"], {"products": datasets["products"]}
    )

    assert "missing_reference_dataset" in rules(issues)


def test_cost_above_price_is_a_business_rule_violation(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Selling below cost is caught by the pricing rule."""
    datasets["products"] = datasets["products"].with_columns(
        (pl.col("list_price") * 2).alias("unit_cost")
    )

    assert "cost_not_below_price" in rules(validate_products(datasets["products"]))


def test_non_positive_price_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A zero price is not a valid catalog entry."""
    products = datasets["products"].with_columns(pl.lit(0.0).alias("list_price"))

    assert "non_positive_price" in rules(validate_products(products))


def test_over_reservation_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Reserving more than is on hand is impossible."""
    inventory = datasets["inventory"].with_columns(
        (pl.col("quantity_on_hand") + 1).alias("quantity_reserved")
    )

    assert "over_reserved" in rules(validate_inventory(inventory))


def test_negative_stock_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Negative stock on hand is a defect."""
    inventory = datasets["inventory"].with_columns(
        pl.lit(-5).cast(pl.Int64).alias("quantity_on_hand")
    )

    assert "negative_quantity" in rules(validate_inventory(inventory))


def test_non_positive_capacity_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A warehouse must be able to hold something."""
    warehouses = datasets["warehouses"].with_columns(
        pl.lit(0).cast(pl.Int64).alias("capacity_units")
    )

    assert "non_positive_capacity" in rules(validate_warehouses(warehouses))


def test_out_of_range_coordinates_are_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Coordinates off the globe are caught."""
    warehouses = datasets["warehouses"].with_columns(pl.lit(120.0).alias("latitude"))

    assert "latitude_out_of_range" in rules(validate_warehouses(warehouses))


def test_reliability_outside_zero_to_one_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Reliability is a probability."""
    suppliers = datasets["suppliers"].with_columns(pl.lit(1.5).alias("reliability_score"))

    assert "reliability_out_of_range" in rules(validate_suppliers(suppliers))


def test_root_category_with_a_parent_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A level-1 category cannot have a parent."""
    categories = datasets["categories"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("parent_category_id")
    )

    assert "root_with_parent" in rules(validate_categories(categories))


def test_tree_without_leaves_is_detected() -> None:
    """A category tree with no leaves cannot hold products."""
    categories = pl.DataFrame(
        {
            "category_id": [1],
            "parent_category_id": [None],
            "category_code": ["CAT-000001"],
            "category_name": ["Root"],
            "category_path": ["Root"],
            "level": [1],
            "is_leaf": [False],
        },
        schema_overrides={"parent_category_id": pl.Int64},
    )

    assert "no_leaf_categories" in rules(validate_categories(categories))


def test_business_rules_skip_absent_datasets() -> None:
    """Business rules do not fail when a dataset was not generated."""
    assert validate_business_rules({}) == []


def test_validation_error_lists_every_issue() -> None:
    """The raised error carries and renders all issues."""
    issues = [
        ValidationIssue("products", "rule_a", "detail a"),
        ValidationIssue("inventory", "rule_b", "detail b"),
    ]

    error = ValidationError(issues)

    assert error.issues == tuple(issues)
    assert "rule_a" in str(error)
    assert "rule_b" in str(error)


def test_assert_valid_raises_on_corrupt_data(datasets: dict[str, pl.DataFrame]) -> None:
    """The assertion helper raises when the data is broken."""
    datasets["products"] = datasets["products"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias("brand_id")
    )

    with pytest.raises(ValidationError, match="orphan_reference"):
        assert_valid_master_data(datasets)


def test_format_issues_handles_an_empty_list() -> None:
    """Rendering no issues is explicit rather than blank."""
    assert format_issues([]) == "  (none)"


def test_issue_renders_as_one_line() -> None:
    """An issue reads as a single diagnostic line."""
    issue = ValidationIssue("products", "orphan_reference", "brand_id missing")

    assert str(issue) == "[products] orphan_reference: brand_id missing"
