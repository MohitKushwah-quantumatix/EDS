"""Tests for customer validation.

Every failure path corrupts a valid bundle and asserts the specific rule
fires, so the tests prove the validators catch real defects.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from eds.config import CustomerConfig
from eds.generators.customer_data import CustomerData
from eds.generators.master_data import MasterData
from eds.validation.customer_validation import (
    assert_valid_customer_data,
    validate_address_cardinality,
    validate_customer_data,
    validate_customer_fields,
    validate_loyalty,
    validate_one_record_per_customer,
)
from eds.validation.issues import ValidationError, ValidationIssue


@pytest.fixture
def datasets(customer_data: CustomerData, master_data: MasterData) -> dict[str, pl.DataFrame]:
    """Return a mutable bundle of customer datasets plus their geography."""
    return {**master_data.datasets, **customer_data.datasets}


@pytest.fixture
def bounds(small_customer_config: CustomerConfig) -> tuple[int, int]:
    """Return the configured address bounds."""
    return small_customer_config.min_addresses, small_customer_config.max_addresses


def rules(issues: list[ValidationIssue]) -> set[str]:
    """Return the rule identifiers present in a list of issues.

    Args:
        issues: Issues to summarise.

    Returns:
        The set of rule names.
    """
    return {issue.rule for issue in issues}


def test_clean_data_produces_no_issues(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """A freshly generated bundle validates cleanly."""
    assert validate_customer_data(datasets, *bounds) == []


def test_assert_valid_passes_on_clean_data(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """The assertion helper does not raise for valid data."""
    assert_valid_customer_data(datasets, *bounds)


def test_duplicate_email_is_detected(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """Email is a declared unique column."""
    datasets["customers"] = datasets["customers"].with_columns(
        pl.lit("same@example.com").alias("email")
    )

    assert "duplicate_unique_column" in rules(validate_customer_data(datasets, *bounds))


def test_duplicate_phone_is_detected(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """Phone is a declared unique column."""
    datasets["customers"] = datasets["customers"].with_columns(
        pl.lit("+1-555-000-0000").alias("phone")
    )

    assert "duplicate_unique_column" in rules(validate_customer_data(datasets, *bounds))


def test_duplicate_customer_number_is_detected(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """Customer number is a declared unique column."""
    datasets["customers"] = datasets["customers"].with_columns(
        pl.lit("CUST-00000001").alias("customer_number")
    )

    assert "duplicate_unique_column" in rules(validate_customer_data(datasets, *bounds))


def test_duplicate_customer_id_is_detected(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """Customer id is the primary key."""
    datasets["customers"] = datasets["customers"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("customer_id")
    )

    assert "duplicate_primary_key" in rules(validate_customer_data(datasets, *bounds))


def test_orphan_city_reference_is_detected(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """An address pointing at a non-existent city is an orphan."""
    datasets["customer_addresses"] = datasets["customer_addresses"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias("city_id")
    )

    issues = validate_customer_data(datasets, *bounds)

    assert "orphan_reference" in rules(issues)
    assert any("cities.city_id" in issue.detail for issue in issues)


def test_orphan_state_reference_is_detected(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """An address pointing at a non-existent state is an orphan."""
    datasets["customer_addresses"] = datasets["customer_addresses"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias("state_id")
    )

    assert "orphan_reference" in rules(validate_customer_data(datasets, *bounds))


def test_orphan_country_reference_is_detected(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """An address pointing at a non-existent country is an orphan."""
    datasets["customer_addresses"] = datasets["customer_addresses"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias("country_id")
    )

    assert "orphan_reference" in rules(validate_customer_data(datasets, *bounds))


def test_orphan_customer_reference_is_detected(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """An address pointing at a non-existent customer is an orphan."""
    datasets["customer_addresses"] = datasets["customer_addresses"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias("customer_id")
    )

    assert "orphan_reference" in rules(validate_customer_data(datasets, *bounds))


def test_customer_without_an_address_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A customer with no address violates the minimum-one rule."""
    customers = datasets["customers"]
    addresses = datasets["customer_addresses"].filter(pl.col("customer_id") != 1)

    issues = validate_address_cardinality(customers, addresses, 1, 2)

    assert "customer_without_address" in rules(issues)


def test_two_primary_addresses_are_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """More than one primary address per customer is a defect."""
    addresses = datasets["customer_addresses"].with_columns(pl.lit(True).alias("is_primary"))

    issues = validate_address_cardinality(datasets["customers"], addresses, 1, 2)

    assert "primary_address_count" in rules(issues)


def test_no_primary_address_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Zero primary addresses is equally a defect."""
    addresses = datasets["customer_addresses"].with_columns(pl.lit(False).alias("is_primary"))

    issues = validate_address_cardinality(datasets["customers"], addresses, 1, 2)

    assert "primary_address_count" in rules(issues)


def test_too_many_addresses_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Exceeding max_addresses is reported."""
    issues = validate_address_cardinality(
        datasets["customers"], datasets["customer_addresses"], 1, 1
    )

    assert "too_many_addresses" in rules(issues)


def test_too_few_addresses_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Falling below min_addresses is reported."""
    issues = validate_address_cardinality(
        datasets["customers"], datasets["customer_addresses"], 3, 4
    )

    assert "too_few_addresses" in rules(issues)


def test_customer_without_a_preference_record_is_detected(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """Every customer must have a preference record."""
    datasets["customer_preferences"] = datasets["customer_preferences"].filter(
        pl.col("customer_id") != 2
    )

    assert "customer_without_record" in rules(validate_customer_data(datasets, *bounds))


def test_customer_without_a_loyalty_record_is_detected(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """Every customer must have a loyalty record."""
    datasets["customer_loyalty"] = datasets["customer_loyalty"].filter(pl.col("customer_id") != 3)

    assert "customer_without_record" in rules(validate_customer_data(datasets, *bounds))


def test_duplicate_one_to_one_record_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Two preference records for one customer is a defect."""
    preferences = datasets["customer_preferences"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("customer_id")
    )

    issues = validate_one_record_per_customer(
        datasets["customers"], preferences, "customer_preferences"
    )

    assert "duplicate_customer_record" in rules(issues)


def test_risk_score_out_of_range_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Risk is a 0-100 score."""
    customers = datasets["customers"].with_columns(pl.lit(150.0).alias("risk_score"))

    assert "risk_score_out_of_range" in rules(validate_customer_fields(customers))


def test_birth_after_registration_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A customer cannot be born after they registered."""
    customers = datasets["customers"].with_columns(
        pl.col("registration_date").alias("date_of_birth")
    )

    assert "birth_after_registration" in rules(validate_customer_fields(customers))


def test_updated_before_created_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Audit timestamps must be ordered."""
    customers = datasets["customers"].with_columns(
        (pl.col("created_at") - pl.duration(days=1)).alias("updated_at")
    )

    assert "updated_before_created" in rules(validate_customer_fields(customers))


def test_negative_points_are_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A negative points balance is a defect."""
    loyalty = datasets["customer_loyalty"].with_columns(
        pl.lit(-10).cast(pl.Int64).alias("points_balance")
    )

    assert "negative_points" in rules(validate_loyalty(datasets["customers"], loyalty))


def test_enrolment_before_registration_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Enrolling before registering is impossible."""
    loyalty = datasets["customer_loyalty"].with_columns(
        pl.lit(date(1990, 1, 1)).alias("enrollment_date")
    )

    assert "enrolled_before_registration" in rules(validate_loyalty(datasets["customers"], loyalty))


def test_missing_customers_dataset_is_reported(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """A missing customers dataset is an integrity failure."""
    del datasets["customers"]

    assert "missing_dataset" in rules(validate_customer_data(datasets, *bounds))


def test_dtype_mismatch_is_detected(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """A wrong dtype would corrupt the exported Parquet schema."""
    datasets["customers"] = datasets["customers"].with_columns(pl.col("customer_id").cast(pl.Int32))

    assert "dtype_mismatch" in rules(validate_customer_data(datasets, *bounds))


def test_assert_valid_raises_on_corrupt_data(
    datasets: dict[str, pl.DataFrame], bounds: tuple[int, int]
) -> None:
    """The assertion helper raises when the data is broken."""
    datasets["customer_addresses"] = datasets["customer_addresses"].with_columns(
        pl.lit(True).alias("is_primary")
    )

    with pytest.raises(ValidationError, match="primary_address_count"):
        assert_valid_customer_data(datasets, *bounds)


def test_master_data_validation_still_works(master_data: MasterData) -> None:
    """Generalising the referential validator did not break F001."""
    from eds.validation.master_data import validate_master_data

    assert validate_master_data(master_data.datasets) == []
