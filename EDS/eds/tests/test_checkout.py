"""Tests for the checkout generator and its configuration."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import polars as pl
import pytest

from eds.config import (
    CheckoutConfig,
    ConfigError,
    PlatformConfig,
    SimulationConfig,
    load_checkout_config,
    load_config,
)
from eds.domain.commerce.enums import (
    CartStatus,
    CheckoutStatus,
    PaymentMethod,
    ShippingMethod,
)
from eds.domain.commerce.schema import (
    CHECKOUT_DATASETS,
    COMMERCE_DATASETS,
    checkout_dataset_by_name,
    checkout_dataset_names,
)
from eds.generators.commerce.checkout_generator import (
    REQUIRED_CHECKOUT_DATASETS,
    SHIPPING_COST_BANDS,
    CheckoutData,
    generate_checkout_data,
    generate_checkouts,
    iter_checkout_batches,
)
from eds.validation.checkout_validation import validate_checkout_data

SEED = 9090
MONEY_TOLERANCE = 0.011


@pytest.fixture
def config() -> CheckoutConfig:
    """Return a checkout configuration with a small batch size."""
    return CheckoutConfig(batch_size=150)


@pytest.fixture
def checkouts(checkout_data: CheckoutData) -> pl.DataFrame:
    """Return the generated checkout frame."""
    return checkout_data["checkout"]


@pytest.fixture
def carts(checkout_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the shopping carts frame."""
    return checkout_upstream["shopping_carts"]


@pytest.fixture
def cart_items(checkout_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the cart items frame."""
    return checkout_upstream["cart_items"]


@pytest.fixture
def addresses(checkout_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the customer addresses frame."""
    return checkout_upstream["customer_addresses"]


@pytest.fixture
def many_checkouts(
    config: CheckoutConfig,
    carts: pl.DataFrame,
    cart_items: pl.DataFrame,
    addresses: pl.DataFrame,
) -> pl.DataFrame:
    """Return a large checkout sample for distribution assertions.

    The test fixtures are deliberately small, which leaves too few rows to
    assert a percentage split against. Replicating the eligible carts with
    fresh identifiers produces a sample big enough to measure without
    generating a whole second upstream pipeline.

    Args:
        config: Checkout configuration.
        carts: The shopping carts frame.
        cart_items: The cart items frame.
        addresses: The customer addresses frame.

    Returns:
        Checkouts generated from the replicated carts.
    """
    eligible = carts.filter(pl.col("cart_status") == str(CartStatus.CHECKED_OUT))
    offset = max(carts["cart_id"].to_list()) + 1
    replicated = pl.concat(
        [
            eligible.with_columns((pl.col("cart_id") + offset * copy).alias("cart_id"))
            for copy in range(40)
        ]
    )

    return generate_checkouts(config, replicated, cart_items, addresses, SEED)


def test_shipped_checkout_config_loads() -> None:
    """The committed checkout.yaml matches the documented defaults."""
    config = load_checkout_config()

    assert config.min_tax_rate == pytest.approx(0.05)
    assert config.max_tax_rate == pytest.approx(0.18)


def test_checkout_config_is_part_of_the_run_configuration() -> None:
    """`load_config` includes the checkout section."""
    assert load_config().checkout.max_tax_rate == pytest.approx(0.18)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_tax_rate", 1.5),
        ("max_tax_rate", -0.1),
        ("same_address_rate", 2.0),
        ("min_checkout_seconds", 0),
        ("batch_size", 0),
    ],
)
def test_out_of_range_checkout_values_are_rejected(field: str, value: float) -> None:
    """Settings outside their declared bounds fail validation."""
    with pytest.raises(ValueError, match=field):
        CheckoutConfig(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("low_field", "high_field", "low", "high"),
    [
        ("min_tax_rate", "max_tax_rate", 0.5, 0.1),
        ("min_checkout_seconds", "max_checkout_seconds", 900, 30),
    ],
)
def test_inverted_ranges_are_rejected(
    low_field: str, high_field: str, low: float, high: float
) -> None:
    """A minimum above its maximum is a configuration error."""
    with pytest.raises(ValueError, match="cannot exceed"):
        CheckoutConfig(**{low_field: low, high_field: high})  # type: ignore[arg-type]


def test_unknown_checkout_key_is_rejected() -> None:
    """A misspelled key is an error, not a silent no-op."""
    with pytest.raises(ValueError, match="tax_rate"):
        CheckoutConfig(tax_rate=0.1)  # type: ignore[call-arg]


def test_invalid_checkout_config_file_raises(tmp_path: Path) -> None:
    """An out-of-range value names the offending file."""
    (tmp_path / "checkout.yaml").write_text("max_tax_rate: 5.0\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="checkout.yaml"):
        load_checkout_config(tmp_path)


def test_registry_lists_the_one_documented_output() -> None:
    """F005 declares exactly one output dataset."""
    assert len(CHECKOUT_DATASETS) == 1
    assert set(checkout_dataset_names()) == {"checkout"}


def test_the_commerce_registry_is_unchanged() -> None:
    """F004's registry still declares only its own two datasets."""
    assert {dataset.name for dataset in COMMERCE_DATASETS} == {
        "shopping_carts",
        "cart_items",
    }


def test_dataset_file_name_matches_the_specification() -> None:
    """The dataset maps to the documented Parquet file name."""
    assert checkout_dataset_by_name("checkout").file_name == "checkout.parquet"


def test_unknown_checkout_dataset_lookup_raises() -> None:
    """Looking up an unregistered dataset fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown checkout dataset"):
        checkout_dataset_by_name("orders")


def test_one_checkout_per_checked_out_cart(checkouts: pl.DataFrame, carts: pl.DataFrame) -> None:
    """Every eligible cart produces exactly one checkout, and only those."""
    eligible = set(
        carts.filter(pl.col("cart_status") == str(CartStatus.CHECKED_OUT))["cart_id"].to_list()
    )

    assert set(checkouts["cart_id"].to_list()) == eligible
    assert checkouts["cart_id"].n_unique() == checkouts.height


def test_active_and_abandoned_carts_produce_no_checkout(
    checkouts: pl.DataFrame, carts: pl.DataFrame
) -> None:
    """Ineligible carts never appear."""
    ineligible = set(
        carts.filter(pl.col("cart_status") != str(CartStatus.CHECKED_OUT))["cart_id"].to_list()
    )

    assert not (set(checkouts["cart_id"].to_list()) & ineligible)


def test_checkout_ids_are_unique_and_sequential(checkouts: pl.DataFrame) -> None:
    """Checkout ids form a dense sequence starting at one."""
    assert checkouts["checkout_id"].to_list() == list(range(1, checkouts.height + 1))


def test_customer_and_session_come_from_the_cart(
    checkouts: pl.DataFrame, carts: pl.DataFrame
) -> None:
    """The checkout inherits the cart's customer and session."""
    joined = checkouts.join(
        carts.select(
            "cart_id",
            pl.col("customer_id").alias("cart_customer"),
            pl.col("session_id").alias("cart_session"),
        ),
        on="cart_id",
        how="inner",
    )

    assert joined.height == checkouts.height
    assert joined.filter(pl.col("customer_id") != pl.col("cart_customer")).height == 0
    assert joined.filter(pl.col("session_id") != pl.col("cart_session")).height == 0


def test_addresses_belong_to_the_checking_out_customer(
    checkouts: pl.DataFrame, addresses: pl.DataFrame
) -> None:
    """Neither address belongs to someone else."""
    owners = addresses.select("address_id", pl.col("customer_id").alias("owner"))

    for column in ("shipping_address_id", "billing_address_id"):
        joined = checkouts.join(owners.rename({"address_id": column}), on=column, how="inner")
        assert joined.height == checkouts.height, column
        assert joined.filter(pl.col("customer_id") != pl.col("owner")).height == 0, column


def test_single_address_customers_bill_to_their_only_address(
    checkouts: pl.DataFrame, addresses: pl.DataFrame
) -> None:
    """With one address on file, shipping and billing are identical."""
    counts = addresses.group_by("customer_id").len()
    single = set(counts.filter(pl.col("len") == 1)["customer_id"].to_list())
    subset = checkouts.filter(pl.col("customer_id").is_in(list(single)))

    assert subset.height > 0
    assert subset.filter(pl.col("shipping_address_id") != pl.col("billing_address_id")).height == 0


def test_some_customers_bill_to_a_different_address(checkouts: pl.DataFrame) -> None:
    """The separate-billing path is exercised."""
    differing = checkouts.filter(pl.col("shipping_address_id") != pl.col("billing_address_id"))

    assert differing.height > 0


@pytest.mark.parametrize(
    ("column", "enum"),
    [
        ("checkout_status", CheckoutStatus),
        ("shipping_method", ShippingMethod),
        ("payment_method", PaymentMethod),
    ],
)
def test_categorical_columns_use_declared_values(
    checkouts: pl.DataFrame, column: str, enum: type[StrEnum]
) -> None:
    """Every categorical column draws from its declared enum."""
    known = {str(member) for member in enum}

    assert set(checkouts[column].to_list()) <= known


def test_status_distribution_is_approximately_as_specified(
    many_checkouts: pl.DataFrame,
) -> None:
    """Statuses follow roughly the documented 82/8/10 split."""
    share = {
        row["checkout_status"]: row["count"] / many_checkouts.height
        for row in many_checkouts["checkout_status"].value_counts().to_dicts()
    }

    assert share[str(CheckoutStatus.SUCCESS)] == pytest.approx(0.82, abs=0.08)
    assert share[str(CheckoutStatus.FAILED)] == pytest.approx(0.08, abs=0.06)
    assert share[str(CheckoutStatus.ABANDONED)] == pytest.approx(0.10, abs=0.06)


def test_shipping_method_distribution_is_approximately_as_specified(
    many_checkouts: pl.DataFrame,
) -> None:
    """Shipping methods follow roughly the documented 70/20/5/5 split."""
    share = {
        row["shipping_method"]: row["count"] / many_checkouts.height
        for row in many_checkouts["shipping_method"].value_counts().to_dicts()
    }

    assert share[str(ShippingMethod.STANDARD)] == pytest.approx(0.70, abs=0.05)
    assert share[str(ShippingMethod.EXPRESS)] == pytest.approx(0.20, abs=0.05)
    assert share[str(ShippingMethod.NEXT_DAY)] == pytest.approx(0.05, abs=0.03)
    assert share[str(ShippingMethod.STORE_PICKUP)] == pytest.approx(0.05, abs=0.03)


def test_payment_method_distribution_is_approximately_as_specified(
    many_checkouts: pl.DataFrame,
) -> None:
    """Payment methods follow roughly the documented split."""
    share = {
        row["payment_method"]: row["count"] / many_checkouts.height
        for row in many_checkouts["payment_method"].value_counts().to_dicts()
    }

    assert share[str(PaymentMethod.UPI)] == pytest.approx(0.35, abs=0.05)
    assert share[str(PaymentMethod.CREDIT_CARD)] == pytest.approx(0.25, abs=0.05)
    assert share[str(PaymentMethod.DEBIT_CARD)] == pytest.approx(0.15, abs=0.05)
    assert share[str(PaymentMethod.NET_BANKING)] == pytest.approx(0.10, abs=0.04)
    assert share[str(PaymentMethod.COD)] == pytest.approx(0.10, abs=0.04)
    assert share[str(PaymentMethod.WALLET)] == pytest.approx(0.05, abs=0.03)


def test_subtotal_matches_the_remaining_cart_items(
    checkouts: pl.DataFrame, cart_items: pl.DataFrame
) -> None:
    """The subtotal sums quantity times unit price over items still present."""
    expected = (
        cart_items.filter(pl.col("removed_at").is_null())
        .with_columns((pl.col("quantity") * pl.col("unit_price")).alias("line"))
        .group_by("cart_id")
        .agg(pl.col("line").sum().alias("expected"))
    )
    joined = checkouts.join(expected, on="cart_id", how="left").with_columns(
        pl.col("expected").fill_null(0.0)
    )

    assert joined.height == checkouts.height
    assert (
        joined.filter((pl.col("subtotal") - pl.col("expected")).abs() > MONEY_TOLERANCE).height == 0
    )


def test_removed_items_are_excluded_from_the_subtotal(
    checkouts: pl.DataFrame, cart_items: pl.DataFrame
) -> None:
    """A cart that lost an item is charged less than everything ever added."""
    with_removals = set(cart_items.filter(pl.col("removed_at").is_not_null())["cart_id"].to_list())
    everything = (
        cart_items.with_columns((pl.col("quantity") * pl.col("unit_price")).alias("line"))
        .group_by("cart_id")
        .agg(pl.col("line").sum().alias("all_items"))
    )
    affected = checkouts.filter(pl.col("cart_id").is_in(list(with_removals))).join(
        everything, on="cart_id", how="inner"
    )

    assert affected.height > 0, "no checked-out cart lost an item in this sample"
    assert affected.filter(pl.col("subtotal") >= pl.col("all_items")).height == 0


def test_tax_and_total_follow_the_corrected_subtotal(
    checkouts: pl.DataFrame, cart_items: pl.DataFrame, config: CheckoutConfig
) -> None:
    """Tax and total derive from the remaining items, not everything added."""
    remaining = (
        cart_items.filter(pl.col("removed_at").is_null())
        .with_columns((pl.col("quantity") * pl.col("unit_price")).alias("line"))
        .group_by("cart_id")
        .agg(pl.col("line").sum().alias("remaining"))
    )
    with_removals = set(cart_items.filter(pl.col("removed_at").is_not_null())["cart_id"].to_list())
    affected = (
        checkouts.filter(pl.col("cart_id").is_in(list(with_removals)))
        .join(remaining, on="cart_id", how="left")
        .with_columns(pl.col("remaining").fill_null(0.0))
        .filter(pl.col("remaining") > 0)
    )

    assert affected.height > 0

    # Tax is a share of the corrected subtotal, never of the fuller basket.
    rates = [
        tax / subtotal
        for tax, subtotal in zip(
            affected["tax_amount"].to_list(), affected["remaining"].to_list(), strict=True
        )
    ]
    assert min(rates) >= config.min_tax_rate - 0.01
    assert max(rates) <= config.max_tax_rate + 0.01

    # And the total is built from that same corrected figure.
    assert (
        affected.filter(
            (
                pl.col("total_amount")
                - (
                    pl.col("remaining")
                    + pl.col("shipping_cost")
                    + pl.col("tax_amount")
                    - pl.col("discount_amount")
                )
            ).abs()
            > MONEY_TOLERANCE
        ).height
        == 0
    )


def test_a_fully_emptied_cart_is_charged_shipping_only(
    config: CheckoutConfig,
    carts: pl.DataFrame,
    cart_items: pl.DataFrame,
    addresses: pl.DataFrame,
) -> None:
    """With every item removed the subtotal and tax fall to zero."""
    emptied = cart_items.with_columns(pl.col("added_at").alias("removed_at"))

    result = generate_checkouts(config, carts, emptied, addresses, SEED)

    assert result.height > 0
    assert set(result["subtotal"].to_list()) == {0.0}
    assert set(result["tax_amount"].to_list()) == {0.0}
    assert (
        result.filter(
            (pl.col("total_amount") - pl.col("shipping_cost")).abs() > MONEY_TOLERANCE
        ).height
        == 0
    )


def test_total_is_the_sum_of_its_parts(checkouts: pl.DataFrame) -> None:
    """Totals reconcile exactly."""
    mismatched = checkouts.filter(
        (
            pl.col("total_amount")
            - (
                pl.col("subtotal")
                + pl.col("shipping_cost")
                + pl.col("tax_amount")
                - pl.col("discount_amount")
            )
        ).abs()
        > MONEY_TOLERANCE
    )

    assert mismatched.height == 0


def test_no_amount_is_negative(checkouts: pl.DataFrame) -> None:
    """Money never goes below zero."""
    for column in (
        "subtotal",
        "shipping_cost",
        "tax_amount",
        "discount_amount",
        "total_amount",
    ):
        assert checkouts.filter(pl.col(column) < 0).height == 0, column


def test_discounts_are_zero_until_promotions_exist(checkouts: pl.DataFrame) -> None:
    """Promotions are a later feature, so nothing is discounted."""
    assert set(checkouts["discount_amount"].to_list()) == {0.0}


def test_shipping_cost_respects_its_method_band(checkouts: pl.DataFrame) -> None:
    """Each shipping method charges inside its documented band."""
    for method, (low, high) in SHIPPING_COST_BANDS.items():
        subset = checkouts.filter(pl.col("shipping_method") == str(method))
        if subset.is_empty():
            continue
        costs = subset["shipping_cost"].to_list()
        assert min(costs) >= low - MONEY_TOLERANCE, method
        assert max(costs) <= high + MONEY_TOLERANCE, method


def test_store_pickup_is_free(checkouts: pl.DataFrame) -> None:
    """Collecting in store costs nothing."""
    pickup = checkouts.filter(pl.col("shipping_method") == str(ShippingMethod.STORE_PICKUP))

    assert pickup.height > 0
    assert set(pickup["shipping_cost"].to_list()) == {0.0}


def test_tax_falls_within_the_configured_band(
    checkouts: pl.DataFrame, config: CheckoutConfig
) -> None:
    """Tax is between five and eighteen per cent of the subtotal."""
    priced = checkouts.filter(pl.col("subtotal") > 0)
    rates = [
        tax / subtotal
        for tax, subtotal in zip(
            priced["tax_amount"].to_list(), priced["subtotal"].to_list(), strict=True
        )
    ]

    assert min(rates) >= config.min_tax_rate - 0.01
    assert max(rates) <= config.max_tax_rate + 0.01


def test_abandoned_checkouts_have_no_completion(checkouts: pl.DataFrame) -> None:
    """An abandoned attempt was never completed."""
    abandoned = checkouts.filter(pl.col("checkout_status") == str(CheckoutStatus.ABANDONED))

    assert abandoned.height > 0
    assert abandoned["completed_at"].null_count() == abandoned.height


def test_successful_and_failed_checkouts_are_completed(
    checkouts: pl.DataFrame,
) -> None:
    """Both outcomes record when the attempt finished."""
    finished = checkouts.filter(pl.col("checkout_status") != str(CheckoutStatus.ABANDONED))

    assert finished["completed_at"].null_count() == 0
    assert finished.filter(pl.col("completed_at") <= pl.col("started_at")).height == 0


def test_checkout_starts_after_the_cart_was_last_changed(
    checkouts: pl.DataFrame, carts: pl.DataFrame
) -> None:
    """A customer pays once they have stopped filling the cart."""
    joined = checkouts.join(
        carts.select("cart_id", pl.col("updated_at").alias("cart_updated")),
        on="cart_id",
    )

    assert joined.filter(pl.col("started_at") <= pl.col("cart_updated")).height == 0


def test_generated_data_passes_validation(
    checkout_data: CheckoutData, checkout_upstream: dict[str, pl.DataFrame]
) -> None:
    """The dataset satisfies the F005 acceptance criteria."""
    assert validate_checkout_data({**checkout_upstream, **checkout_data.datasets}) == []


def test_batching_does_not_change_the_output(
    carts: pl.DataFrame, cart_items: pl.DataFrame, addresses: pl.DataFrame
) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = generate_checkouts(CheckoutConfig(batch_size=7), carts, cart_items, addresses, SEED)
    large = generate_checkouts(
        CheckoutConfig(batch_size=1_000_000), carts, cart_items, addresses, SEED
    )

    assert small.equals(large)


def test_batches_are_bounded_by_the_configured_size(
    carts: pl.DataFrame, cart_items: pl.DataFrame, addresses: pl.DataFrame
) -> None:
    """No batch exceeds the configured size."""
    batches = list(
        iter_checkout_batches(CheckoutConfig(batch_size=50), carts, cart_items, addresses, SEED)
    )

    assert batches
    assert all(batch.height <= 50 for batch in batches)


def test_generation_is_deterministic(
    checkout_simulation_config: SimulationConfig,
    checkout_upstream: dict[str, pl.DataFrame],
) -> None:
    """The same configuration and seed reproduce identical data."""
    first = generate_checkout_data(checkout_simulation_config, checkout_upstream)
    second = generate_checkout_data(checkout_simulation_config, checkout_upstream)

    assert first.seed == second.seed
    assert first["checkout"].equals(second["checkout"])


def test_a_different_seed_changes_the_data(
    checkout_simulation_config: SimulationConfig,
    checkout_upstream: dict[str, pl.DataFrame],
) -> None:
    """Changing the seed changes generated attributes."""
    other = SimulationConfig(
        platform=PlatformConfig(seed=13_579),
        master_data=checkout_simulation_config.master_data,
        customers=checkout_simulation_config.customers,
        journey=checkout_simulation_config.journey,
        browsing=checkout_simulation_config.browsing,
        engagement=checkout_simulation_config.engagement,
        commerce=checkout_simulation_config.commerce,
        checkout=checkout_simulation_config.checkout,
    )

    baseline = generate_checkout_data(checkout_simulation_config, checkout_upstream)
    varied = generate_checkout_data(other, checkout_upstream)

    assert not baseline["checkout"].equals(varied["checkout"])


@pytest.mark.parametrize("missing", REQUIRED_CHECKOUT_DATASETS)
def test_missing_upstream_data_is_reported(
    checkout_simulation_config: SimulationConfig,
    checkout_upstream: dict[str, pl.DataFrame],
    missing: str,
) -> None:
    """Each required upstream dataset is checked before generation starts."""
    available = {name: frame for name, frame in checkout_upstream.items() if name != missing}

    with pytest.raises(KeyError, match="Missing upstream data"):
        generate_checkout_data(checkout_simulation_config, available)


def test_missing_upstream_names_the_prerequisite_commands(
    checkout_simulation_config: SimulationConfig,
    checkout_upstream: dict[str, pl.DataFrame],
) -> None:
    """The error tells the user which commands to run first."""
    available = {
        name: frame for name, frame in checkout_upstream.items() if name != "shopping_carts"
    }

    with pytest.raises(KeyError, match="generate commerce"):
        generate_checkout_data(checkout_simulation_config, available)


def test_empty_addresses_stops_generation(
    checkout_simulation_config: SimulationConfig,
    checkout_upstream: dict[str, pl.DataFrame],
) -> None:
    """Without an address there is nowhere to ship to."""
    available = dict(checkout_upstream)
    available["customer_addresses"] = available["customer_addresses"].clear()

    with pytest.raises(ValueError, match="customer addresses dataset is empty"):
        generate_checkout_data(checkout_simulation_config, available)


def test_no_eligible_carts_produces_an_empty_frame(
    config: CheckoutConfig,
    carts: pl.DataFrame,
    cart_items: pl.DataFrame,
    addresses: pl.DataFrame,
) -> None:
    """A run with nothing checked out yields an empty, schema-shaped frame."""
    none_eligible = carts.with_columns(pl.lit(str(CartStatus.ABANDONED)).alias("cart_status"))

    result = generate_checkouts(config, none_eligible, cart_items, addresses, SEED)

    assert result.height == 0
    assert "checkout_id" in result.columns


def test_bundle_reports_row_counts(checkout_data: CheckoutData) -> None:
    """The bundle exposes counts for the CLI report."""
    assert checkout_data.row_counts()["checkout"] == checkout_data.total_rows()


def test_unknown_dataset_access_raises(checkout_data: CheckoutData) -> None:
    """Requesting a dataset F005 does not produce fails clearly."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        checkout_data["orders"]


def test_checkout_does_not_regenerate_upstream_data(
    checkout_data: CheckoutData, checkout_upstream: dict[str, pl.DataFrame]
) -> None:
    """F005 consumes earlier output; it emits none of those datasets."""
    assert set(checkout_data.datasets).isdisjoint(set(checkout_upstream))
