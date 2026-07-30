"""Running one Retail stage for the platform, and saying what went wrong.

**Generation moved into the domain.** P006.1 put the generate/validate
sequence here because there was nowhere else it could go: the platform may not
import Retail and Retail had no notion of being *run*. Retail now has one -
:func:`~eds.domains.retail.temporal.day.advance_day`, which runs a stage for a
business date - so this module no longer restates how a retail business is
built. It asks the domain, and classifies what the domain raises.

That is the whole job. Only this layer can tell a generator that raised from
data that failed validation from a disk that would not accept a write, so it
raises :class:`~eds.platform.scheduler.executor.StageExecutionError` with the
:class:`~eds.platform.runtime.failure.FailureType` that names it and the
scheduler records what it is told.

**A stage is validated against the world.** Each feature validator is shown
every dataset as it now stands, because most of what they check is referential
and a day's rows point at years of history. The one exception is the session
timeline, which asks whether sessions fall within the configured window of the
reference date - a question about a *snapshot*, which an accumulated history is
not - so that rule alone is asked of the day.

What has to hold across the whole history is stated separately, in
:func:`~eds.domains.retail.temporal.rules.validate_temporal_history`, and is
checked on every stage that has enough of the history to check it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Final

import polars as pl

from eds.core.validation.issues import ValidationIssue
from eds.domains.retail.config import SimulationConfig
from eds.domains.retail.temporal.context import BusinessContext
from eds.domains.retail.temporal.day import DayOfBusiness, advance_day
from eds.domains.retail.temporal.rules import validate_temporal_history
from eds.domains.retail.validation.browsing_validation import validate_browsing_data
from eds.domains.retail.validation.checkout_validation import validate_checkout_data
from eds.domains.retail.validation.commerce_validation import validate_commerce_data
from eds.domains.retail.validation.customer_validation import validate_customer_data
from eds.domains.retail.validation.engagement_validation import validate_engagement_data
from eds.domains.retail.validation.journey_validation import validate_journey_data
from eds.domains.retail.validation.master_data import validate_master_data
from eds.domains.retail.validation.order_validation import validate_order_data
from eds.domains.retail.validation.payment_validation import validate_payment_data
from eds.domains.retail.validation.return_validation import validate_return_data
from eds.domains.retail.validation.review_validation import validate_review_data
from eds.domains.retail.validation.shipment_validation import validate_shipment_data
from eds.platform.runtime.failure import FailureType
from eds.platform.scheduler.executor import StageExecutionError

__all__ = ["RETAIL_STAGES", "StageValidation", "run_stage"]

#: What checks one stage's day: the settings it was generated with, the world
#: as it now stands, and the rows this day added to it.
type StageValidation = Callable[
    [SimulationConfig, Mapping[str, pl.DataFrame], Mapping[str, pl.DataFrame]],
    Sequence[ValidationIssue],
]

Frames = Mapping[str, pl.DataFrame]


def _master_data(
    config: SimulationConfig, world: Frames, today: Frames
) -> Sequence[ValidationIssue]:
    """Check the fourteen master datasets.

    Args:
        config: The settings the day was generated with.
        world: Every dataset as it now stands.
        today: The rows this day added.

    Returns:
        Every issue found.
    """
    del config, today
    return validate_master_data(world)


def _customers(config: SimulationConfig, world: Frames, today: Frames) -> Sequence[ValidationIssue]:
    """Check the four customer datasets.

    Args:
        config: The settings the day was generated with.
        world: Every dataset as it now stands.
        today: The rows this day added.

    Returns:
        Every issue found.
    """
    del today
    return validate_customer_data(
        world, config.customers.min_addresses, config.customers.max_addresses
    )


def _journey(config: SimulationConfig, world: Frames, today: Frames) -> Sequence[ValidationIssue]:
    """Check the six journey datasets.

    The session timeline is the one rule here that is about a *snapshot*: it
    asks whether sessions fall within the configured window of the reference
    date, and an accumulated history is older than any window by construction.
    So it is asked of the day's sessions, against the day. That sessions never
    predate their customer across the whole history is checked separately, by
    the temporal rules.

    Args:
        config: The settings the day was generated with, whose reference date
            is the business date.
        world: Every dataset as it now stands.
        today: The rows this day added.

    Returns:
        Every issue found.
    """
    dated = {**world, "sessions": today["sessions"]} if "sessions" in today else world
    issues = list(
        validate_journey_data(
            dated,
            config.customers.reference_date,
            config.journey.session_years,
            config.journey.max_pages_viewed,
        )
    )
    issues += validate_browsing_data(
        world,
        config.browsing.min_view_seconds,
        config.browsing.max_view_seconds,
        config.browsing.max_results_count,
    )
    issues += validate_engagement_data(
        world, config.engagement.min_view_seconds, config.engagement.max_view_seconds
    )
    return issues


def _commerce(config: SimulationConfig, world: Frames, today: Frames) -> Sequence[ValidationIssue]:
    """Check the fifteen commerce datasets.

    Against the whole history, not against the day. It is tempting to check
    only what today added - an append-only history cannot have changed since it
    was written, so re-checking it is work already done - but several of these
    rules are about a *date* rather than a row: order, payment, shipment,
    return and review numbers must run ``1..n`` without gaps for every day they
    fall on, and a later day can add to a date an earlier day opened. Shown
    only today's rows, those rules would see a sequence starting at four and
    report a defect that is not there.

    Args:
        config: The settings the day was generated with.
        world: Every dataset as it now stands.
        today: The rows this day added.

    Returns:
        Every issue found.
    """
    del today
    issues = list(
        validate_commerce_data(world, config.commerce.min_quantity, config.commerce.max_quantity)
    )
    issues += validate_checkout_data(world)
    issues += validate_order_data(world)
    issues += validate_payment_data(world)
    issues += validate_shipment_data(world, config.shipments.carriers)
    issues += validate_return_data(world, config.returns.refund_types)
    issues += validate_review_data(world, config.reviews.titles, config.reviews.texts)
    return issues


#: What checks each declared Retail stage, keyed by the stage name the domain
#: registers. The keys are checked against
#: :attr:`~eds.domains.retail.registry.RetailDomain.stages` by a test, so a
#: stage added to the domain without checks here fails loudly rather than
#: silently going unchecked.
RETAIL_STAGES: Final[Mapping[str, StageValidation]] = {
    "master-data": _master_data,
    "customers": _customers,
    "journey": _journey,
    "commerce": _commerce,
}


def run_stage(
    stage: str,
    config: SimulationConfig,
    context: BusinessContext,
    upstream: Frames,
    history: Frames,
) -> DayOfBusiness:
    """Run one Retail stage for one business date, and check what it produced.

    Args:
        stage: Which stage, as the domain names it.
        config: Retail settings.
        context: The business date and the enterprise seed.
        upstream: What earlier stages produced, as the plan requires it.
        history: What this stage has produced before.

    Returns:
        The day's work and the datasets as they now stand.

    Raises:
        StageExecutionError: If the stage is not one Retail runs
            (``CONFIGURATION``), if generation raised (``GENERATION``), or if
            what it produced does not hold up (``VALIDATION``).
    """
    checks = RETAIL_STAGES.get(stage)
    if checks is None:
        raise StageExecutionError(
            f"Retail has no work for stage {stage!r}; it runs {sorted(RETAIL_STAGES)}",
            FailureType.CONFIGURATION,
        )

    try:
        day = advance_day(stage, config, context, upstream, history)
    except (KeyError, ValueError) as exc:
        raise StageExecutionError(
            f"{stage} could not be generated: {exc}",
            FailureType.GENERATION,
            cause=repr(exc),
        ) from exc

    world = {**history, **upstream, **day.persisted}
    issues = list(checks(day.settings, world, day.generated))
    issues += validate_temporal_history(world)
    _refuse(stage, issues)
    return day


def _refuse(stage: str, issues: Sequence[ValidationIssue]) -> None:
    """Reject a day whose work does not hold up.

    Nothing is written when validation fails, which is what keeps a failed
    stage from leaving half-correct data behind for a later day to build on.

    Args:
        stage: The stage name, for the message.
        issues: What validation found.

    Raises:
        StageExecutionError: If any issue was found, carrying the first few so
            the message is useful without being a wall.
    """
    if not issues:
        return
    shown = "; ".join(str(issue) for issue in issues[:5])
    more = f" (and {len(issues) - 5} more)" if len(issues) > 5 else ""
    raise StageExecutionError(
        f"{stage} failed validation with {len(issues)} issue(s): {shown}{more}",
        FailureType.VALIDATION,
    )
