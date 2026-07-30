"""Tests for journey validation.

Every failure path corrupts a valid bundle and asserts the specific rule
fires, covering each check the F003.1 specification lists.
"""

from __future__ import annotations

from datetime import date, datetime

import polars as pl
import pytest

from eds.config import SimulationConfig
from eds.generators.journey.journey import JourneyData
from eds.validation.issues import ValidationError, ValidationIssue
from eds.validation.journey_validation import (
    assert_valid_journey_data,
    validate_journey_data,
    validate_persona_coverage,
    validate_persona_fields,
    validate_session_fields,
    validate_session_timeline,
)


@pytest.fixture
def datasets(
    journey_data: JourneyData, journey_upstream: dict[str, pl.DataFrame]
) -> dict[str, pl.DataFrame]:
    """Return a mutable bundle of journey datasets plus their upstream data."""
    return {**journey_upstream, **journey_data.datasets}


@pytest.fixture
def reference(journey_simulation_config: SimulationConfig) -> date:
    """Return the configured reference date."""
    return journey_simulation_config.customers.reference_date


def rules(issues: list[ValidationIssue]) -> set[str]:
    """Return the rule identifiers present in a list of issues.

    Args:
        issues: Issues to summarise.

    Returns:
        The set of rule names.
    """
    return {issue.rule for issue in issues}


def test_clean_data_produces_no_issues(datasets: dict[str, pl.DataFrame], reference: date) -> None:
    """A freshly generated bundle validates cleanly."""
    assert validate_journey_data(datasets, reference) == []


def test_assert_valid_passes_on_clean_data(
    datasets: dict[str, pl.DataFrame], reference: date
) -> None:
    """The assertion helper does not raise for valid data."""
    assert_valid_journey_data(datasets, reference)


def test_duplicate_session_ids_are_detected(
    datasets: dict[str, pl.DataFrame], reference: date
) -> None:
    """Session id is the primary key."""
    datasets["sessions"] = datasets["sessions"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("session_id")
    )

    assert "duplicate_primary_key" in rules(validate_journey_data(datasets, reference))


def test_duplicate_persona_ids_are_detected(
    datasets: dict[str, pl.DataFrame], reference: date
) -> None:
    """Persona id is the primary key."""
    datasets["customer_personas"] = datasets["customer_personas"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("persona_id")
    )

    assert "duplicate_primary_key" in rules(validate_journey_data(datasets, reference))


def test_invalid_customer_id_on_a_session_is_detected(
    datasets: dict[str, pl.DataFrame], reference: date
) -> None:
    """A session pointing at a non-existent customer is an orphan."""
    datasets["sessions"] = datasets["sessions"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias("customer_id")
    )

    issues = validate_journey_data(datasets, reference)

    assert "orphan_reference" in rules(issues)
    assert any("customers.customer_id" in issue.detail for issue in issues)


def test_invalid_customer_id_on_a_persona_is_detected(
    datasets: dict[str, pl.DataFrame], reference: date
) -> None:
    """A persona pointing at a non-existent customer is an orphan."""
    datasets["customer_personas"] = datasets["customer_personas"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias("customer_id")
    )

    assert "orphan_reference" in rules(validate_journey_data(datasets, reference))


@pytest.mark.parametrize("column", ["country_id", "state_id", "city_id"])
def test_invalid_geography_is_detected(
    datasets: dict[str, pl.DataFrame], reference: date, column: str
) -> None:
    """Each geography key is checked against F001."""
    datasets["sessions"] = datasets["sessions"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias(column)
    )

    assert "orphan_reference" in rules(validate_journey_data(datasets, reference))


def test_customer_without_a_persona_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Every customer must have a persona."""
    personas = datasets["customer_personas"].filter(pl.col("customer_id") != 1)

    issues = validate_persona_coverage(datasets["customers"], personas)

    assert "customer_without_persona" in rules(issues)


def test_duplicate_persona_for_one_customer_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """Two personas for one customer is a defect."""
    personas = datasets["customer_personas"].with_columns(
        pl.lit(1).cast(pl.Int64).alias("customer_id")
    )

    issues = validate_persona_coverage(datasets["customers"], personas)

    assert "duplicate_persona" in rules(issues)


def test_session_end_before_start_is_detected(
    datasets: dict[str, pl.DataFrame], reference: date
) -> None:
    """A session cannot end before it begins."""
    sessions = datasets["sessions"].with_columns(
        (pl.col("start_time") - pl.duration(seconds=1)).alias("end_time")
    )

    issues = validate_session_timeline(sessions, datasets["customers"], reference, 5)

    assert "end_before_start" in rules(issues)


def test_negative_duration_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Duration must be positive."""
    sessions = datasets["sessions"].with_columns(
        pl.lit(-10).cast(pl.Int64).alias("duration_seconds")
    )

    assert "negative_duration" in rules(validate_session_fields(sessions, 25))


def test_session_before_registration_is_detected(
    datasets: dict[str, pl.DataFrame], reference: date
) -> None:
    """A session cannot predate its customer's registration."""
    sessions = datasets["sessions"].with_columns(pl.lit(datetime(2000, 1, 1)).alias("start_time"))

    issues = validate_session_timeline(sessions, datasets["customers"], reference, 5)

    assert "session_before_registration" in rules(issues)


def test_session_outside_the_window_is_detected(
    datasets: dict[str, pl.DataFrame], reference: date
) -> None:
    """Sessions must fall within the configured window."""
    sessions = datasets["sessions"].with_columns(pl.lit(datetime(1990, 1, 1)).alias("start_time"))

    issues = validate_session_timeline(sessions, datasets["customers"], reference, 5)

    assert "session_outside_window" in rules(issues)


def test_bounce_with_many_pages_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A bounce views exactly one page."""
    sessions = datasets["sessions"].with_columns(pl.lit(True).alias("bounce"))

    assert "bounce_page_count" in rules(validate_session_fields(sessions, 25))


def test_non_bounce_with_one_page_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A non-bounce views at least two pages."""
    sessions = datasets["sessions"].with_columns(pl.lit(False).alias("bounce"))

    assert "non_bounce_page_count" in rules(validate_session_fields(sessions, 25))


def test_pages_above_the_maximum_are_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """The page ceiling is enforced."""
    assert "pages_above_maximum" in rules(validate_session_fields(datasets["sessions"], 3))


def test_duration_mismatch_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Duration must agree with the timestamps."""
    sessions = datasets["sessions"].with_columns(
        (pl.col("duration_seconds") + 1).alias("duration_seconds")
    )

    assert "duration_mismatch" in rules(validate_session_fields(sessions, 25))


def test_probability_out_of_range_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """Trait scores are probabilities."""
    personas = datasets["customer_personas"].with_columns(pl.lit(1.5).alias("purchase_intent"))

    assert "probability_out_of_range" in rules(validate_persona_fields(personas))


def test_purchase_above_cart_is_detected(datasets: dict[str, pl.DataFrame]) -> None:
    """A purchase probability cannot exceed the cart probability."""
    personas = datasets["customer_personas"].with_columns(
        pl.lit(1.0).alias("purchase_probability"), pl.lit(0.1).alias("cart_probability")
    )

    assert "purchase_above_cart" in rules(validate_persona_fields(personas))


def test_negative_session_frequency_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """A negative session count is a defect."""
    personas = datasets["customer_personas"].with_columns(
        pl.lit(-1).cast(pl.Int64).alias("session_frequency")
    )

    assert "negative_session_frequency" in rules(validate_persona_fields(personas))


def test_non_positive_average_duration_is_detected(
    datasets: dict[str, pl.DataFrame],
) -> None:
    """An average session length of zero is a defect."""
    personas = datasets["customer_personas"].with_columns(
        pl.lit(0.0).alias("average_session_minutes")
    )

    assert "non_positive_session_duration" in rules(validate_persona_fields(personas))


def test_missing_dataset_is_reported(datasets: dict[str, pl.DataFrame], reference: date) -> None:
    """A dataset that was never generated is an integrity failure."""
    del datasets["sessions"]

    assert "missing_dataset" in rules(validate_journey_data(datasets, reference))


def test_dtype_mismatch_is_detected(datasets: dict[str, pl.DataFrame], reference: date) -> None:
    """A wrong dtype would corrupt the exported Parquet schema."""
    datasets["sessions"] = datasets["sessions"].with_columns(pl.col("session_id").cast(pl.Int32))

    assert "dtype_mismatch" in rules(validate_journey_data(datasets, reference))


def test_assert_valid_raises_on_corrupt_data(
    datasets: dict[str, pl.DataFrame], reference: date
) -> None:
    """The assertion helper raises when the data is broken."""
    datasets["sessions"] = datasets["sessions"].with_columns(
        pl.lit(999_999).cast(pl.Int64).alias("city_id")
    )

    with pytest.raises(ValidationError, match="orphan_reference"):
        assert_valid_journey_data(datasets, reference)


def test_earlier_features_still_validate(
    journey_upstream: dict[str, pl.DataFrame], journey_simulation_config: SimulationConfig
) -> None:
    """Adding journey declarations did not disturb F001 or F002 validation."""
    from eds.validation.customer_validation import validate_customer_data
    from eds.validation.master_data import validate_master_data

    assert validate_master_data(journey_upstream) == []
    assert (
        validate_customer_data(
            journey_upstream,
            journey_simulation_config.customers.min_addresses,
            journey_simulation_config.customers.max_addresses,
        )
        == []
    )
