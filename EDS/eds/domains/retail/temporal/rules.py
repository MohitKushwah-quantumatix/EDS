"""The business rules that only exist because time passes.

Every other validator in Retail checks one feature's output against its own
specification. These check the *history*: that the sequence of events an
enterprise accumulated over many simulated days still describes something that
could have happened.

They are all of the same shape - a child event may not predate its parent -
and they are worth stating separately because a single day's output cannot
violate any of them. It takes two days for a payment to settle against an
order that has not been placed, and the day that generated the payment cannot
see the day that will generate the order. Only the accumulated history can.

Two structural rules join them. Identifiers must stay unique across the whole
history, and so must the business keys, because those are the properties that
renumbering a day's work exists to preserve and the ones that fail loudest
when it goes wrong.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl

from eds.core.validation.issues import ValidationIssue
from eds.domains.retail.temporal.datasets import retail_dataset

__all__ = ["ORDERINGS", "EventOrdering", "validate_temporal_history"]


@dataclass(frozen=True, slots=True)
class EventOrdering:
    """A rule that one kind of event cannot predate another.

    Comparison is at day granularity. Two events on the same simulated day are
    in order whichever hour they carry, because a tick *is* a day: asking a
    payment to be later than its order to the second would be asking the
    domain for a precision the platform never gave it.

    Attributes:
        dataset: The later event's dataset.
        rule: Short identifier reported when it is violated.
        moment: The column saying when the later event happened.
        parent: The earlier event's dataset.
        key: The column in ``dataset`` that points at ``parent``.
        parent_key: The column in ``parent`` that ``key`` points at.
        parent_moment: The column saying when the earlier event happened.
        strict: Whether the later event must fall on a strictly later day,
            rather than merely not an earlier one. A session is strictly after
            registration; a payment may settle the day its order was placed.
    """

    dataset: str
    rule: str
    moment: str
    parent: str
    key: str
    parent_key: str
    parent_moment: str
    strict: bool = False


#: The order events must happen in. A customer registers, browses, buys, pays,
#: has it shipped, and only then can send it back or say what they thought.
#:
#: Returns and reviews hang off ``delivered_at`` rather than ``created_at``:
#: what makes both possible is the parcel arriving, not the label being
#: printed. Rows where the parent moment is null are not checked, because an
#: undelivered shipment has no delivery to be later than.
ORDERINGS: tuple[EventOrdering, ...] = (
    EventOrdering(
        dataset="sessions",
        rule="session_precedes_registration",
        moment="start_time",
        parent="customers",
        key="customer_id",
        parent_key="customer_id",
        parent_moment="registration_date",
        strict=True,
    ),
    EventOrdering(
        dataset="orders",
        rule="order_precedes_registration",
        moment="order_date",
        parent="customers",
        key="customer_id",
        parent_key="customer_id",
        parent_moment="registration_date",
    ),
    EventOrdering(
        dataset="payments",
        rule="payment_precedes_order",
        moment="created_at",
        parent="orders",
        key="order_id",
        parent_key="order_id",
        parent_moment="order_date",
    ),
    EventOrdering(
        dataset="shipments",
        rule="shipment_precedes_payment",
        moment="created_at",
        parent="payments",
        key="payment_id",
        parent_key="payment_id",
        parent_moment="created_at",
    ),
    EventOrdering(
        dataset="returns",
        rule="return_precedes_delivery",
        moment="requested_at",
        parent="shipments",
        key="shipment_id",
        parent_key="shipment_id",
        parent_moment="delivered_at",
    ),
    EventOrdering(
        dataset="reviews",
        rule="review_precedes_delivery",
        moment="created_at",
        parent="shipments",
        key="shipment_id",
        parent_key="shipment_id",
        parent_moment="delivered_at",
    ),
)


def validate_temporal_history(datasets: Mapping[str, pl.DataFrame]) -> list[ValidationIssue]:
    """Check that an accumulated history could have happened.

    Args:
        datasets: The enterprise as it now stands. Datasets that are absent
            are not checked: a history that has not reached commerce yet is
            incomplete, not wrong.

    Returns:
        Every issue found, in rule order. Empty when the history is coherent.
    """
    issues: list[ValidationIssue] = []
    for ordering in ORDERINGS:
        issues.extend(_check_ordering(datasets, ordering))
    issues.extend(_check_identities(datasets))
    return issues


def _check_ordering(
    datasets: Mapping[str, pl.DataFrame], ordering: EventOrdering
) -> list[ValidationIssue]:
    """Check one "cannot predate" rule.

    Args:
        datasets: The enterprise as it now stands.
        ordering: The rule to check.

    Returns:
        At most one issue, naming how many rows broke it and one example.
    """
    child = datasets.get(ordering.dataset)
    parent = datasets.get(ordering.parent)
    if child is None or parent is None or child.is_empty() or parent.is_empty():
        return []
    if not _comparable(child, ordering.moment) or not _comparable(parent, ordering.parent_moment):
        return []

    joined = (
        child.select(
            pl.col(ordering.key),
            _day(child, ordering.moment).alias("_moment"),
        )
        .join(
            parent.select(
                pl.col(ordering.parent_key).alias(ordering.key),
                _day(parent, ordering.parent_moment).alias("_parent_moment"),
            ),
            on=ordering.key,
            how="inner",
        )
        .drop_nulls(["_moment", "_parent_moment"])
    )
    if joined.is_empty():
        return []

    moment = pl.col("_moment")
    parent_moment = pl.col("_parent_moment")
    broken = joined.filter(moment <= parent_moment if ordering.strict else moment < parent_moment)
    if broken.is_empty():
        return []

    example = broken.row(0, named=True)
    relation = "must fall after" if ordering.strict else "cannot fall before"
    return [
        ValidationIssue(
            ordering.dataset,
            ordering.rule,
            f"{broken.height} row(s) {relation} their {ordering.parent} moment; "
            f"first is {ordering.key}={example[ordering.key]} on "
            f"{example['_moment']} against {example['_parent_moment']}",
        )
    ]


def _comparable(frame: pl.DataFrame, column: str) -> bool:
    """Report whether a column holds moments that can be compared.

    A column of nothing but nulls carries no type, and an absent column
    carries no rows. Neither is a violation: it is an absence of evidence.

    Args:
        frame: The frame the column would belong to.
        column: The column name.

    Returns:
        Whether the column exists and holds dates or timestamps.
    """
    if column not in frame.columns:
        return False
    return frame.schema[column] == pl.Date or isinstance(frame.schema[column], pl.Datetime)


def _day(frame: pl.DataFrame, column: str) -> pl.Expr:
    """Return the calendar day a moment column falls on.

    Args:
        frame: The frame the column belongs to, read only for its type.
        column: A date or timestamp column.

    Returns:
        An expression yielding a date.
    """
    moment = pl.col(column)
    return moment if frame.schema[column] == pl.Date else moment.dt.date()


def _check_identities(datasets: Mapping[str, pl.DataFrame]) -> list[ValidationIssue]:
    """Check that identifiers and business keys stayed unique across history.

    Args:
        datasets: The enterprise as it now stands.

    Returns:
        One issue per column that repeated a value.
    """
    issues: list[ValidationIssue] = []
    for name, frame in datasets.items():
        try:
            declaration = retail_dataset(name)
        except KeyError:
            continue
        if frame.is_empty():
            continue
        for column, rule in (
            (declaration.primary_key, "duplicate_identifier"),
            *((unique, "duplicate_business_key") for unique in declaration.unique_columns),
        ):
            if column not in frame.columns:
                continue
            values = frame[column].drop_nulls()
            repeated = values.len() - values.n_unique()
            if repeated:
                issues.append(
                    ValidationIssue(
                        name,
                        rule,
                        f"{column} repeats {repeated} value(s) across the accumulated history",
                    )
                )
    return issues
