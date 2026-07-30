"""Business rule checks for generated master data.

Referential integrity proves the keys line up; these rules prove the values
make commercial sense. A catalog where cost exceeds price, or a warehouse with
negative capacity, is referentially perfect and still useless for analytics.

Each check is a small function over one dataset so that a failure names the
rule it broke.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.validation.issues import ValidationIssue

__all__ = [
    "validate_business_rules",
    "validate_categories",
    "validate_geography",
    "validate_inventory",
    "validate_products",
    "validate_suppliers",
    "validate_warehouses",
]


def _count_where(frame: pl.DataFrame, predicate: pl.Expr) -> int:
    """Count rows satisfying a predicate.

    Args:
        frame: Frame to filter.
        predicate: Boolean expression describing the violation.

    Returns:
        The number of matching rows.
    """
    return int(frame.filter(predicate).height)


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
    count = _count_where(frame, predicate)
    if count:
        return [ValidationIssue(dataset, rule, f"{count} row(s) violate: {message}")]
    return []


def validate_products(frame: pl.DataFrame) -> list[ValidationIssue]:
    """Check catalog pricing and physical attributes.

    Args:
        frame: The products dataset.

    Returns:
        Issues for non-positive prices, cost at or above price, or
        non-positive weights and dimensions.
    """
    issues: list[ValidationIssue] = []
    issues += _issue_if(
        frame, "products", "non_positive_price", pl.col("list_price") <= 0, "list_price > 0"
    )
    issues += _issue_if(
        frame, "products", "non_positive_cost", pl.col("unit_cost") <= 0, "unit_cost > 0"
    )
    issues += _issue_if(
        frame,
        "products",
        "cost_not_below_price",
        pl.col("unit_cost") >= pl.col("list_price"),
        "unit_cost < list_price",
    )
    issues += _issue_if(
        frame, "products", "non_positive_weight", pl.col("weight_kg") <= 0, "weight_kg > 0"
    )
    for dimension in ("length_cm", "width_cm", "height_cm"):
        issues += _issue_if(
            frame, "products", "non_positive_dimension", pl.col(dimension) <= 0, f"{dimension} > 0"
        )
    return issues


def validate_inventory(frame: pl.DataFrame) -> list[ValidationIssue]:
    """Check stock quantities are coherent.

    Args:
        frame: The inventory dataset.

    Returns:
        Issues for negative quantities, reservations exceeding stock on hand,
        or non-positive reorder quantities.
    """
    issues: list[ValidationIssue] = []
    issues += _issue_if(
        frame,
        "inventory",
        "negative_quantity",
        pl.col("quantity_on_hand") < 0,
        "quantity_on_hand >= 0",
    )
    issues += _issue_if(
        frame,
        "inventory",
        "negative_reservation",
        pl.col("quantity_reserved") < 0,
        "quantity_reserved >= 0",
    )
    issues += _issue_if(
        frame,
        "inventory",
        "over_reserved",
        pl.col("quantity_reserved") > pl.col("quantity_on_hand"),
        "quantity_reserved <= quantity_on_hand",
    )
    issues += _issue_if(
        frame,
        "inventory",
        "non_positive_reorder_quantity",
        pl.col("reorder_quantity") <= 0,
        "reorder_quantity > 0",
    )
    return issues


def validate_warehouses(frame: pl.DataFrame) -> list[ValidationIssue]:
    """Check warehouse capacity and coordinates.

    Args:
        frame: The warehouses dataset.

    Returns:
        Issues for non-positive capacity or out-of-range coordinates.
    """
    issues: list[ValidationIssue] = []
    issues += _issue_if(
        frame,
        "warehouses",
        "non_positive_capacity",
        pl.col("capacity_units") <= 0,
        "capacity_units > 0",
    )
    issues += _issue_if(
        frame,
        "warehouses",
        "latitude_out_of_range",
        (pl.col("latitude") < -90) | (pl.col("latitude") > 90),
        "-90 <= latitude <= 90",
    )
    issues += _issue_if(
        frame,
        "warehouses",
        "longitude_out_of_range",
        (pl.col("longitude") < -180) | (pl.col("longitude") > 180),
        "-180 <= longitude <= 180",
    )
    return issues


def validate_suppliers(frame: pl.DataFrame) -> list[ValidationIssue]:
    """Check supplier lead times and reliability scores.

    Args:
        frame: The suppliers dataset.

    Returns:
        Issues for non-positive lead times or reliability outside 0 to 1.
    """
    issues: list[ValidationIssue] = []
    issues += _issue_if(
        frame,
        "suppliers",
        "non_positive_lead_time",
        pl.col("lead_time_days") <= 0,
        "lead_time_days > 0",
    )
    issues += _issue_if(
        frame,
        "suppliers",
        "reliability_out_of_range",
        (pl.col("reliability_score") < 0) | (pl.col("reliability_score") > 1),
        "0 <= reliability_score <= 1",
    )
    return issues


def validate_categories(frame: pl.DataFrame) -> list[ValidationIssue]:
    """Check the category tree is well formed.

    Args:
        frame: The categories dataset.

    Returns:
        Issues when a level-1 category has a parent, a deeper category has
        none, or at least one leaf is not present.
    """
    issues: list[ValidationIssue] = []
    issues += _issue_if(
        frame,
        "categories",
        "root_with_parent",
        (pl.col("level") == 1) & pl.col("parent_category_id").is_not_null(),
        "level 1 categories have no parent",
    )
    issues += _issue_if(
        frame,
        "categories",
        "child_without_parent",
        (pl.col("level") > 1) & pl.col("parent_category_id").is_null(),
        "categories below level 1 have a parent",
    )
    if not frame.is_empty() and _count_where(frame, pl.col("is_leaf")) == 0:
        issues.append(
            ValidationIssue(
                "categories", "no_leaf_categories", "no leaf category exists to hold products"
            )
        )
    return issues


def validate_geography(cities: pl.DataFrame) -> list[ValidationIssue]:
    """Check city coordinates fall on the globe.

    Args:
        cities: The cities dataset.

    Returns:
        Issues for out-of-range latitude or longitude.
    """
    issues: list[ValidationIssue] = []
    issues += _issue_if(
        cities,
        "cities",
        "latitude_out_of_range",
        (pl.col("latitude") < -90) | (pl.col("latitude") > 90),
        "-90 <= latitude <= 90",
    )
    issues += _issue_if(
        cities,
        "cities",
        "longitude_out_of_range",
        (pl.col("longitude") < -180) | (pl.col("longitude") > 180),
        "-180 <= longitude <= 180",
    )
    return issues


def validate_business_rules(datasets: Mapping[str, pl.DataFrame]) -> list[ValidationIssue]:
    """Run every business rule check over a set of datasets.

    Datasets that were not generated are skipped rather than reported here;
    :func:`eds.core.validation.referential.validate_referential_integrity` owns the
    "dataset is missing" diagnostic.

    Args:
        datasets: Generated datasets, keyed by name.

    Returns:
        Every business rule issue found.
    """
    checks = {
        "products": validate_products,
        "inventory": validate_inventory,
        "warehouses": validate_warehouses,
        "suppliers": validate_suppliers,
        "categories": validate_categories,
        "cities": validate_geography,
    }

    issues: list[ValidationIssue] = []
    for name, check in checks.items():
        frame = datasets.get(name)
        if frame is not None:
            issues.extend(check(frame))
    return issues
