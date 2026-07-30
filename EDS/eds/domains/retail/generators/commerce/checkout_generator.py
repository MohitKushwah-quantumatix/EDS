"""Generator for the checkout dataset.

A checkout is the attempt to pay for a cart. Only carts F004 marked
``CHECKED_OUT`` are eligible, and each one produces exactly one checkout - the
cart status records the customer's intent to pay, while ``checkout_status``
records how that attempt actually ended.

Money is computed rather than sampled: the subtotal is summed from the cart's
own items, and the total is the sum of its parts, so the figures reconcile
against the upstream data instead of merely looking plausible.
"""

from __future__ import annotations

import random
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import polars as pl

from eds.config import CheckoutConfig, SimulationConfig
from eds.core.frames import build_frame, empty_frame
from eds.core.random_streams import make_rng, resolve_seed
from eds.domains.retail.domain.commerce.enums import (
    CartStatus,
    CheckoutStatus,
    PaymentMethod,
    ShippingMethod,
)
from eds.domains.retail.domain.commerce.schema import CHECKOUT, CHECKOUT_DATASETS

__all__ = [
    "MONEY_PRECISION",
    "REQUIRED_CHECKOUT_DATASETS",
    "SHIPPING_COST_BANDS",
    "CheckoutData",
    "generate_checkout_data",
    "generate_checkouts",
    "iter_checkout_batches",
]

#: The datasets F005 needs from earlier features.
REQUIRED_CHECKOUT_DATASETS: tuple[str, ...] = (
    "customers",
    "customer_addresses",
    "sessions",
    "shopping_carts",
    "cart_items",
)

_STATUSES: Final[tuple[CheckoutStatus, ...]] = (
    CheckoutStatus.SUCCESS,
    CheckoutStatus.FAILED,
    CheckoutStatus.ABANDONED,
)
_STATUS_WEIGHTS: Final[tuple[int, ...]] = (82, 8, 10)

_SHIPPING_METHODS: Final[tuple[ShippingMethod, ...]] = (
    ShippingMethod.STANDARD,
    ShippingMethod.EXPRESS,
    ShippingMethod.NEXT_DAY,
    ShippingMethod.STORE_PICKUP,
)
_SHIPPING_WEIGHTS: Final[tuple[int, ...]] = (70, 20, 5, 5)

#: Cost band per shipping method. Collecting in store is free.
SHIPPING_COST_BANDS: Final[dict[ShippingMethod, tuple[float, float]]] = {
    ShippingMethod.STANDARD: (0.0, 8.0),
    ShippingMethod.EXPRESS: (8.0, 20.0),
    ShippingMethod.NEXT_DAY: (20.0, 35.0),
    ShippingMethod.STORE_PICKUP: (0.0, 0.0),
}

_PAYMENT_METHODS: Final[tuple[PaymentMethod, ...]] = (
    PaymentMethod.UPI,
    PaymentMethod.CREDIT_CARD,
    PaymentMethod.DEBIT_CARD,
    PaymentMethod.COD,
    PaymentMethod.NET_BANKING,
    PaymentMethod.WALLET,
)
_PAYMENT_WEIGHTS: Final[tuple[int, ...]] = (35, 25, 15, 10, 10, 5)

#: Money is rounded to whole cents.
MONEY_PRECISION: Final[int] = 2

# The checkout begins a moment after the cart was last touched.
_CHECKOUT_LEAD_SECONDS: Final[int] = 1

# Promotions are a later feature, so nothing is discounted yet.
_DISCOUNT_AMOUNT: Final[float] = 0.0


@dataclass(frozen=True, slots=True)
class CheckoutData:
    """The generated checkout dataset.

    Attributes:
        datasets: Dataset name to frame.
        seed: The resolved seed the run used.
    """

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        """Return one dataset by name.

        Args:
            name: Dataset name, which is ``"checkout"``.

        Returns:
            The generated frame.

        Raises:
            KeyError: If the dataset was not generated.
        """
        try:
            return self.datasets[name]
        except KeyError:
            raise KeyError(
                f"Unknown dataset {name!r}. Generated: {sorted(self.datasets)}"
            ) from None

    def __iter__(self) -> Iterator[tuple[str, pl.DataFrame]]:
        """Iterate over ``(name, frame)`` pairs."""
        return iter(self.datasets.items())

    def row_counts(self) -> dict[str, int]:
        """Return the row count of every dataset, keyed by name."""
        return {name: frame.height for name, frame in self.datasets.items()}

    def total_rows(self) -> int:
        """Return the total number of rows across every dataset."""
        return sum(frame.height for frame in self.datasets.values())


def _subtotals(cart_items: pl.DataFrame) -> dict[int, float]:
    """Sum the value of each cart's remaining items.

    Only items still in the cart at checkout are paid for, so an item the
    customer took back out - one carrying a ``removed_at`` - contributes
    nothing. A cart whose items were all removed has a subtotal of zero and
    is charged for shipping alone.

    Args:
        cart_items: The F004 cart items dataset.

    Returns:
        Cart id to its subtotal, rounded to whole cents.
    """
    if cart_items.is_empty():
        return {}

    totals = (
        cart_items.filter(pl.col("removed_at").is_null())
        .with_columns((pl.col("quantity") * pl.col("unit_price")).alias("line_total"))
        .group_by("cart_id")
        .agg(pl.col("line_total").sum().alias("subtotal"))
    )

    return {
        cart_id: round(value, MONEY_PRECISION)
        for cart_id, value in zip(
            totals["cart_id"].to_list(), totals["subtotal"].to_list(), strict=True
        )
    }


def _addresses_by_customer(addresses: pl.DataFrame) -> dict[int, list[int]]:
    """Group address identifiers by customer, primary address first.

    Args:
        addresses: The F002 customer addresses dataset.

    Returns:
        Customer id to their address ids, most preferred first.

    Raises:
        ValueError: If the dataset is empty, leaving nowhere to ship to.
    """
    if addresses.is_empty():
        raise ValueError("cannot generate checkouts: the customer addresses dataset is empty")

    ordered = addresses.sort("is_primary", "address_id", descending=[True, False])
    grouped: dict[int, list[int]] = {}
    for customer_id, address_id in zip(
        ordered["customer_id"].to_list(), ordered["address_id"].to_list(), strict=True
    ):
        grouped.setdefault(customer_id, []).append(address_id)
    return grouped


def _pick_addresses(
    rng: random.Random, available: list[int], config: CheckoutConfig
) -> tuple[int, int]:
    """Choose the shipping and billing addresses.

    Args:
        rng: Random source.
        available: The customer's addresses, primary first.
        config: Checkout configuration.

    Returns:
        The shipping and billing address ids. A customer with a single address
        bills to it, so the two are identical.
    """
    shipping = available[0]
    if len(available) == 1 or rng.random() < config.same_address_rate:
        return shipping, shipping
    return shipping, rng.choice(available[1:])


def iter_checkout_batches(
    config: CheckoutConfig,
    carts: pl.DataFrame,
    cart_items: pl.DataFrame,
    addresses: pl.DataFrame,
    seed: int,
) -> Iterator[pl.DataFrame]:
    """Yield checkouts in batches, one per eligible cart.

    Args:
        config: Checkout configuration.
        carts: The F004 shopping carts dataset.
        cart_items: The F004 cart items dataset.
        addresses: The F002 customer addresses dataset.
        seed: Run seed.

    Yields:
        Frames matching the checkout schema.

    Raises:
        ValueError: If the customer addresses dataset is empty.
    """
    rng = make_rng(seed, "checkout")
    subtotal_by_cart = _subtotals(cart_items)
    address_pool = _addresses_by_customer(addresses)

    eligible = carts.filter(pl.col("cart_status") == str(CartStatus.CHECKED_OUT)).sort("cart_id")

    checkout_ids: list[int] = []
    cart_ids: list[int] = []
    customer_ids: list[int] = []
    session_ids: list[int] = []
    shipping_addresses: list[int] = []
    billing_addresses: list[int] = []
    shipping_methods: list[str] = []
    payment_methods: list[str] = []
    statuses: list[str] = []
    subtotals: list[float] = []
    shipping_costs: list[float] = []
    taxes: list[float] = []
    discounts: list[float] = []
    totals: list[float] = []
    started: list[datetime] = []
    completed: list[datetime | None] = []
    created: list[datetime] = []

    next_checkout_id = 1

    def flush() -> pl.DataFrame:
        """Build a frame from the accumulated rows and reset the buffers."""
        frame = build_frame(
            CHECKOUT,
            {
                "checkout_id": checkout_ids,
                "cart_id": cart_ids,
                "customer_id": customer_ids,
                "session_id": session_ids,
                "shipping_address_id": shipping_addresses,
                "billing_address_id": billing_addresses,
                "shipping_method": shipping_methods,
                "payment_method": payment_methods,
                "checkout_status": statuses,
                "subtotal": subtotals,
                "shipping_cost": shipping_costs,
                "tax_amount": taxes,
                "discount_amount": discounts,
                "total_amount": totals,
                "started_at": started,
                "completed_at": completed,
                "created_at": created,
            },
        )
        for buffer in (
            checkout_ids,
            cart_ids,
            customer_ids,
            session_ids,
            shipping_addresses,
            billing_addresses,
            shipping_methods,
            payment_methods,
            statuses,
            subtotals,
            shipping_costs,
            taxes,
            discounts,
            totals,
            started,
            completed,
            created,
        ):
            buffer.clear()
        return frame

    for cart_id, customer_id, session_id, updated_at in zip(
        eligible["cart_id"].to_list(),
        eligible["customer_id"].to_list(),
        eligible["session_id"].to_list(),
        eligible["updated_at"].to_list(),
        strict=True,
    ):
        available = address_pool.get(customer_id)
        if not available:
            # No address on file, so there is nowhere to ship to.
            continue

        shipping_method = rng.choices(_SHIPPING_METHODS, weights=_SHIPPING_WEIGHTS, k=1)[0]
        status = rng.choices(_STATUSES, weights=_STATUS_WEIGHTS, k=1)[0]
        shipping_address, billing_address = _pick_addresses(rng, available, config)

        subtotal = subtotal_by_cart.get(cart_id, 0.0)
        low, high = SHIPPING_COST_BANDS[shipping_method]
        shipping_cost = round(rng.uniform(low, high), MONEY_PRECISION)
        tax = round(
            subtotal * rng.uniform(config.min_tax_rate, config.max_tax_rate),
            MONEY_PRECISION,
        )
        total = round(subtotal + shipping_cost + tax - _DISCOUNT_AMOUNT, MONEY_PRECISION)

        # The checkout begins once the cart has stopped changing.
        began = updated_at + timedelta(seconds=_CHECKOUT_LEAD_SECONDS)
        duration = rng.randint(config.min_checkout_seconds, config.max_checkout_seconds)
        # An abandoned checkout was never completed.
        finished = (
            None if status is CheckoutStatus.ABANDONED else began + timedelta(seconds=duration)
        )

        checkout_ids.append(next_checkout_id)
        cart_ids.append(cart_id)
        customer_ids.append(customer_id)
        session_ids.append(session_id)
        shipping_addresses.append(shipping_address)
        billing_addresses.append(billing_address)
        shipping_methods.append(str(shipping_method))
        payment_methods.append(str(rng.choices(_PAYMENT_METHODS, weights=_PAYMENT_WEIGHTS, k=1)[0]))
        statuses.append(str(status))
        subtotals.append(subtotal)
        shipping_costs.append(shipping_cost)
        taxes.append(tax)
        discounts.append(_DISCOUNT_AMOUNT)
        totals.append(total)
        started.append(began)
        completed.append(finished)
        created.append(began)
        next_checkout_id += 1

        if len(checkout_ids) >= config.batch_size:
            yield flush()

    if checkout_ids:
        yield flush()


def generate_checkouts(
    config: CheckoutConfig,
    carts: pl.DataFrame,
    cart_items: pl.DataFrame,
    addresses: pl.DataFrame,
    seed: int,
) -> pl.DataFrame:
    """Generate the complete checkout dataset.

    Args:
        config: Checkout configuration.
        carts: The F004 shopping carts dataset.
        cart_items: The F004 cart items dataset.
        addresses: The F002 customer addresses dataset.
        seed: Run seed.

    Returns:
        One row per checked-out cart, keyed by sequential ``checkout_id``.

    Raises:
        ValueError: If the customer addresses dataset is empty.
    """
    batches = list(iter_checkout_batches(config, carts, cart_items, addresses, seed))
    return pl.concat(batches, how="vertical") if batches else empty_frame(CHECKOUT)


def generate_checkout_data(
    config: SimulationConfig, upstream: Mapping[str, pl.DataFrame]
) -> CheckoutData:
    """Generate checkouts from existing carts.

    Args:
        config: The complete run configuration.
        upstream: The earlier datasets, which must include the entries in
            :data:`REQUIRED_CHECKOUT_DATASETS`.

    Returns:
        The generated bundle, including the resolved seed.

    Raises:
        KeyError: If a required upstream dataset is absent.
        ValueError: If the customer addresses dataset is empty.
    """
    missing = [name for name in REQUIRED_CHECKOUT_DATASETS if name not in upstream]
    if missing:
        raise KeyError(
            f"Missing upstream data required by F005: {missing}. "
            "Run `eds generate master-data`, `eds generate customers`, "
            "`eds generate journey`, and `eds generate commerce` first."
        )

    seed = resolve_seed(config.platform.seed)
    checkouts = generate_checkouts(
        config.checkout,
        upstream["shopping_carts"],
        upstream["cart_items"],
        upstream["customer_addresses"],
        seed,
    )

    datasets = {dataset.name: checkouts for dataset in CHECKOUT_DATASETS}
    return CheckoutData(datasets=datasets, seed=seed)
