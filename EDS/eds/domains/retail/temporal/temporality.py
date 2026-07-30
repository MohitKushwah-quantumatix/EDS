"""How each Retail dataset behaves when a day passes.

Four behaviours cover all thirty-nine, and every dataset declares exactly one.
The classification is not decoration: :mod:`eds.domains.retail.temporal.merge`
reads it to decide what happens to a dataset when a day's work arrives, so a
dataset classified wrongly behaves wrongly, and a dataset not classified at all
cannot be merged.

**Why four and not three.** Append-only and mutable-snapshot are the obvious
pair: history that accumulates, and a current picture that is replaced.
Slowly-changing is the one that earns its place - a row per customer whose
*balance* moves while the row's identity and enrolment date do not. Static is
worth naming separately from mutable-snapshot even though both are "one
current picture", because static means *nothing writes it after the founding
day*, which is a stronger and cheaper promise: over three hundred and
sixty-five days, the eleven static datasets are written once.

**This classification belongs to Retail.** The adapters know nothing about it
and should not: a dataset's temporality is a statement about a *business*, not
about storage.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

__all__ = ["DATASET_TEMPORALITY", "Temporality", "temporality_of"]


class Temporality(StrEnum):
    """How a dataset changes as simulated time advances.

    Attributes:
        STATIC: Written on the founding day and never again. Reference data
            and the catalogue: countries, categories, products.
        APPEND_ONLY: History. New rows are added and no existing row is ever
            altered or removed. Sessions, orders, payments, reviews.
        MUTABLE_SNAPSHOT: The current state of something, replaced in full
            each day it changes. Inventory levels.
        SLOWLY_CHANGING: One row per subject, kept for the life of that
            subject, with a few attributes that move. Loyalty balances.
    """

    STATIC = "static"
    APPEND_ONLY = "append-only"
    MUTABLE_SNAPSHOT = "mutable-snapshot"
    SLOWLY_CHANGING = "slowly-changing"


#: What each Retail dataset does when a day passes.
#:
#: A test asserts this covers exactly the datasets the domain declares, so a
#: feature that adds a dataset must say how it behaves in time before it can
#: run for a second day.
DATASET_TEMPORALITY: Final[Mapping[str, Temporality]] = {
    # Master data. Geography, the commercial catalogues, the supply chain and
    # the product catalogue are the enterprise's fixtures: a day of trading
    # does not open a country or invent a category.
    "countries": Temporality.STATIC,
    "states": Temporality.STATIC,
    "cities": Temporality.STATIC,
    "payment_methods": Temporality.STATIC,
    "shipping_methods": Temporality.STATIC,
    "tax_codes": Temporality.STATIC,
    "coupon_types": Temporality.STATIC,
    "return_reasons": Temporality.STATIC,
    "suppliers": Temporality.STATIC,
    "warehouses": Temporality.STATIC,
    "categories": Temporality.STATIC,
    "brands": Temporality.STATIC,
    "products": Temporality.STATIC,
    # The one master dataset that is not a fixture. Stock is consumed by what
    # was sold and replenished by the reorder policy, so it is a picture of
    # now rather than a record of what happened.
    "inventory": Temporality.MUTABLE_SNAPSHOT,
    # Customers. A person who registered on the fourth of March registered on
    # the fourth of March for ever, so the customer row and everything created
    # with it is history.
    "customers": Temporality.APPEND_ONLY,
    "customer_addresses": Temporality.APPEND_ONLY,
    "customer_preferences": Temporality.APPEND_ONLY,
    # The exception, and the reason the fourth kind exists: one row per
    # customer, enrolled once, whose balance and tier move with spending.
    "customer_loyalty": Temporality.SLOWLY_CHANGING,
    # The journey. A persona is assigned when a customer arrives and is not
    # revisited; everything else is a record of a visit.
    "customer_personas": Temporality.APPEND_ONLY,
    "sessions": Temporality.APPEND_ONLY,
    "category_views": Temporality.APPEND_ONLY,
    "search_history": Temporality.APPEND_ONLY,
    "product_views": Temporality.APPEND_ONLY,
    "wishlists": Temporality.APPEND_ONLY,
    # Commerce. All of it is history by definition: a cart was filled, an
    # order was placed, money moved, a parcel arrived, a customer wrote a
    # review. None of that unhappens.
    "shopping_carts": Temporality.APPEND_ONLY,
    "cart_items": Temporality.APPEND_ONLY,
    "checkout": Temporality.APPEND_ONLY,
    "orders": Temporality.APPEND_ONLY,
    "order_lines": Temporality.APPEND_ONLY,
    "order_status_history": Temporality.APPEND_ONLY,
    "payments": Temporality.APPEND_ONLY,
    "payment_status_history": Temporality.APPEND_ONLY,
    "shipments": Temporality.APPEND_ONLY,
    "shipment_items": Temporality.APPEND_ONLY,
    "shipment_status_history": Temporality.APPEND_ONLY,
    "returns": Temporality.APPEND_ONLY,
    "return_items": Temporality.APPEND_ONLY,
    "return_status_history": Temporality.APPEND_ONLY,
    "reviews": Temporality.APPEND_ONLY,
}


def temporality_of(name: str) -> Temporality:
    """Return how a dataset behaves as simulated time advances.

    Args:
        name: Dataset name, such as ``"inventory"``.

    Returns:
        Its temporality.

    Raises:
        KeyError: If the dataset has not declared one. Refusing to guess is
            the point: a dataset with no declared temporality has no defined
            behaviour on the second day, and silently appending to something
            that should have been replaced corrupts a history quietly.
    """
    try:
        return DATASET_TEMPORALITY[name]
    except KeyError:
        raise KeyError(
            f"dataset {name!r} has not declared how it behaves over time; "
            f"add it to DATASET_TEMPORALITY"
        ) from None
