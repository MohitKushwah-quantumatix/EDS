"""Validation rules for the F003.1 journey datasets.

Referential integrity is delegated to
:func:`eds.core.validation.referential.validate_referential_integrity` with the
journey declarations, which covers duplicate session ids, duplicate persona
ids, invalid customer ids, and invalid geography.

The rules here cover what a schema cannot express: persona coverage, session
chronology, and the page and duration relationships.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

import polars as pl

from eds.core.validation.issues import ValidationError, ValidationIssue
from eds.domains.retail.domain.journey.schema import JOURNEY_DATASETS
from eds.domains.retail.validation.referential import validate_referential_integrity

__all__ = [
    "assert_valid_journey_data",
    "validate_journey_data",
    "validate_persona_coverage",
    "validate_persona_fields",
    "validate_session_fields",
    "validate_session_timeline",
]

_MAX_REPORTED = 5
_DAYS_PER_YEAR = 365

_PROBABILITY_COLUMNS = (
    "purchase_intent",
    "price_sensitivity",
    "brand_loyalty",
    "research_depth",
    "wishlist_probability",
    "cart_probability",
    "purchase_probability",
)


def _sample_ids(values: list[int]) -> str:
    """Render a short sample of offending identifiers.

    Args:
        values: Offending identifiers.

    Returns:
        A comma-separated sample, truncated with a count when long.
    """
    head = ", ".join(str(value) for value in values[:_MAX_REPORTED])
    if len(values) > _MAX_REPORTED:
        return f"{head}, ... ({len(values)} total)"
    return head


def _issue_if(
    frame: pl.DataFrame, dataset: str, rule: str, predicate: pl.Expr, message: str
) -> list[ValidationIssue]:
    """Return one issue when any row violates a rule.

    Args:
        frame: Frame to check.
        dataset: Dataset name for the issue.
        rule: Rule identifier.
        predicate: Expression that is true for violating rows.
        message: Description of what the rule requires.

    Returns:
        A single-item list when violations exist, otherwise an empty list.
    """
    count = frame.filter(predicate).height
    if count:
        return [ValidationIssue(dataset, rule, f"{count} row(s) violate: {message}")]
    return []


def validate_persona_coverage(
    customers: pl.DataFrame, personas: pl.DataFrame
) -> list[ValidationIssue]:
    """Check every customer has exactly one persona.

    Args:
        customers: The F002 customers dataset.
        personas: The generated personas dataset.

    Returns:
        Issues for customers with no persona and for duplicated personas.
    """
    issues: list[ValidationIssue] = []
    covered = set(personas["customer_id"].to_list())
    missing = [
        customer_id
        for customer_id in customers["customer_id"].to_list()
        if customer_id not in covered
    ]
    if missing:
        issues.append(
            ValidationIssue(
                "customer_personas",
                "customer_without_persona",
                f"customer(s) have no persona: {_sample_ids(missing)}",
            )
        )

    duplicates = personas.height - personas["customer_id"].n_unique()
    if duplicates:
        issues.append(
            ValidationIssue(
                "customer_personas",
                "duplicate_persona",
                f"{duplicates} customer(s) have more than one persona",
            )
        )
    return issues


def validate_persona_fields(personas: pl.DataFrame) -> list[ValidationIssue]:
    """Check persona trait scores are coherent.

    Args:
        personas: The generated personas dataset.

    Returns:
        Issues for scores outside zero to one, a negative session frequency,
        a non-positive average duration, or a purchase probability above the
        cart probability.
    """
    issues: list[ValidationIssue] = []

    for column in _PROBABILITY_COLUMNS:
        issues += _issue_if(
            personas,
            "customer_personas",
            "probability_out_of_range",
            (pl.col(column) < 0.0) | (pl.col(column) > 1.0),
            f"0 <= {column} <= 1",
        )

    issues += _issue_if(
        personas,
        "customer_personas",
        "negative_session_frequency",
        pl.col("session_frequency") < 0,
        "session_frequency >= 0",
    )
    issues += _issue_if(
        personas,
        "customer_personas",
        "non_positive_session_duration",
        pl.col("average_session_minutes") <= 0,
        "average_session_minutes > 0",
    )
    issues += _issue_if(
        personas,
        "customer_personas",
        "purchase_above_cart",
        pl.col("purchase_probability") > pl.col("cart_probability"),
        "purchase_probability <= cart_probability",
    )
    return issues


def validate_session_fields(sessions: pl.DataFrame, max_pages_viewed: int) -> list[ValidationIssue]:
    """Check session page counts and durations.

    Args:
        sessions: The generated sessions dataset.
        max_pages_viewed: Upper bound on pages in a non-bounce session.

    Returns:
        Issues for a negative duration, a bounce that viewed more than one
        page, a non-bounce that viewed fewer than two, a page count above the
        configured ceiling, or a duration inconsistent with the timestamps.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        sessions,
        "sessions",
        "negative_duration",
        pl.col("duration_seconds") <= 0,
        "duration_seconds > 0",
    )
    issues += _issue_if(
        sessions,
        "sessions",
        "bounce_page_count",
        pl.col("bounce") & (pl.col("pages_viewed") != 1),
        "a bounce views exactly one page",
    )
    issues += _issue_if(
        sessions,
        "sessions",
        "non_bounce_page_count",
        ~pl.col("bounce") & (pl.col("pages_viewed") < 2),
        "a non-bounce views at least two pages",
    )
    issues += _issue_if(
        sessions,
        "sessions",
        "pages_above_maximum",
        pl.col("pages_viewed") > max_pages_viewed,
        f"pages_viewed <= {max_pages_viewed}",
    )
    issues += _issue_if(
        sessions,
        "sessions",
        "duration_mismatch",
        (pl.col("end_time") - pl.col("start_time")).dt.total_seconds()
        != pl.col("duration_seconds"),
        "duration_seconds equals end_time minus start_time",
    )
    return issues


def validate_session_timeline(
    sessions: pl.DataFrame,
    customers: pl.DataFrame,
    reference_date: date,
    session_years: int,
) -> list[ValidationIssue]:
    """Check session chronology against the customer timeline.

    Args:
        sessions: The generated sessions dataset.
        customers: The F002 customers dataset.
        reference_date: The dataset's as-of date.
        session_years: The window sessions must fall within.

    Returns:
        Issues for sessions ending before they start, starting before the
        customer registered, or falling outside the configured window.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        sessions,
        "sessions",
        "end_before_start",
        pl.col("end_time") <= pl.col("start_time"),
        "end_time > start_time",
    )

    joined = sessions.join(
        customers.select("customer_id", "registration_date"), on="customer_id", how="inner"
    )
    issues += _issue_if(
        joined,
        "sessions",
        "session_before_registration",
        pl.col("start_time").dt.date() < pl.col("registration_date"),
        "start_time is before registration_date",
    )

    earliest = reference_date - timedelta(days=session_years * _DAYS_PER_YEAR)
    issues += _issue_if(
        sessions,
        "sessions",
        "session_outside_window",
        (pl.col("start_time").dt.date() < earliest)
        | (pl.col("start_time").dt.date() > reference_date),
        f"sessions fall between {earliest} and {reference_date}",
    )
    return issues


def validate_journey_data(
    datasets: Mapping[str, pl.DataFrame],
    reference_date: date,
    session_years: int = 5,
    max_pages_viewed: int = 25,
) -> list[ValidationIssue]:
    """Validate schema, referential integrity, and journey business rules.

    Args:
        datasets: The journey datasets plus the upstream datasets they
            reference, keyed by name.
        reference_date: The dataset's as-of date.
        session_years: The window sessions must fall within.
        max_pages_viewed: Upper bound on pages in a non-bounce session.

    Returns:
        Every issue found. An empty list means the data satisfies the F003.1
        acceptance criteria.
    """
    issues = validate_referential_integrity(datasets, JOURNEY_DATASETS)

    personas = datasets.get("customer_personas")
    sessions = datasets.get("sessions")
    customers = datasets.get("customers")

    if personas is not None:
        issues.extend(validate_persona_fields(personas))
        if customers is not None:
            issues.extend(validate_persona_coverage(customers, personas))

    if sessions is not None:
        issues.extend(validate_session_fields(sessions, max_pages_viewed))
        if customers is not None:
            issues.extend(
                validate_session_timeline(sessions, customers, reference_date, session_years)
            )
    return issues


def assert_valid_journey_data(
    datasets: Mapping[str, pl.DataFrame],
    reference_date: date,
    session_years: int = 5,
    max_pages_viewed: int = 25,
) -> None:
    """Validate journey datasets and raise if anything is wrong.

    Args:
        datasets: The journey datasets plus the upstream data they reference.
        reference_date: The dataset's as-of date.
        session_years: The window sessions must fall within.
        max_pages_viewed: Upper bound on pages in a non-bounce session.

    Raises:
        ValidationError: If any validation issue is found.
    """
    issues = validate_journey_data(datasets, reference_date, session_years, max_pages_viewed)
    if issues:
        raise ValidationError(issues)
