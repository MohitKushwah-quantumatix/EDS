"""Validation rules for the F003.2 browsing datasets.

Referential integrity is delegated to
:func:`eds.core.validation.referential.validate_referential_integrity` with the
browsing declarations, which covers duplicate ``category_view_id`` and
``search_id`` values and invalid session, customer, category, and
``category_view`` references.

The rules here cover what a schema cannot express: sequence numbering, the
chronology that keeps every view and search inside its session, and the
requirement that a search belongs to the same category as the view it came
from.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.validation.issues import ValidationError, ValidationIssue
from eds.domains.retail.domain.journey.schema import BROWSING_DATASETS
from eds.domains.retail.validation.referential import validate_referential_integrity

__all__ = [
    "assert_valid_browsing_data",
    "validate_browsing_data",
    "validate_category_view_timeline",
    "validate_search_category_consistency",
    "validate_search_results",
    "validate_search_timeline",
    "validate_sequences",
    "validate_view_durations",
]


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


def _sequence_issues(
    frame: pl.DataFrame, dataset: str, group_column: str, sequence_column: str, rule: str
) -> list[ValidationIssue]:
    """Check a sequence column numbers each group 1..n without gaps.

    Args:
        frame: Frame to check.
        dataset: Dataset name for the issue.
        group_column: Column the sequence restarts within.
        sequence_column: The sequence column.
        rule: Rule identifier.

    Returns:
        A single-item list when any group is misnumbered.
    """
    if frame.is_empty():
        return []

    grouped = frame.group_by(group_column).agg(
        pl.col(sequence_column).min().alias("lowest"),
        pl.col(sequence_column).max().alias("highest"),
        pl.col(sequence_column).n_unique().alias("distinct"),
        pl.len().alias("total"),
    )
    broken = grouped.filter(
        (pl.col("lowest") != 1)
        | (pl.col("highest") != pl.col("total"))
        | (pl.col("distinct") != pl.col("total"))
    )
    if broken.is_empty():
        return []
    return [
        ValidationIssue(
            dataset,
            rule,
            f"{broken.height} {group_column} group(s) are not numbered 1..n without gaps",
        )
    ]


def validate_sequences(
    category_views: pl.DataFrame, searches: pl.DataFrame
) -> list[ValidationIssue]:
    """Check view and search sequences start at one and run contiguously.

    Args:
        category_views: The category views dataset.
        searches: The search history dataset.

    Returns:
        Issues for non-positive sequence values or misnumbered groups.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        category_views,
        "category_views",
        "invalid_view_sequence",
        pl.col("view_sequence") < 1,
        "view_sequence >= 1",
    )
    issues += _sequence_issues(
        category_views, "category_views", "session_id", "view_sequence", "invalid_view_sequence"
    )

    issues += _issue_if(
        searches,
        "search_history",
        "invalid_search_sequence",
        pl.col("search_sequence") < 1,
        "search_sequence >= 1",
    )
    issues += _sequence_issues(
        searches, "search_history", "session_id", "search_sequence", "invalid_search_sequence"
    )
    return issues


def validate_view_durations(
    category_views: pl.DataFrame, min_seconds: int, max_seconds: int
) -> list[ValidationIssue]:
    """Check every category view lasted a plausible length of time.

    Args:
        category_views: The category views dataset.
        min_seconds: Shortest permitted view.
        max_seconds: Longest permitted view.

    Returns:
        Issues for non-positive or out-of-range durations.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        category_views,
        "category_views",
        "negative_duration",
        pl.col("duration_seconds") <= 0,
        "duration_seconds > 0",
    )
    issues += _issue_if(
        category_views,
        "category_views",
        "duration_out_of_range",
        (pl.col("duration_seconds") < min_seconds) | (pl.col("duration_seconds") > max_seconds),
        f"{min_seconds} <= duration_seconds <= {max_seconds}",
    )
    return issues


def validate_category_view_timeline(
    category_views: pl.DataFrame, sessions: pl.DataFrame
) -> list[ValidationIssue]:
    """Check every category view sits inside its session.

    Args:
        category_views: The category views dataset.
        sessions: The F003.1 sessions dataset.

    Returns:
        Issues for views starting before the session, or running past its end.
    """
    joined = category_views.join(
        sessions.select("session_id", "start_time", "end_time"),
        on="session_id",
        how="inner",
    )
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        joined,
        "category_views",
        "timestamp_outside_session",
        (pl.col("timestamp") < pl.col("start_time")) | (pl.col("timestamp") > pl.col("end_time")),
        "the view timestamp falls inside its session",
    )
    issues += _issue_if(
        joined,
        "category_views",
        "view_outlasts_session",
        pl.col("timestamp") + pl.duration(seconds=pl.col("duration_seconds")) > pl.col("end_time"),
        "the view ends before its session does",
    )
    return issues


def validate_search_timeline(
    searches: pl.DataFrame, sessions: pl.DataFrame, category_views: pl.DataFrame
) -> list[ValidationIssue]:
    """Check every search sits inside its session and after the first view.

    Args:
        searches: The search history dataset.
        sessions: The F003.1 sessions dataset.
        category_views: The category views dataset.

    Returns:
        Issues for searches outside their session, or preceding the first
        category view of that session.
    """
    issues: list[ValidationIssue] = []

    within_session = searches.join(
        sessions.select("session_id", "start_time", "end_time"),
        on="session_id",
        how="inner",
    )
    issues += _issue_if(
        within_session,
        "search_history",
        "timestamp_outside_session",
        (pl.col("timestamp") < pl.col("start_time")) | (pl.col("timestamp") > pl.col("end_time")),
        "the search timestamp falls inside its session",
    )

    first_views = category_views.group_by("session_id").agg(
        pl.col("timestamp").min().alias("first_view_time")
    )
    after_first = searches.join(first_views, on="session_id", how="inner")
    issues += _issue_if(
        after_first,
        "search_history",
        "search_before_first_view",
        pl.col("timestamp") <= pl.col("first_view_time"),
        "the search happens after the first category view",
    )
    return issues


def validate_search_category_consistency(
    searches: pl.DataFrame, category_views: pl.DataFrame
) -> list[ValidationIssue]:
    """Check a search belongs to the category of the view it came from.

    This is the rule that stops an Electronics visit from producing a search
    for a coffee table.

    Args:
        searches: The search history dataset.
        category_views: The category views dataset.

    Returns:
        Issues where the search category or session differs from its view's.
    """
    joined = searches.join(
        category_views.select(
            "category_view_id",
            pl.col("category_id").alias("view_category_id"),
            pl.col("session_id").alias("view_session_id"),
        ),
        on="category_view_id",
        how="inner",
    )
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        joined,
        "search_history",
        "category_mismatch",
        pl.col("category_id") != pl.col("view_category_id"),
        "the search category matches its category view",
    )
    issues += _issue_if(
        joined,
        "search_history",
        "session_mismatch",
        pl.col("session_id") != pl.col("view_session_id"),
        "the search session matches its category view",
    )
    return issues


def validate_search_results(searches: pl.DataFrame, max_results: int) -> list[ValidationIssue]:
    """Check result counts and click flags are coherent.

    Args:
        searches: The search history dataset.
        max_results: Largest permitted result count.

    Returns:
        Issues for out-of-range counts, empty search text, or a click on a
        search that returned nothing.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        searches,
        "search_history",
        "results_out_of_range",
        (pl.col("results_count") < 0) | (pl.col("results_count") > max_results),
        f"0 <= results_count <= {max_results}",
    )
    issues += _issue_if(
        searches,
        "search_history",
        "clicked_without_results",
        pl.col("clicked_result") & (pl.col("results_count") == 0),
        "a search with no results was not clicked",
    )
    issues += _issue_if(
        searches,
        "search_history",
        "empty_search_text",
        pl.col("search_text").str.strip_chars().str.len_chars() == 0,
        "search_text is not empty",
    )
    return issues


def validate_browsing_data(
    datasets: Mapping[str, pl.DataFrame],
    min_view_seconds: int = 5,
    max_view_seconds: int = 180,
    max_results_count: int = 250,
) -> list[ValidationIssue]:
    """Validate schema, referential integrity, and browsing business rules.

    Args:
        datasets: The browsing datasets plus the upstream datasets they
            reference, keyed by name.
        min_view_seconds: Shortest permitted category view.
        max_view_seconds: Longest permitted category view.
        max_results_count: Largest permitted result count.

    Returns:
        Every issue found. An empty list means the data satisfies the F003.2
        acceptance criteria.
    """
    issues = validate_referential_integrity(datasets, BROWSING_DATASETS)

    category_views = datasets.get("category_views")
    searches = datasets.get("search_history")
    sessions = datasets.get("sessions")

    if category_views is None or searches is None:
        return issues

    issues.extend(validate_sequences(category_views, searches))
    issues.extend(validate_view_durations(category_views, min_view_seconds, max_view_seconds))
    issues.extend(validate_search_category_consistency(searches, category_views))
    issues.extend(validate_search_results(searches, max_results_count))

    if sessions is not None:
        issues.extend(validate_category_view_timeline(category_views, sessions))
        issues.extend(validate_search_timeline(searches, sessions, category_views))
    return issues


def assert_valid_browsing_data(
    datasets: Mapping[str, pl.DataFrame],
    min_view_seconds: int = 5,
    max_view_seconds: int = 180,
    max_results_count: int = 250,
) -> None:
    """Validate browsing datasets and raise if anything is wrong.

    Args:
        datasets: The browsing datasets plus the upstream data they reference.
        min_view_seconds: Shortest permitted category view.
        max_view_seconds: Longest permitted category view.
        max_results_count: Largest permitted result count.

    Raises:
        ValidationError: If any validation issue is found.
    """
    issues = validate_browsing_data(datasets, min_view_seconds, max_view_seconds, max_results_count)
    if issues:
        raise ValidationError(issues)
