"""Validation rules for the F003.3 engagement datasets.

Referential integrity is delegated to
:func:`eds.core.validation.referential.validate_referential_integrity` with the
engagement declarations, which covers duplicate ``product_view_id`` and
``wishlist_id`` values and invalid customer, session, category view, search,
category, and product references.

The rules here cover what a schema cannot express: that a viewed product
really sits under the category being browsed, that a search-sourced view
points at a search in the same category, that timestamps respect the journey's
order, and that a customer never saves the same product twice.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.validation.issues import ValidationError, ValidationIssue
from eds.domains.retail.domain.journey.schema import ENGAGEMENT_DATASETS
from eds.domains.retail.validation.referential import validate_referential_integrity

__all__ = [
    "assert_valid_engagement_data",
    "validate_engagement_data",
    "validate_product_category_containment",
    "validate_product_view_sequences",
    "validate_product_view_timeline",
    "validate_search_source",
    "validate_view_durations",
    "validate_wishlist_origin",
    "validate_wishlist_timeline",
    "validate_wishlist_uniqueness",
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


def validate_product_category_containment(
    product_views: pl.DataFrame,
    category_views: pl.DataFrame,
    categories: pl.DataFrame,
    products: pl.DataFrame,
) -> list[ValidationIssue]:
    """Check each viewed product sits under the category being browsed.

    F001 attaches products to leaf categories while F003.2 browses categories
    at every level, so containment is checked by category path: the product's
    own category must be the browsed category or a descendant of it.

    Args:
        product_views: The product views dataset.
        category_views: The F003.2 category views dataset.
        categories: The F001 categories dataset.
        products: The F001 products dataset.

    Returns:
        Issues where the view's category differs from its category view's, or
        the product does not sit under that category.
    """
    issues: list[ValidationIssue] = []

    inherited = product_views.join(
        category_views.select(
            "category_view_id", pl.col("category_id").alias("browsed_category_id")
        ),
        on="category_view_id",
        how="inner",
    )
    issues += _issue_if(
        inherited,
        "product_views",
        "category_mismatch",
        pl.col("category_id") != pl.col("browsed_category_id"),
        "the product view category matches its category view",
    )

    paths = categories.select(pl.col("category_id"), pl.col("category_path").alias("browsed_path"))
    product_paths = products.select(
        "product_id", pl.col("category_id").alias("product_category_id")
    ).join(
        categories.select(
            pl.col("category_id").alias("product_category_id"),
            pl.col("category_path").alias("product_path"),
        ),
        on="product_category_id",
        how="inner",
    )

    resolved = product_views.join(paths, on="category_id", how="inner").join(
        product_paths, on="product_id", how="inner"
    )
    issues += _issue_if(
        resolved,
        "product_views",
        "product_outside_category",
        ~(
            (pl.col("product_path") == pl.col("browsed_path"))
            | pl.col("product_path").str.starts_with(pl.col("browsed_path") + "/")
        ),
        "the product sits under the browsed category",
    )
    return issues


def validate_search_source(
    product_views: pl.DataFrame, searches: pl.DataFrame
) -> list[ValidationIssue]:
    """Check search-sourced views point at a matching search.

    Args:
        product_views: The product views dataset.
        searches: The F003.2 search history dataset.

    Returns:
        Issues for a search-sourced view without a search, a non-search view
        carrying one, or a search whose category or session disagrees.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        product_views,
        "product_views",
        "search_source_without_search",
        (pl.col("view_source") == "SEARCH") & pl.col("search_id").is_null(),
        "a search-sourced view references a search",
    )
    issues += _issue_if(
        product_views,
        "product_views",
        "search_on_non_search_source",
        (pl.col("view_source") != "SEARCH") & pl.col("search_id").is_not_null(),
        "only a search-sourced view references a search",
    )

    joined = product_views.filter(pl.col("search_id").is_not_null()).join(
        searches.select(
            "search_id",
            pl.col("category_id").alias("search_category_id"),
            pl.col("session_id").alias("search_session_id"),
            pl.col("timestamp").alias("search_time"),
        ),
        on="search_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "product_views",
        "search_category_mismatch",
        pl.col("category_id") != pl.col("search_category_id"),
        "the search category matches the product view category",
    )
    issues += _issue_if(
        joined,
        "product_views",
        "search_session_mismatch",
        pl.col("session_id") != pl.col("search_session_id"),
        "the search session matches the product view session",
    )
    issues += _issue_if(
        joined,
        "product_views",
        "view_before_search",
        pl.col("timestamp") <= pl.col("search_time"),
        "the product view happens after the search that led to it",
    )
    return issues


def validate_view_durations(
    product_views: pl.DataFrame, min_seconds: int, max_seconds: int
) -> list[ValidationIssue]:
    """Check every product view lasted a plausible length of time.

    Args:
        product_views: The product views dataset.
        min_seconds: Shortest permitted view.
        max_seconds: Longest permitted view.

    Returns:
        Issues for non-positive or out-of-range durations.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        product_views,
        "product_views",
        "negative_duration",
        pl.col("view_duration_seconds") <= 0,
        "view_duration_seconds > 0",
    )
    issues += _issue_if(
        product_views,
        "product_views",
        "duration_out_of_range",
        (pl.col("view_duration_seconds") < min_seconds)
        | (pl.col("view_duration_seconds") > max_seconds),
        f"{min_seconds} <= view_duration_seconds <= {max_seconds}",
    )
    return issues


def validate_product_view_sequences(product_views: pl.DataFrame) -> list[ValidationIssue]:
    """Check view sequences number each session from one without gaps.

    Args:
        product_views: The product views dataset.

    Returns:
        Issues for non-positive sequence values or misnumbered sessions.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        product_views,
        "product_views",
        "invalid_view_sequence",
        pl.col("view_sequence") < 1,
        "view_sequence >= 1",
    )
    if product_views.is_empty():
        return issues

    grouped = product_views.group_by("session_id").agg(
        pl.col("view_sequence").min().alias("lowest"),
        pl.col("view_sequence").max().alias("highest"),
        pl.col("view_sequence").n_unique().alias("distinct"),
        pl.len().alias("total"),
    )
    broken = grouped.filter(
        (pl.col("lowest") != 1)
        | (pl.col("highest") != pl.col("total"))
        | (pl.col("distinct") != pl.col("total"))
    )
    if not broken.is_empty():
        issues.append(
            ValidationIssue(
                "product_views",
                "invalid_view_sequence",
                f"{broken.height} session(s) are not numbered 1..n without gaps",
            )
        )
    return issues


def validate_product_view_timeline(
    product_views: pl.DataFrame, sessions: pl.DataFrame, category_views: pl.DataFrame
) -> list[ValidationIssue]:
    """Check product views sit inside their session and after their category.

    Args:
        product_views: The product views dataset.
        sessions: The F003.1 sessions dataset.
        category_views: The F003.2 category views dataset.

    Returns:
        Issues for views outside their session, running past its end, or
        preceding the category view they came from.
    """
    issues: list[ValidationIssue] = []

    within = product_views.join(
        sessions.select("session_id", "start_time", "end_time"),
        on="session_id",
        how="inner",
    )
    issues += _issue_if(
        within,
        "product_views",
        "timestamp_outside_session",
        (pl.col("timestamp") < pl.col("start_time")) | (pl.col("timestamp") > pl.col("end_time")),
        "the view timestamp falls inside its session",
    )
    issues += _issue_if(
        within,
        "product_views",
        "view_outlasts_session",
        pl.col("timestamp") + pl.duration(seconds=pl.col("view_duration_seconds"))
        > pl.col("end_time"),
        "the view ends before its session does",
    )

    after_category = product_views.join(
        category_views.select("category_view_id", pl.col("timestamp").alias("category_time")),
        on="category_view_id",
        how="inner",
    )
    issues += _issue_if(
        after_category,
        "product_views",
        "view_before_category_view",
        pl.col("timestamp") < pl.col("category_time"),
        "the product view happens after the category view it came from",
    )
    return issues


def validate_wishlist_origin(
    wishlists: pl.DataFrame, product_views: pl.DataFrame
) -> list[ValidationIssue]:
    """Check each wishlist entry came from a real product view.

    Args:
        wishlists: The wishlists dataset.
        product_views: The product views dataset.

    Returns:
        Issues where the saved product, customer, or source disagrees with the
        product view it claims to come from.
    """
    joined = wishlists.join(
        product_views.select(
            "product_view_id",
            pl.col("product_id").alias("viewed_product_id"),
            pl.col("customer_id").alias("viewing_customer_id"),
            pl.col("view_source").alias("origin_source"),
        ),
        on="product_view_id",
        how="inner",
    )
    issues: list[ValidationIssue] = []

    if joined.height != wishlists.height:
        issues.append(
            ValidationIssue(
                "wishlists",
                "wishlist_without_product_view",
                f"{wishlists.height - joined.height} entry(ies) reference no product view",
            )
        )

    issues += _issue_if(
        joined,
        "wishlists",
        "product_mismatch",
        pl.col("product_id") != pl.col("viewed_product_id"),
        "the saved product matches the product that was viewed",
    )
    issues += _issue_if(
        joined,
        "wishlists",
        "customer_mismatch",
        pl.col("customer_id") != pl.col("viewing_customer_id"),
        "the saving customer matches the customer who viewed the product",
    )
    issues += _issue_if(
        joined,
        "wishlists",
        "source_mismatch",
        pl.col("added_from_source") != pl.col("origin_source"),
        "the wishlist source matches the product view source",
    )
    return issues


def validate_wishlist_uniqueness(wishlists: pl.DataFrame) -> list[ValidationIssue]:
    """Check no customer saved the same product twice.

    Args:
        wishlists: The wishlists dataset.

    Returns:
        A single issue when any customer holds a duplicate product.
    """
    if wishlists.is_empty():
        return []

    pairs = wishlists.select("customer_id", "product_id")
    duplicates = pairs.height - pairs.n_unique()
    if duplicates:
        return [
            ValidationIssue(
                "wishlists",
                "duplicate_wishlist_product",
                f"{duplicates} entry(ies) repeat a product for the same customer",
            )
        ]
    return []


def validate_wishlist_timeline(
    wishlists: pl.DataFrame, product_views: pl.DataFrame
) -> list[ValidationIssue]:
    """Check each wishlist entry was saved after the product was viewed.

    Args:
        wishlists: The wishlists dataset.
        product_views: The product views dataset.

    Returns:
        Issues where an entry predates the view it came from.
    """
    joined = wishlists.join(
        product_views.select("product_view_id", pl.col("timestamp").alias("view_time")),
        on="product_view_id",
        how="inner",
    )
    return _issue_if(
        joined,
        "wishlists",
        "wishlist_before_product_view",
        pl.col("timestamp") <= pl.col("view_time"),
        "the wishlist entry is saved after the product view",
    )


def validate_engagement_data(
    datasets: Mapping[str, pl.DataFrame],
    min_view_seconds: int = 5,
    max_view_seconds: int = 600,
) -> list[ValidationIssue]:
    """Validate schema, referential integrity, and engagement business rules.

    Args:
        datasets: The engagement datasets plus the upstream datasets they
            reference, keyed by name.
        min_view_seconds: Shortest permitted product view.
        max_view_seconds: Longest permitted product view.

    Returns:
        Every issue found. An empty list means the data satisfies the F003.3
        acceptance criteria.
    """
    issues = validate_referential_integrity(datasets, ENGAGEMENT_DATASETS)

    product_views = datasets.get("product_views")
    wishlists = datasets.get("wishlists")
    if product_views is None or wishlists is None:
        return issues

    issues.extend(validate_view_durations(product_views, min_view_seconds, max_view_seconds))
    issues.extend(validate_product_view_sequences(product_views))
    issues.extend(validate_wishlist_origin(wishlists, product_views))
    issues.extend(validate_wishlist_uniqueness(wishlists))
    issues.extend(validate_wishlist_timeline(wishlists, product_views))

    category_views = datasets.get("category_views")
    categories = datasets.get("categories")
    products = datasets.get("products")
    searches = datasets.get("search_history")
    sessions = datasets.get("sessions")

    if category_views is not None and categories is not None and products is not None:
        issues.extend(
            validate_product_category_containment(
                product_views, category_views, categories, products
            )
        )
    if searches is not None:
        issues.extend(validate_search_source(product_views, searches))
    if sessions is not None and category_views is not None:
        issues.extend(validate_product_view_timeline(product_views, sessions, category_views))
    return issues


def assert_valid_engagement_data(
    datasets: Mapping[str, pl.DataFrame],
    min_view_seconds: int = 5,
    max_view_seconds: int = 600,
) -> None:
    """Validate engagement datasets and raise if anything is wrong.

    Args:
        datasets: The engagement datasets plus the upstream data they use.
        min_view_seconds: Shortest permitted product view.
        max_view_seconds: Longest permitted product view.

    Raises:
        ValidationError: If any validation issue is found.
    """
    issues = validate_engagement_data(datasets, min_view_seconds, max_view_seconds)
    if issues:
        raise ValidationError(issues)
