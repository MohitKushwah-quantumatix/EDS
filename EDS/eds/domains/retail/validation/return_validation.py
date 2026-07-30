"""Validation rules for the F009 return datasets.

Referential integrity is delegated to
:func:`eds.core.validation.referential.validate_referential_integrity` with the
return declarations, which covers duplicate ``return_id``, ``return_number``,
``return_item_id`` and ``history_id`` values, the one-return-per-shipment rule,
and invalid shipment, customer, reason, shipment item, order line and product
references.

The rules here cover what a schema cannot express: that returns came only from
delivered shipments, that the item lineage was preserved rather than
reconstructed, and that the status history is a well-formed lifecycle ending at
the return's current status.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import polars as pl

from eds.core.validation.issues import ValidationError, ValidationIssue
from eds.domains.retail.domain.commerce.enums import RETURN_LIFECYCLE, ReturnStatus, ShipmentStatus
from eds.domains.retail.domain.commerce.schema import RETURN_DATASETS
from eds.domains.retail.validation.referential import validate_referential_integrity

__all__ = [
    "RETURN_NUMBER_PATTERN",
    "assert_valid_return_data",
    "validate_item_reconciliation",
    "validate_refund_types",
    "validate_return_data",
    "validate_return_numbers",
    "validate_return_status_history",
    "validate_return_timeline",
    "validate_shipment_eligibility",
]

#: ``RET-YYYYMMDD-000001`` and anything else with the same shape.
RETURN_NUMBER_PATTERN: Final[str] = r"^[A-Z0-9]{1,8}-\d{8}-\d{6}$"


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


def validate_shipment_eligibility(
    returns: pl.DataFrame, shipments: pl.DataFrame
) -> list[ValidationIssue]:
    """Check returns came only from delivered shipments, at most one each.

    Args:
        returns: The returns dataset.
        shipments: The F008 shipments dataset.

    Returns:
        Issues for a return against an undelivered shipment, a shipment
        returned more than once, or a return whose customer disagrees with its
        shipment.
    """
    issues: list[ValidationIssue] = []

    joined = returns.join(
        shipments.select(
            "shipment_id",
            "current_status",
            pl.col("customer_id").alias("shipment_customer_id"),
        ),
        on="shipment_id",
        how="inner",
        suffix="_shp",
    )
    issues += _issue_if(
        joined,
        "returns",
        "invalid_shipment_status",
        pl.col("current_status_shp") != str(ShipmentStatus.DELIVERED),
        "only a DELIVERED shipment produces a return",
    )
    issues += _issue_if(
        joined,
        "returns",
        "customer_mismatch",
        pl.col("customer_id") != pl.col("shipment_customer_id"),
        "customer_id matches the shipment being returned",
    )

    duplicates = returns.height - returns["shipment_id"].n_unique()
    if duplicates:
        issues.append(
            ValidationIssue(
                "returns",
                "multiple_returns_per_shipment",
                f"{duplicates} shipment(s) produced more than one return",
            )
        )
    return issues


def validate_refund_types(
    returns: pl.DataFrame, refund_types: Mapping[str, float] | None = None
) -> list[ValidationIssue]:
    """Check the settlement type is one the configuration offers.

    Args:
        returns: The returns dataset.
        refund_types: The configured settlement types. When omitted the
            membership check is skipped, because nothing else knows which
            types were on offer.

    Returns:
        Issues for an empty refund type, or one the configuration does not
        list.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        returns,
        "returns",
        "missing_refund_type",
        pl.col("refund_type").str.len_chars() == 0,
        "refund_type is not empty",
    )
    if refund_types is None:
        return issues

    issues += _issue_if(
        returns,
        "returns",
        "unknown_refund_type",
        ~pl.col("refund_type").is_in(list(refund_types)),
        f"refund_type is one of {sorted(refund_types)}",
    )
    return issues


def validate_return_numbers(returns: pl.DataFrame) -> list[ValidationIssue]:
    """Check the business return number is well formed and consistent.

    Args:
        returns: The returns dataset.

    Returns:
        Issues for a malformed number, one whose embedded date disagrees with
        the day the return was requested, or a day that is not numbered from
        one without gaps.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        returns,
        "returns",
        "malformed_return_number",
        ~pl.col("return_number").str.contains(RETURN_NUMBER_PATTERN),
        "return_number matches PREFIX-YYYYMMDD-NNNNNN",
    )

    # The remaining checks read the number apart, so they only run on the rows
    # that are shaped like one. A malformed number has already been reported
    # above; parsing it here would raise rather than add an issue.
    well_formed = returns.filter(pl.col("return_number").str.contains(RETURN_NUMBER_PATTERN))
    if well_formed.is_empty():
        return issues

    dated = well_formed.with_columns(pl.col("requested_at").dt.date().alias("return_date"))
    issues += _issue_if(
        dated,
        "returns",
        "return_number_date_mismatch",
        pl.col("return_number").str.slice(-15, 8) != pl.col("return_date").dt.strftime("%Y%m%d"),
        "the date inside return_number is the date of requested_at",
    )

    numbered = dated.group_by("return_date").agg(
        pl.col("return_number").str.slice(-6).cast(pl.Int64).min().alias("lowest"),
        pl.col("return_number").str.slice(-6).cast(pl.Int64).max().alias("highest"),
        pl.len().alias("total"),
    )
    broken = numbered.filter((pl.col("lowest") != 1) | (pl.col("highest") != pl.col("total")))
    if not broken.is_empty():
        issues.append(
            ValidationIssue(
                "returns",
                "return_number_not_sequential",
                f"{broken.height} date(s) are not numbered 1..n without gaps",
            )
        )
    return issues


def validate_return_timeline(
    returns: pl.DataFrame, shipments: pl.DataFrame
) -> list[ValidationIssue]:
    """Check a return was requested after the shipment was delivered.

    Args:
        returns: The returns dataset.
        shipments: The F008 shipments dataset.

    Returns:
        Issues for a request predating delivery, a stage that does not follow
        the one before it, or a timestamp populated on a status that never
        reached that stage.
    """
    issues: list[ValidationIssue] = []

    joined = returns.join(
        shipments.select("shipment_id", pl.col("delivered_at").alias("shipment_delivered_at")),
        on="shipment_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "returns",
        "return_before_delivery",
        pl.col("shipment_delivered_at").is_null()
        | (pl.col("requested_at") < pl.col("shipment_delivered_at")),
        "the return is requested no earlier than the shipment was delivered",
    )
    issues += _issue_if(
        returns,
        "returns",
        "created_at_mismatch",
        pl.col("created_at") != pl.col("requested_at"),
        "created_at is the moment the return was requested",
    )

    for earlier, later in (
        ("requested_at", "approved_at"),
        ("approved_at", "received_at"),
        ("received_at", "completed_at"),
    ):
        issues += _issue_if(
            returns,
            "returns",
            "timeline_out_of_order",
            pl.col(later).is_not_null()
            & (pl.col(earlier).is_null() | (pl.col(later) <= pl.col(earlier))),
            f"{later} is after {earlier}",
        )

    # A return that never reached a stage has no timestamp for it.
    reached = {
        "approved_at": (
            ReturnStatus.APPROVED,
            ReturnStatus.IN_TRANSIT,
            ReturnStatus.RECEIVED,
            ReturnStatus.COMPLETED,
        ),
        "received_at": (ReturnStatus.RECEIVED, ReturnStatus.COMPLETED),
        "completed_at": (ReturnStatus.COMPLETED,),
    }
    for column, statuses in reached.items():
        issues += _issue_if(
            returns,
            "returns",
            "timestamp_inconsistent",
            pl.col("current_status").is_in([str(status) for status in statuses])
            != pl.col(column).is_not_null(),
            f"{column} is populated exactly when the return has reached that stage",
        )
    return issues


def validate_item_reconciliation(
    returns: pl.DataFrame, return_items: pl.DataFrame, shipment_items: pl.DataFrame
) -> list[ValidationIssue]:
    """Check the items came back from the return's own shipment, unaltered.

    Args:
        returns: The returns dataset.
        return_items: The return items dataset.
        shipment_items: The F008 shipment items dataset.

    Returns:
        Issues for a non-positive quantity, an item from another shipment, a
        quantity, product or order line that disagrees with the shipment item,
        a return carrying no items, or an item created before its return.
    """
    issues: list[ValidationIssue] = []

    issues += _issue_if(
        return_items,
        "return_items",
        "non_positive_quantity",
        pl.col("quantity") <= 0,
        "quantity > 0",
    )

    joined = return_items.join(
        returns.select(
            "return_id",
            pl.col("shipment_id").alias("return_shipment_id"),
            pl.col("created_at").alias("return_created_at"),
        ),
        on="return_id",
        how="inner",
    ).join(
        shipment_items.select(
            "shipment_item_id",
            pl.col("shipment_id").alias("item_shipment_id"),
            pl.col("order_line_id").alias("item_order_line_id"),
            pl.col("product_id").alias("item_product_id"),
            pl.col("quantity").alias("item_quantity"),
        ),
        on="shipment_item_id",
        how="inner",
    )
    issues += _issue_if(
        joined,
        "return_items",
        "item_from_another_shipment",
        pl.col("return_shipment_id") != pl.col("item_shipment_id"),
        "the shipment item belongs to the return's own shipment",
    )
    for column, source in (
        ("order_line_id", "item_order_line_id"),
        ("product_id", "item_product_id"),
        ("quantity", "item_quantity"),
    ):
        issues += _issue_if(
            joined,
            "return_items",
            "lineage_not_preserved",
            pl.col(column) != pl.col(source),
            f"{column} is carried across from the shipment item unchanged",
        )
    issues += _issue_if(
        joined,
        "return_items",
        "item_before_return",
        pl.col("created_at") < pl.col("return_created_at"),
        "the item is created no earlier than its return",
    )

    covered = set(return_items["return_id"].to_list())
    if without := [
        return_id for return_id in returns["return_id"].to_list() if return_id not in covered
    ]:
        issues.append(
            ValidationIssue(
                "return_items",
                "return_without_items",
                f"{len(without)} return(s) carry no items",
            )
        )
    return issues


def validate_return_status_history(
    returns: pl.DataFrame, status_history: pl.DataFrame
) -> list[ValidationIssue]:
    """Check the status history is a well-formed lifecycle.

    Args:
        returns: The returns dataset.
        status_history: The return status history dataset.

    Returns:
        Issues for an unknown status, a sequence that is not numbered from one
        without gaps, timestamps that move backwards, a history that does not
        follow the lifecycle order, a return with no history, or a
        ``current_status`` or timeline column that disagrees with the history.
    """
    issues: list[ValidationIssue] = []
    known = [str(member) for member in RETURN_LIFECYCLE]

    issues += _issue_if(
        status_history,
        "return_status_history",
        "unknown_status",
        ~pl.col("status").is_in(known),
        f"status is one of {known}",
    )
    issues += _issue_if(
        status_history,
        "return_status_history",
        "invalid_sequence",
        pl.col("sequence") < 1,
        "sequence >= 1",
    )

    if status_history.is_empty():
        if not returns.is_empty():
            issues.append(
                ValidationIssue(
                    "return_status_history",
                    "return_without_history",
                    f"{returns.height} return(s) have no status history",
                )
            )
        return issues

    grouped = status_history.group_by("return_id").agg(
        pl.col("sequence").min().alias("lowest"),
        pl.col("sequence").max().alias("highest"),
        pl.col("sequence").n_unique().alias("distinct"),
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
                "return_status_history",
                "invalid_sequence",
                f"{broken.height} return(s) are not numbered 1..n without gaps",
            )
        )

    # Position in the lifecycle must advance in step with the sequence, and
    # time must move forwards with it.
    positions = pl.DataFrame(
        {"status": known, "lifecycle_position": list(range(1, len(known) + 1))},
        schema={"status": pl.String, "lifecycle_position": pl.Int64},
    )
    ordered = (
        status_history.join(positions, on="status", how="inner")
        .sort("return_id", "sequence")
        .with_columns(
            pl.col("status_timestamp").shift(1).over("return_id").alias("previous_timestamp"),
            pl.col("lifecycle_position").shift(1).over("return_id").alias("previous_position"),
        )
    )
    issues += _issue_if(
        ordered,
        "return_status_history",
        "history_out_of_order",
        pl.col("previous_timestamp").is_not_null()
        & (pl.col("status_timestamp") <= pl.col("previous_timestamp")),
        "each status happens after the one before it",
    )
    issues += _issue_if(
        ordered,
        "return_status_history",
        "lifecycle_out_of_order",
        pl.col("previous_position").is_not_null()
        & (pl.col("lifecycle_position") <= pl.col("previous_position")),
        "the lifecycle advances with the sequence",
    )
    issues += _issue_if(
        ordered,
        "return_status_history",
        "lifecycle_does_not_start_at_requested",
        (pl.col("sequence") == 1) & (pl.col("status") != str(ReturnStatus.REQUESTED)),
        "every history starts at REQUESTED",
    )

    covered = set(status_history["return_id"].to_list())
    if without := [
        return_id for return_id in returns["return_id"].to_list() if return_id not in covered
    ]:
        issues.append(
            ValidationIssue(
                "return_status_history",
                "return_without_history",
                f"{len(without)} return(s) have no status history",
            )
        )

    latest = (
        status_history.sort("return_id", "sequence")
        .group_by("return_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest_status"))
    )
    reconciled = returns.join(latest, on="return_id", how="inner")
    issues += _issue_if(
        reconciled,
        "returns",
        "current_status_mismatch",
        pl.col("current_status") != pl.col("latest_status"),
        "current_status equals the status of the latest history row",
    )

    # The timeline columns are denormalised from the history, so they must
    # carry exactly the timestamps the history recorded.
    stamps = status_history.group_by("return_id").agg(
        *[
            pl.col("status_timestamp")
            .filter(pl.col("status") == str(status))
            .first()
            .alias(f"history_{column}")
            for status, column in (
                (ReturnStatus.REQUESTED, "requested_at"),
                (ReturnStatus.APPROVED, "approved_at"),
                (ReturnStatus.RECEIVED, "received_at"),
                (ReturnStatus.COMPLETED, "completed_at"),
            )
        ]
    )
    stamped = returns.join(stamps, on="return_id", how="inner")
    for column in ("requested_at", "approved_at", "received_at", "completed_at"):
        issues += _issue_if(
            stamped,
            "returns",
            "timeline_history_mismatch",
            pl.col(column).is_null() != pl.col(f"history_{column}").is_null(),
            f"{column} is populated exactly when the history records it",
        )
        issues += _issue_if(
            stamped,
            "returns",
            "timeline_history_mismatch",
            pl.col(column).is_not_null() & (pl.col(column) != pl.col(f"history_{column}")),
            f"{column} equals the timestamp of its history row",
        )
    return issues


def validate_return_data(
    datasets: Mapping[str, pl.DataFrame],
    refund_types: Mapping[str, float] | None = None,
) -> list[ValidationIssue]:
    """Validate schema, referential integrity, and return business rules.

    Args:
        datasets: The return datasets plus the upstream datasets they
            reference, keyed by name.
        refund_types: The configured settlement types, used to check that each
            return's ``refund_type`` was actually on offer.

    Returns:
        Every issue found. An empty list means the data satisfies the F009
        acceptance criteria.
    """
    issues = validate_referential_integrity(datasets, RETURN_DATASETS)

    returns = datasets.get("returns")
    return_items = datasets.get("return_items")
    status_history = datasets.get("return_status_history")
    if returns is None or return_items is None or status_history is None:
        return issues

    issues.extend(validate_return_numbers(returns))
    issues.extend(validate_refund_types(returns, refund_types))
    issues.extend(validate_return_status_history(returns, status_history))

    shipments = datasets.get("shipments")
    if shipments is not None:
        issues.extend(validate_shipment_eligibility(returns, shipments))
        issues.extend(validate_return_timeline(returns, shipments))

    shipment_items = datasets.get("shipment_items")
    if shipment_items is not None:
        issues.extend(validate_item_reconciliation(returns, return_items, shipment_items))
    return issues


def assert_valid_return_data(
    datasets: Mapping[str, pl.DataFrame],
    refund_types: Mapping[str, float] | None = None,
) -> None:
    """Validate the return datasets and raise if anything is wrong.

    Args:
        datasets: The return datasets plus the upstream data they reference.
        refund_types: The configured settlement types.

    Raises:
        ValidationError: If any validation issue is found.
    """
    issues = validate_return_data(datasets, refund_types)
    if issues:
        raise ValidationError(issues)
