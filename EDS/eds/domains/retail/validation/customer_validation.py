"""Validation rules for the F002 customer master datasets.

Referential integrity is delegated to
:func:`eds.core.validation.referential.validate_referential_integrity` with the
customer declarations, which covers duplicate emails, phones, and customer
numbers (declared unique columns) and orphan geography references.

The rules in this module cover the cardinality and coherence constraints that
a schema cannot express: every customer having exactly one primary address,
one preference record, and one loyalty record.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.validation.issues import ValidationError, ValidationIssue
from eds.domains.retail.domain.customer.schema import CUSTOMER_DATASETS
from eds.domains.retail.validation.referential import validate_referential_integrity

__all__ = [
    "assert_valid_customer_data",
    "validate_address_cardinality",
    "validate_customer_data",
    "validate_customer_fields",
    "validate_loyalty",
    "validate_one_record_per_customer",
]

_MAX_REPORTED = 5

_RISK_MIN = 0.0
_RISK_MAX = 100.0


def _sample_ids(values: list[int]) -> str:
    """Render a short sample of offending customer ids.

    Args:
        values: Offending identifiers.

    Returns:
        A comma-separated sample, truncated with a count when long.
    """
    head = ", ".join(str(value) for value in values[:_MAX_REPORTED])
    if len(values) > _MAX_REPORTED:
        return f"{head}, ... ({len(values)} total)"
    return head


def validate_address_cardinality(
    customers: pl.DataFrame, addresses: pl.DataFrame, min_addresses: int, max_addresses: int
) -> list[ValidationIssue]:
    """Check the address rules that a schema cannot express.

    Args:
        customers: The customers dataset.
        addresses: The customer addresses dataset.
        min_addresses: Fewest addresses a customer may have.
        max_addresses: Most addresses a customer may have.

    Returns:
        Issues for customers with no address, too few or too many addresses,
        or a primary address count other than exactly one.
    """
    issues: list[ValidationIssue] = []
    dataset = "customer_addresses"

    per_customer = addresses.group_by("customer_id").agg(
        pl.len().alias("address_count"),
        pl.col("is_primary").sum().alias("primary_count"),
    )
    counts = dict(
        zip(
            per_customer["customer_id"].to_list(),
            per_customer["address_count"].to_list(),
            strict=True,
        )
    )

    without = [
        customer_id
        for customer_id in customers["customer_id"].to_list()
        if customer_id not in counts
    ]
    if without:
        issues.append(
            ValidationIssue(
                dataset,
                "customer_without_address",
                f"customer(s) have no address: {_sample_ids(without)}",
            )
        )

    too_few = per_customer.filter(pl.col("address_count") < min_addresses)
    if not too_few.is_empty():
        issues.append(
            ValidationIssue(
                dataset,
                "too_few_addresses",
                f"{too_few.height} customer(s) have fewer than {min_addresses} address(es)",
            )
        )

    too_many = per_customer.filter(pl.col("address_count") > max_addresses)
    if not too_many.is_empty():
        issues.append(
            ValidationIssue(
                dataset,
                "too_many_addresses",
                f"{too_many.height} customer(s) have more than {max_addresses} address(es)",
            )
        )

    wrong_primary = per_customer.filter(pl.col("primary_count") != 1)
    if not wrong_primary.is_empty():
        issues.append(
            ValidationIssue(
                dataset,
                "primary_address_count",
                f"{wrong_primary.height} customer(s) do not have exactly one primary address: "
                f"{_sample_ids(wrong_primary['customer_id'].to_list())}",
            )
        )
    return issues


def validate_one_record_per_customer(
    customers: pl.DataFrame, related: pl.DataFrame, dataset: str
) -> list[ValidationIssue]:
    """Check a one-to-one dataset covers every customer exactly once.

    Args:
        customers: The customers dataset.
        related: The dataset expected to hold one row per customer.
        dataset: Name of that dataset, used in the issue.

    Returns:
        Issues for customers with no record and for duplicated records.
    """
    issues: list[ValidationIssue] = []
    covered = set(related["customer_id"].to_list())
    missing = [
        customer_id
        for customer_id in customers["customer_id"].to_list()
        if customer_id not in covered
    ]
    if missing:
        issues.append(
            ValidationIssue(
                dataset,
                "customer_without_record",
                f"customer(s) have no {dataset} record: {_sample_ids(missing)}",
            )
        )

    duplicates = related.height - related["customer_id"].n_unique()
    if duplicates:
        issues.append(
            ValidationIssue(
                dataset,
                "duplicate_customer_record",
                f"{duplicates} customer(s) have more than one {dataset} record",
            )
        )
    return issues


def validate_customer_fields(customers: pl.DataFrame) -> list[ValidationIssue]:
    """Check value-level rules on the customers dataset.

    Args:
        customers: The customers dataset.

    Returns:
        Issues for out-of-range risk scores, births after registration, or
        an updated timestamp preceding creation.
    """
    issues: list[ValidationIssue] = []

    out_of_range = customers.filter(
        (pl.col("risk_score") < _RISK_MIN) | (pl.col("risk_score") > _RISK_MAX)
    )
    if not out_of_range.is_empty():
        issues.append(
            ValidationIssue(
                "customers",
                "risk_score_out_of_range",
                f"{out_of_range.height} row(s) violate: 0 <= risk_score <= 100",
            )
        )

    born_after_registering = customers.filter(
        pl.col("date_of_birth") >= pl.col("registration_date")
    )
    if not born_after_registering.is_empty():
        issues.append(
            ValidationIssue(
                "customers",
                "birth_after_registration",
                f"{born_after_registering.height} row(s) violate: "
                "date_of_birth < registration_date",
            )
        )

    reversed_timestamps = customers.filter(pl.col("updated_at") < pl.col("created_at"))
    if not reversed_timestamps.is_empty():
        issues.append(
            ValidationIssue(
                "customers",
                "updated_before_created",
                f"{reversed_timestamps.height} row(s) violate: updated_at >= created_at",
            )
        )
    return issues


def validate_loyalty(customers: pl.DataFrame, loyalty: pl.DataFrame) -> list[ValidationIssue]:
    """Check loyalty value rules.

    Args:
        customers: The customers dataset, supplying registration dates.
        loyalty: The customer loyalty dataset.

    Returns:
        Issues for negative point balances or enrolment before registration.
    """
    issues: list[ValidationIssue] = []

    negative = loyalty.filter(pl.col("points_balance") < 0)
    if not negative.is_empty():
        issues.append(
            ValidationIssue(
                "customer_loyalty",
                "negative_points",
                f"{negative.height} row(s) violate: points_balance >= 0",
            )
        )

    joined = loyalty.join(
        customers.select("customer_id", "registration_date"), on="customer_id", how="inner"
    )
    early = joined.filter(pl.col("enrollment_date") < pl.col("registration_date"))
    if not early.is_empty():
        issues.append(
            ValidationIssue(
                "customer_loyalty",
                "enrolled_before_registration",
                f"{early.height} row(s) violate: enrollment_date >= registration_date",
            )
        )
    return issues


def validate_customer_data(
    datasets: Mapping[str, pl.DataFrame],
    min_addresses: int = 1,
    max_addresses: int = 2,
) -> list[ValidationIssue]:
    """Validate schema, referential integrity, and customer business rules.

    Args:
        datasets: The customer datasets plus the F001 geography datasets they
            reference, keyed by name.
        min_addresses: Fewest addresses a customer may have.
        max_addresses: Most addresses a customer may have.

    Returns:
        Every issue found. An empty list means the data satisfies the F002
        data quality rules.
    """
    issues = validate_referential_integrity(datasets, CUSTOMER_DATASETS)

    customers = datasets.get("customers")
    addresses = datasets.get("customer_addresses")
    preferences = datasets.get("customer_preferences")
    loyalty = datasets.get("customer_loyalty")

    if customers is None:
        return issues

    issues.extend(validate_customer_fields(customers))

    if addresses is not None:
        issues.extend(
            validate_address_cardinality(customers, addresses, min_addresses, max_addresses)
        )
    if preferences is not None:
        issues.extend(
            validate_one_record_per_customer(customers, preferences, "customer_preferences")
        )
    if loyalty is not None:
        issues.extend(validate_one_record_per_customer(customers, loyalty, "customer_loyalty"))
        issues.extend(validate_loyalty(customers, loyalty))
    return issues


def assert_valid_customer_data(
    datasets: Mapping[str, pl.DataFrame],
    min_addresses: int = 1,
    max_addresses: int = 2,
) -> None:
    """Validate customer datasets and raise if anything is wrong.

    Args:
        datasets: The customer datasets plus the geography they reference.
        min_addresses: Fewest addresses a customer may have.
        max_addresses: Most addresses a customer may have.

    Raises:
        ValidationError: If any validation issue is found.
    """
    issues = validate_customer_data(datasets, min_addresses, max_addresses)
    if issues:
        raise ValidationError(issues)
