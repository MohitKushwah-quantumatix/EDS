"""Validation rules for the F010 review dataset.

Referential integrity is delegated to
:func:`eds.core.validation.referential.validate_referential_integrity` with the
review declaration, which covers duplicate ``review_id``, ``review_number`` and
``shipment_item_id`` values, and invalid shipment item, shipment, order,
product and customer references.

The rules here cover what a schema cannot express: that reviews came only from
delivered items that were kept, that the rating is in range and matches the
wording beside it, and that the review was written after the parcel arrived.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import polars as pl

from eds.core.validation.issues import ValidationError, ValidationIssue
from eds.domains.retail.domain.commerce.enums import ShipmentStatus
from eds.domains.retail.domain.commerce.schema import REVIEW_DATASETS
from eds.domains.retail.validation.referential import validate_referential_integrity

__all__ = [
    "MAX_RATING",
    "MIN_RATING",
    "REVIEW_NUMBER_PATTERN",
    "assert_valid_review_data",
    "validate_review_content",
    "validate_review_data",
    "validate_review_eligibility",
    "validate_review_numbers",
    "validate_review_ratings",
    "validate_review_timeline",
]

#: ``REV-YYYYMMDD-000001`` and anything else with the same shape.
REVIEW_NUMBER_PATTERN: Final[str] = r"^[A-Z0-9]{1,8}-\d{8}-\d{6}$"

#: A rating is a whole number of stars, one to five.
MIN_RATING: Final[int] = 1
MAX_RATING: Final[int] = 5


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


def validate_review_eligibility(
    reviews: pl.DataFrame,
    shipments: pl.DataFrame,
    shipment_items: pl.DataFrame,
    return_items: pl.DataFrame,
) -> list[ValidationIssue]:
    """Check reviews came only from delivered items that were kept.

    Args:
        reviews: The reviews dataset.
        shipments: The F008 shipments dataset.
        shipment_items: The F008 shipment items dataset.
        return_items: The F009 return items dataset.

    Returns:
        Issues for a review on an undelivered shipment, on an item that was
        returned, an item reviewed more than once, or a review whose shipment,
        order, product or customer disagrees with the item it describes.
    """
    issues: list[ValidationIssue] = []

    joined = reviews.join(
        shipments.select(
            "shipment_id",
            "current_status",
            pl.col("order_id").alias("shipment_order_id"),
            pl.col("customer_id").alias("shipment_customer_id"),
        ),
        on="shipment_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "reviews",
        "invalid_shipment_status",
        pl.col("current_status") != str(ShipmentStatus.DELIVERED),
        "only a DELIVERED shipment produces a review",
    )
    for column, source in (
        ("order_id", "shipment_order_id"),
        ("customer_id", "shipment_customer_id"),
    ):
        issues += _issue_if(
            joined,
            "reviews",
            "shipment_field_mismatch",
            pl.col(column) != pl.col(source),
            f"{column} matches the shipment the item came in",
        )

    itemised = reviews.join(
        shipment_items.select(
            "shipment_item_id",
            pl.col("shipment_id").alias("item_shipment_id"),
            pl.col("product_id").alias("item_product_id"),
        ),
        on="shipment_item_id",
        how="inner",
    )
    issues += _issue_if(
        itemised,
        "reviews",
        "shipment_item_mismatch",
        pl.col("shipment_id") != pl.col("item_shipment_id"),
        "shipment_id matches the shipment the item belongs to",
    )
    issues += _issue_if(
        itemised,
        "reviews",
        "product_mismatch",
        pl.col("product_id") != pl.col("item_product_id"),
        "product_id is the product the item carried",
    )

    returned = set(return_items["shipment_item_id"].to_list())
    if reviewed_and_returned := returned & set(reviews["shipment_item_id"].to_list()):
        issues.append(
            ValidationIssue(
                "reviews",
                "returned_item_reviewed",
                f"{len(reviewed_and_returned)} returned item(s) produced a review",
            )
        )

    duplicates = reviews.height - reviews["shipment_item_id"].n_unique()
    if duplicates:
        issues.append(
            ValidationIssue(
                "reviews",
                "multiple_reviews_per_item",
                f"{duplicates} item(s) were reviewed more than once",
            )
        )
    return issues


def validate_review_ratings(reviews: pl.DataFrame) -> list[ValidationIssue]:
    """Check the rating is a whole number of stars in range.

    Args:
        reviews: The reviews dataset.

    Returns:
        Issues for a rating outside one to five.
    """
    return _issue_if(
        reviews,
        "reviews",
        "rating_out_of_range",
        (pl.col("rating") < MIN_RATING) | (pl.col("rating") > MAX_RATING),
        f"rating is between {MIN_RATING} and {MAX_RATING}",
    )


def validate_review_content(
    reviews: pl.DataFrame,
    titles: Mapping[int, tuple[str, ...]] | None = None,
    texts: Mapping[int, tuple[str, ...]] | None = None,
) -> list[ValidationIssue]:
    """Check the wording is present and matches the rating beside it.

    Args:
        reviews: The reviews dataset.
        titles: The configured titles per rating. When omitted the membership
            check is skipped, because nothing else knows which phrases were on
            offer.
        texts: The configured bodies per rating, treated the same way.

    Returns:
        Issues for empty wording, a review that is not marked as verified, or
        a phrase that does not belong to its rating.
    """
    issues: list[ValidationIssue] = []

    for column in ("review_title", "review_text"):
        issues += _issue_if(
            reviews,
            "reviews",
            "empty_review_content",
            pl.col(column).str.len_chars() == 0,
            f"{column} is not empty",
        )

    # Every review comes from a delivered shipment, so there is no unverified
    # case: the column is a constant the data must actually carry.
    issues += _issue_if(
        reviews,
        "reviews",
        "unverified_purchase",
        ~pl.col("verified_purchase"),
        "verified_purchase is always true",
    )

    for column, table in (("review_title", titles), ("review_text", texts)):
        if table is None:
            continue
        allowed = pl.DataFrame(
            {
                "rating": [rating for rating, options in table.items() for _ in options],
                column: [phrase for options in table.values() for phrase in options],
                "offered": [True for options in table.values() for _ in options],
            },
            schema={"rating": pl.Int64, column: pl.String, "offered": pl.Boolean},
        )
        issues += _issue_if(
            reviews.join(allowed, on=["rating", column], how="left"),
            "reviews",
            "content_not_offered_for_rating",
            pl.col("offered").is_null(),
            f"{column} is one the rating offers",
        )
    return issues


def validate_review_numbers(reviews: pl.DataFrame) -> list[ValidationIssue]:
    """Check the business review number is well formed and consistent.

    Args:
        reviews: The reviews dataset.

    Returns:
        Issues for a malformed number, one whose embedded date disagrees with
        the day the review was written, or a day that is not numbered from one
        without gaps.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        reviews,
        "reviews",
        "malformed_review_number",
        ~pl.col("review_number").str.contains(REVIEW_NUMBER_PATTERN),
        "review_number matches PREFIX-YYYYMMDD-NNNNNN",
    )

    # The remaining checks read the number apart, so they only run on the rows
    # that are shaped like one. A malformed number has already been reported
    # above; parsing it here would raise rather than add an issue.
    well_formed = reviews.filter(pl.col("review_number").str.contains(REVIEW_NUMBER_PATTERN))
    if well_formed.is_empty():
        return issues

    dated = well_formed.with_columns(pl.col("created_at").dt.date().alias("review_date"))
    issues += _issue_if(
        dated,
        "reviews",
        "review_number_date_mismatch",
        pl.col("review_number").str.slice(-15, 8) != pl.col("review_date").dt.strftime("%Y%m%d"),
        "the date inside review_number is the date of created_at",
    )

    numbered = dated.group_by("review_date").agg(
        pl.col("review_number").str.slice(-6).cast(pl.Int64).min().alias("lowest"),
        pl.col("review_number").str.slice(-6).cast(pl.Int64).max().alias("highest"),
        pl.len().alias("total"),
    )
    broken = numbered.filter((pl.col("lowest") != 1) | (pl.col("highest") != pl.col("total")))
    if not broken.is_empty():
        issues.append(
            ValidationIssue(
                "reviews",
                "review_number_not_sequential",
                f"{broken.height} date(s) are not numbered 1..n without gaps",
            )
        )
    return issues


def validate_review_timeline(
    reviews: pl.DataFrame, shipments: pl.DataFrame
) -> list[ValidationIssue]:
    """Check the review was written after the parcel arrived.

    Args:
        reviews: The reviews dataset.
        shipments: The F008 shipments dataset.

    Returns:
        Issues for a review predating its shipment's delivery.
    """
    joined = reviews.join(
        shipments.select("shipment_id", pl.col("delivered_at").alias("shipment_delivered_at")),
        on="shipment_id",
        how="inner",
    )
    return _issue_if(
        joined,
        "reviews",
        "review_before_delivery",
        pl.col("shipment_delivered_at").is_null()
        | (pl.col("created_at") < pl.col("shipment_delivered_at")),
        "the review is written no earlier than the shipment was delivered",
    )


def validate_review_data(
    datasets: Mapping[str, pl.DataFrame],
    titles: Mapping[int, tuple[str, ...]] | None = None,
    texts: Mapping[int, tuple[str, ...]] | None = None,
) -> list[ValidationIssue]:
    """Validate schema, referential integrity, and review business rules.

    Args:
        datasets: The review dataset plus the upstream datasets it references,
            keyed by name.
        titles: The configured titles per rating, used to check that each
            review's wording was actually on offer.
        texts: The configured bodies per rating, used the same way.

    Returns:
        Every issue found. An empty list means the data satisfies the F010
        acceptance criteria.
    """
    issues = validate_referential_integrity(datasets, REVIEW_DATASETS)

    reviews = datasets.get("reviews")
    if reviews is None:
        return issues

    issues.extend(validate_review_numbers(reviews))
    issues.extend(validate_review_ratings(reviews))
    issues.extend(validate_review_content(reviews, titles, texts))

    shipments = datasets.get("shipments")
    shipment_items = datasets.get("shipment_items")
    return_items = datasets.get("return_items")
    if shipments is not None:
        issues.extend(validate_review_timeline(reviews, shipments))
        if shipment_items is not None and return_items is not None:
            issues.extend(
                validate_review_eligibility(reviews, shipments, shipment_items, return_items)
            )
    return issues


def assert_valid_review_data(
    datasets: Mapping[str, pl.DataFrame],
    titles: Mapping[int, tuple[str, ...]] | None = None,
    texts: Mapping[int, tuple[str, ...]] | None = None,
) -> None:
    """Validate the review dataset and raise if anything is wrong.

    Args:
        datasets: The review dataset plus the upstream data it references.
        titles: The configured titles per rating.
        texts: The configured bodies per rating.

    Raises:
        ValidationError: If any validation issue is found.
    """
    issues = validate_review_data(datasets, titles, texts)
    if issues:
        raise ValidationError(issues)
