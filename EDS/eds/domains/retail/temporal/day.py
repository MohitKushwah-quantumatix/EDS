"""One business day of Retail, whichever day it is.

This is the domain's entry point for running itself. Ask it for a stage and a
business date, give it what that stage needs to read, and it returns what the
day produced and what the datasets now hold.

**A stage founds itself the first time it runs.** There is no tick counter and
no "first run" flag: a stage whose own datasets are empty has no history to
continue, so it builds one, and a stage that has history continues it. That
single rule is what makes every awkward case work out. A run that stopped
half-way through the founding day and was picked up later founds the stages
that never ran and evolves the ones that did. A run continued a year after the
last one continues from what is on disk. Nothing has to remember which tick it
is, because *the data is the state*.

**The execution date is the reference date.** Retail used to generate against
a fixed ``reference_date`` in its configuration, which is why every tick
produced the same enterprise. That setting is now a default for callers who
have no business date to offer; when a date is supplied, it wins, and it is
what the day is generated relative to.

Nothing here knows what advanced the date, and nothing here can advance it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import polars as pl

from eds.domains.retail.config import SimulationConfig
from eds.domains.retail.domain.commerce.schema import (
    checkout_dataset_names,
    commerce_dataset_names,
    order_dataset_names,
    payment_dataset_names,
    return_dataset_names,
    review_dataset_names,
    shipment_dataset_names,
)
from eds.domains.retail.domain.customer.schema import customer_dataset_names
from eds.domains.retail.domain.journey.schema import (
    browsing_dataset_names,
    engagement_dataset_names,
    journey_dataset_names,
)
from eds.domains.retail.domain.master_data import dataset_names as master_dataset_names
from eds.domains.retail.generators.commerce.checkout_generator import generate_checkout_data
from eds.domains.retail.generators.commerce.commerce import generate_commerce_data
from eds.domains.retail.generators.commerce.orders import generate_order_data
from eds.domains.retail.generators.commerce.payments import generate_payment_data
from eds.domains.retail.generators.commerce.returns import generate_return_data
from eds.domains.retail.generators.commerce.reviews import generate_review_data
from eds.domains.retail.generators.commerce.shipments import generate_shipment_data
from eds.domains.retail.generators.customer_data import generate_customer_data
from eds.domains.retail.generators.journey.browsing import generate_browsing_data
from eds.domains.retail.generators.journey.engagement import generate_engagement_data
from eds.domains.retail.generators.journey.journey import generate_journey_data
from eds.domains.retail.generators.master_data import generate_master_data
from eds.domains.retail.temporal.context import BusinessContext
from eds.domains.retail.temporal.evolution import (
    evolve_commerce,
    evolve_customers,
    evolve_journey,
    evolve_master_data,
)
from eds.domains.retail.temporal.merge import merge_history

__all__ = [
    "HISTORY_READ",
    "RETAIL_STAGE_NAMES",
    "STAGE_DATASETS",
    "DayOfBusiness",
    "advance_day",
]

Frames = dict[str, pl.DataFrame]

#: What each Retail stage produces, in dependency order. Derived from the same
#: schema declarations the domain describes itself with, and pinned against
#: them by a test.
STAGE_DATASETS: Final[Mapping[str, tuple[str, ...]]] = {
    "master-data": master_dataset_names(),
    "customers": customer_dataset_names(),
    "journey": (
        *journey_dataset_names(),
        *browsing_dataset_names(),
        *engagement_dataset_names(),
    ),
    "commerce": (
        *commerce_dataset_names(),
        *checkout_dataset_names(),
        *order_dataset_names(),
        *payment_dataset_names(),
        *shipment_dataset_names(),
        *return_dataset_names(),
        *review_dataset_names(),
    ),
}

#: The four stages, in execution order.
RETAIL_STAGE_NAMES: Final[tuple[str, ...]] = tuple(STAGE_DATASETS)

#: What each stage must be shown of the past, on top of what the execution
#: plan already says it requires.
#:
#: A stage always reads its own datasets: continuing a history means knowing
#: what the history is. Two stages read a little further, and both readings are
#: business facts rather than conveniences - stock falls because things were
#: sold, and loyalty points are earned by spending. Neither relationship can be
#: expressed as a plan dependency, because the datasets that carry them are
#: produced by a *later* stage in the same day; a plan that declared them would
#: be describing a cycle.
HISTORY_READ: Final[Mapping[str, tuple[str, ...]]] = {
    "master-data": (*STAGE_DATASETS["master-data"], "orders", "order_lines"),
    "customers": (*STAGE_DATASETS["customers"], "orders"),
    "journey": STAGE_DATASETS["journey"],
    "commerce": STAGE_DATASETS["commerce"],
}


@dataclass(frozen=True, slots=True)
class DayOfBusiness:
    """What one stage did on one business date.

    Attributes:
        generated: The rows this day created. What a validator should be shown:
            checking a day's work against a day's rules is meaningful, and
            checking one day's rules against ten years of accumulated history
            is not.
        persisted: Every dataset the stage changed, as it now stands. What a
            writer should be given.
        settings: The settings the day was generated with, including the
            business date as the reference date.
        is_founding: Whether this stage had no history and built one.
    """

    generated: Mapping[str, pl.DataFrame]
    persisted: Mapping[str, pl.DataFrame]
    settings: SimulationConfig
    is_founding: bool


def advance_day(
    stage: str,
    config: SimulationConfig,
    context: BusinessContext,
    upstream: Mapping[str, pl.DataFrame],
    history: Mapping[str, pl.DataFrame],
) -> DayOfBusiness:
    """Run one Retail stage for one business date.

    Args:
        stage: Which stage, as the domain names it.
        config: Retail settings. The business date replaces the configured
            reference date.
        context: The business date and the enterprise seed.
        upstream: What earlier stages produced, as the plan requires it.
        history: What this stage has produced before, and anything else it
            reads of the past. Empty on a founding day.

    Returns:
        What the day produced and what the datasets now hold.

    Raises:
        KeyError: If the stage is not one Retail runs, or a required dataset
            is absent.
        ValueError: If a required dataset is unusable.
    """
    if stage not in STAGE_DATASETS:
        raise KeyError(f"Retail runs no stage named {stage!r}; it runs {RETAIL_STAGE_NAMES}")

    settings = config.model_copy(
        update={
            "customers": config.customers.model_copy(
                update={"reference_date": context.business_date}
            )
        }
    )
    if _founding(stage, history):
        generated = _found(stage, settings, upstream)
        return DayOfBusiness(generated, generated, settings, is_founding=True)

    generated = _evolve(stage, settings, context, upstream, history)
    return DayOfBusiness(generated, merge_history(history, generated), settings, is_founding=False)


def _founding(stage: str, history: Mapping[str, pl.DataFrame]) -> bool:
    """Report whether this stage has anything to continue.

    Args:
        stage: Which stage.
        history: What it has produced before.

    Returns:
        Whether every dataset the stage produces is absent or empty.
    """
    return all(name not in history or history[name].is_empty() for name in STAGE_DATASETS[stage])


def _found(stage: str, config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]) -> Frames:
    """Build a stage's datasets from nothing.

    Args:
        stage: Which stage.
        config: Retail settings, as of the business date.
        upstream: What earlier stages produced.

    Returns:
        Every dataset the stage produces.

    Raises:
        KeyError: If a required upstream dataset is absent.
        ValueError: If a required upstream dataset is unusable.
    """
    match stage:
        case "master-data":
            return dict(generate_master_data(config).datasets)
        case "customers":
            return dict(generate_customer_data(config, upstream).datasets)
        case "journey":
            journey = generate_journey_data(config, upstream)
            browsing = generate_browsing_data(config, {**upstream, **journey.datasets})
            engagement = generate_engagement_data(
                config, {**upstream, **journey.datasets, **browsing.datasets}
            )
            return {**journey.datasets, **browsing.datasets, **engagement.datasets}
        case _:
            return _found_commerce(config, upstream)


def _found_commerce(config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]) -> Frames:
    """Build the fifteen commerce datasets from nothing.

    Seven features, F004 through F010, each narrowing the one before it: a
    session may open a cart, a cart may reach checkout, a checkout becomes an
    order, an order is paid and shipped, a shipment may come back, and a
    delivered item that was kept may be reviewed.

    Args:
        config: Retail settings, as of the business date.
        upstream: What earlier stages produced.

    Returns:
        The fifteen commerce datasets.

    Raises:
        KeyError: If a required upstream dataset is absent.
        ValueError: If a required upstream dataset is unusable.
    """
    commerce = generate_commerce_data(config, upstream)
    checkout = generate_checkout_data(config, {**upstream, **commerce.datasets})
    orders = generate_order_data(config, {**upstream, **commerce.datasets, **checkout.datasets})
    placed = {**upstream, **commerce.datasets, **checkout.datasets, **orders.datasets}
    payments = generate_payment_data(config, placed)
    shipments = generate_shipment_data(config, {**placed, **payments.datasets})
    fulfilled = {**placed, **payments.datasets, **shipments.datasets}
    returns = generate_return_data(config, fulfilled)
    reviews = generate_review_data(config, {**fulfilled, **returns.datasets})
    return {
        **commerce.datasets,
        **checkout.datasets,
        **orders.datasets,
        **payments.datasets,
        **shipments.datasets,
        **returns.datasets,
        **reviews.datasets,
    }


def _evolve(
    stage: str,
    config: SimulationConfig,
    context: BusinessContext,
    upstream: Mapping[str, pl.DataFrame],
    history: Mapping[str, pl.DataFrame],
) -> Frames:
    """Add one day to a stage's history.

    Args:
        stage: Which stage.
        config: Retail settings, as of the business date.
        context: The business date and the enterprise seed.
        upstream: What earlier stages produced.
        history: What this stage has produced before.

    Returns:
        The datasets this day changed, which may be none of them.

    Raises:
        KeyError: If a required upstream dataset is absent.
        ValueError: If a required upstream dataset is unusable.
    """
    match stage:
        case "master-data":
            return evolve_master_data(config, context, history)
        case "customers":
            return evolve_customers(config, context, upstream, history)
        case "journey":
            return evolve_journey(config, context, upstream, history)
        case _:
            return evolve_commerce(config, context, upstream, history)
