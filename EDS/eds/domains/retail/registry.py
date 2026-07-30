"""The Retail domain's self-description.

This is the concrete :class:`~eds.platform.domain.SimulationDomain` that makes
the protocol a real abstraction rather than a speculative one.

Everything here is *derived* from the same declarations the CLI and the
generators already use - the dataset registries and the ``REQUIRED_*``
constants - so the description cannot drift from the implementation. A feature
that adds a dataset without declaring it, or that starts reading an upstream
dataset it never declared, changes these values and fails the tests that pin
them.

The imports are deferred into the properties on purpose. ``import
eds.domains.retail`` registers the domain, and registration must stay cheap:
pulling every generator module in at import time would make merely *knowing
that Retail exists* cost as much as running it.
"""

from __future__ import annotations

from eds.platform.domain import DomainStage, register_domain

__all__ = ["RETAIL_DOMAIN_NAME", "RetailDomain"]

#: Registry name for this domain.
RETAIL_DOMAIN_NAME = "retail"


def _master_stage() -> DomainStage:
    """Describe the ``master-data`` stage."""
    from eds.domains.retail.domain.master_data import dataset_names

    return DomainStage(name="master-data", requires=(), produces=dataset_names())


def _customers_stage() -> DomainStage:
    """Describe the ``customers`` stage."""
    from eds.domains.retail.domain.customer.schema import customer_dataset_names
    from eds.domains.retail.generators.customer_data import REQUIRED_MASTER_DATASETS

    return DomainStage(
        name="customers",
        requires=REQUIRED_MASTER_DATASETS,
        produces=customer_dataset_names(),
    )


def _journey_stage() -> DomainStage:
    """Describe the ``journey`` stage.

    The stage runs three features in one command, so what it *requires* is the
    union of their inputs minus whatever it produces along the way - the same
    subtraction the CLI performs.
    """
    from eds.domains.retail.domain.journey.schema import (
        browsing_dataset_names,
        engagement_dataset_names,
        journey_dataset_names,
    )
    from eds.domains.retail.generators.journey.browsing import REQUIRED_BROWSING_DATASETS
    from eds.domains.retail.generators.journey.engagement import REQUIRED_ENGAGEMENT_DATASETS
    from eds.domains.retail.generators.journey.journey import REQUIRED_UPSTREAM_DATASETS

    produces = (*journey_dataset_names(), *browsing_dataset_names(), *engagement_dataset_names())
    requires = dict.fromkeys(
        (
            *REQUIRED_UPSTREAM_DATASETS,
            *REQUIRED_BROWSING_DATASETS,
            *REQUIRED_ENGAGEMENT_DATASETS,
        )
    )
    return DomainStage(
        name="journey",
        requires=tuple(name for name in requires if name not in set(produces)),
        produces=produces,
    )


def _commerce_stage() -> DomainStage:
    """Describe the ``commerce`` stage.

    Seven features run in one command, F004 through F010, each consuming the
    previous one's output.
    """
    from eds.domains.retail.domain.commerce.schema import (
        checkout_dataset_names,
        commerce_dataset_names,
        order_dataset_names,
        payment_dataset_names,
        return_dataset_names,
        review_dataset_names,
        shipment_dataset_names,
    )
    from eds.domains.retail.generators.commerce.checkout_generator import (
        REQUIRED_CHECKOUT_DATASETS,
    )
    from eds.domains.retail.generators.commerce.commerce import REQUIRED_COMMERCE_DATASETS
    from eds.domains.retail.generators.commerce.orders import REQUIRED_ORDER_DATASETS
    from eds.domains.retail.generators.commerce.payments import REQUIRED_PAYMENT_DATASETS
    from eds.domains.retail.generators.commerce.returns import REQUIRED_RETURN_DATASETS
    from eds.domains.retail.generators.commerce.reviews import REQUIRED_REVIEW_DATASETS
    from eds.domains.retail.generators.commerce.shipments import REQUIRED_SHIPMENT_DATASETS

    produces = (
        *commerce_dataset_names(),
        *checkout_dataset_names(),
        *order_dataset_names(),
        *payment_dataset_names(),
        *shipment_dataset_names(),
        *return_dataset_names(),
        *review_dataset_names(),
    )
    requires = dict.fromkeys(
        (
            *REQUIRED_COMMERCE_DATASETS,
            *REQUIRED_CHECKOUT_DATASETS,
            *REQUIRED_ORDER_DATASETS,
            *REQUIRED_PAYMENT_DATASETS,
            *REQUIRED_SHIPMENT_DATASETS,
            *REQUIRED_RETURN_DATASETS,
            *REQUIRED_REVIEW_DATASETS,
        )
    )
    return DomainStage(
        name="commerce",
        requires=tuple(name for name in requires if name not in set(produces)),
        produces=produces,
    )


class RetailDomain:
    """The Retail simulation domain, described for the platform.

    Satisfies :class:`~eds.platform.domain.SimulationDomain`.
    """

    @property
    def name(self) -> str:
        """Return the domain's registry name."""
        return RETAIL_DOMAIN_NAME

    @property
    def stages(self) -> tuple[DomainStage, ...]:
        """Return the four stages in execution order.

        These are the four ``eds generate`` commands. The order is a real
        dependency order: each stage reads what the ones before it wrote.
        """
        return (_master_stage(), _customers_stage(), _journey_stage(), _commerce_stage())

    @property
    def dataset_names(self) -> tuple[str, ...]:
        """Return every dataset Retail produces, in dependency order."""
        return tuple(name for stage in self.stages for name in stage.produces)


register_domain(RetailDomain())
