"""Tests for the payment generator and payment status history."""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import pytest

from eds.config import (
    ConfigError,
    PaymentConfig,
    PlatformConfig,
    SimulationConfig,
    load_config,
    load_payment_config,
)
from eds.domain.commerce.enums import (
    PAYMENT_PROVIDER_BY_METHOD,
    PaymentMethod,
    PaymentStatus,
)
from eds.domain.commerce.schema import (
    CHECKOUT_DATASETS,
    COMMERCE_DATASETS,
    ORDER_DATASETS,
    PAYMENT_DATASETS,
    payment_dataset_by_name,
    payment_dataset_names,
)
from eds.generators.commerce.payment_generator import (
    PROVIDER_BY_METHOD,
    apply_payment_status,
    generate_payments,
    iter_payment_batches,
)
from eds.generators.commerce.payment_status_generator import (
    generate_payment_status_history,
)
from eds.generators.commerce.payments import (
    REQUIRED_PAYMENT_DATASETS,
    PaymentData,
    generate_payment_data,
)
from eds.validation.payment_validation import (
    PAYMENT_REFERENCE_PATTERN,
    validate_payment_data,
)

SEED = 4242

#: How many times the order fixture is repeated to measure outcome shares.
REPLICATION_FACTOR = 40

EXPECTED_OUTPUTS = {"payments", "payment_status_history"}


@pytest.fixture
def config() -> PaymentConfig:
    """Return a payment configuration with a small batch size."""
    return PaymentConfig(batch_size=25)


@pytest.fixture
def payments(payment_data: PaymentData) -> pl.DataFrame:
    """Return the generated payments frame."""
    return payment_data["payments"]


@pytest.fixture
def history(payment_data: PaymentData) -> pl.DataFrame:
    """Return the generated payment status history frame."""
    return payment_data["payment_status_history"]


@pytest.fixture
def orders(payment_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the orders frame."""
    return payment_upstream["orders"]


@pytest.fixture
def checkouts(payment_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the checkout frame."""
    return payment_upstream["checkout"]


@pytest.fixture
def many_orders(orders: pl.DataFrame) -> pl.DataFrame:
    """Return the orders repeated enough times to measure a distribution.

    The test fixture carries a few dozen orders, which is far too few to
    distinguish a 3 per cent outcome from a 5 per cent one. Repeating the same
    orders under fresh identifiers keeps every other property intact while
    giving the outcome shares a sample they can actually be read from.
    """
    copies = [
        orders.with_columns((pl.col("order_id") + index * orders.height).alias("order_id"))
        for index in range(REPLICATION_FACTOR)
    ]
    return pl.concat(copies, how="vertical")


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_shipped_payment_config_loads() -> None:
    """The committed payments.yaml matches the documented defaults."""
    config = load_payment_config()

    assert config.currency == "USD"
    assert config.capture_rate == pytest.approx(0.92)
    assert config.void_rate == pytest.approx(0.03)
    assert config.failure_rate == pytest.approx(0.05)
    assert config.payment_reference_prefix == "PAY"


def test_payment_config_is_part_of_the_run_configuration() -> None:
    """`load_config` includes the payments section."""
    assert load_config().payments.currency == "USD"


def test_currency_is_read_from_configuration_not_inferred() -> None:
    """A configured currency reaches the data unchanged."""
    assert PaymentConfig(currency="EUR").currency == "EUR"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capture_rate", 1.5),
        ("void_rate", -0.1),
        ("authorization_lead_seconds", 0),
        ("min_capture_minutes", 0),
        ("batch_size", 0),
    ],
)
def test_out_of_range_payment_values_are_rejected(field: str, value: float) -> None:
    """Settings outside their declared bounds fail validation."""
    with pytest.raises(ValueError, match=field):
        PaymentConfig(**{field: value})  # type: ignore[arg-type]


def test_outcome_shares_must_total_one() -> None:
    """The three outcomes partition every payment, so they sum to 1.0."""
    with pytest.raises(ValueError, match="must sum to 1.0"):
        PaymentConfig(capture_rate=0.5, void_rate=0.1, failure_rate=0.1)


@pytest.mark.parametrize(
    ("low_field", "high_field"),
    [
        ("min_capture_minutes", "max_capture_minutes"),
        ("min_void_minutes", "max_void_minutes"),
    ],
)
def test_inverted_wait_ranges_are_rejected(low_field: str, high_field: str) -> None:
    """A minimum above its maximum is a configuration error."""
    with pytest.raises(ValueError, match="cannot exceed"):
        PaymentConfig(**{low_field: 500, high_field: 10})  # type: ignore[arg-type]


def test_a_currency_must_be_a_three_letter_code() -> None:
    """ISO 4217 alphabetic codes are exactly three characters."""
    with pytest.raises(ValueError, match="currency"):
        PaymentConfig(currency="DOLLAR")


def test_unknown_payment_key_is_rejected() -> None:
    """A misspelled key is an error, not a silent no-op."""
    with pytest.raises(ValueError, match="captured_rate"):
        PaymentConfig(captured_rate=0.9)  # type: ignore[call-arg]


def test_invalid_payment_config_file_raises(tmp_path: Path) -> None:
    """An out-of-range value names the offending file."""
    (tmp_path / "payments.yaml").write_text("capture_rate: 5.0\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="payments.yaml"):
        load_payment_config(tmp_path)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_registry_lists_the_two_documented_outputs() -> None:
    """F007 declares exactly two output datasets."""
    assert len(PAYMENT_DATASETS) == 2
    assert set(payment_dataset_names()) == EXPECTED_OUTPUTS


def test_earlier_registries_are_unchanged() -> None:
    """Adding payments did not disturb the F004, F005 or F006 registries."""
    assert {dataset.name for dataset in COMMERCE_DATASETS} == {
        "shopping_carts",
        "cart_items",
    }
    assert {dataset.name for dataset in CHECKOUT_DATASETS} == {"checkout"}
    assert {dataset.name for dataset in ORDER_DATASETS} == {
        "orders",
        "order_lines",
        "order_status_history",
    }


def test_dataset_file_names_match_the_specification() -> None:
    """Each dataset maps to the documented Parquet file name."""
    assert payment_dataset_by_name("payments").file_name == "payments.parquet"
    assert (
        payment_dataset_by_name("payment_status_history").file_name
        == "payment_status_history.parquet"
    )


def test_unknown_payment_dataset_lookup_raises() -> None:
    """Looking up an unregistered dataset fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown payment dataset"):
        payment_dataset_by_name("refunds")


def test_every_payment_method_maps_to_exactly_one_provider() -> None:
    """The mapping is total, so the provider column is fully derived."""
    assert set(PAYMENT_PROVIDER_BY_METHOD) == set(PaymentMethod)
    assert set(PROVIDER_BY_METHOD) == {str(member) for member in PaymentMethod}


def test_only_the_four_documented_statuses_exist() -> None:
    """Refunds and chargebacks belong to later features."""
    assert {str(member) for member in PaymentStatus} == {
        "AUTHORIZED",
        "CAPTURED",
        "FAILED",
        "VOIDED",
    }


# --------------------------------------------------------------------------
# Payments
# --------------------------------------------------------------------------


def test_payments_originate_only_from_orders(payments: pl.DataFrame, orders: pl.DataFrame) -> None:
    """Every payment points at a real order, one each."""
    assert set(payments["order_id"].to_list()) <= set(orders["order_id"].to_list())
    assert payments["order_id"].n_unique() == payments.height


def test_every_payable_order_is_paid_for(payments: pl.DataFrame, orders: pl.DataFrame) -> None:
    """An order billed above zero always produces a payment."""
    payable = set(orders.filter(pl.col("total_amount") > 0.0)["order_id"].to_list())

    assert set(payments["order_id"].to_list()) == payable


def test_an_order_billed_at_zero_is_never_charged(
    config: PaymentConfig, orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """There is nothing to authorise, so no payment is created.

    An order whose every item was removed before checkout carries a zero
    total. The fixture may not contain one, so this zeroes an order to make
    the case explicit rather than skipping it.
    """
    zeroed = orders["order_id"][0]
    adjusted = orders.with_columns(
        pl.when(pl.col("order_id") == zeroed)
        .then(pl.lit(0.0))
        .otherwise(pl.col("total_amount"))
        .alias("total_amount")
    )

    generated = generate_payments(config, adjusted, checkouts, SEED)

    assert generated.height == orders.height - 1
    assert zeroed not in set(generated["order_id"].to_list())


def test_payment_ids_are_unique_and_sequential(payments: pl.DataFrame) -> None:
    """Payment ids form a dense sequence starting at one."""
    assert payments["payment_id"].to_list() == list(range(1, payments.height + 1))


def test_amount_is_copied_from_the_order(payments: pl.DataFrame, orders: pl.DataFrame) -> None:
    """ADR-007: money is copied verbatim, never recalculated."""
    joined = payments.join(orders, on="order_id", how="inner", suffix="_ord")

    assert joined.height == payments.height
    assert joined.filter(pl.col("payment_amount") != pl.col("total_amount")).height == 0


def test_every_amount_is_positive(payments: pl.DataFrame) -> None:
    """A payment for nothing is not a payment."""
    assert payments.filter(pl.col("payment_amount") <= 0.0).height == 0


def test_customer_comes_from_the_order(payments: pl.DataFrame, orders: pl.DataFrame) -> None:
    """The payer is whoever placed the order."""
    joined = payments.join(orders, on="order_id", how="inner", suffix="_ord")

    assert joined.filter(pl.col("customer_id") != pl.col("customer_id_ord")).height == 0


def test_method_is_copied_from_the_checkout(
    payments: pl.DataFrame, orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """The customer chose the method at checkout; the payment reuses it."""
    joined = payments.join(orders.select("order_id", "checkout_id"), on="order_id").join(
        checkouts.select("checkout_id", pl.col("payment_method").alias("chosen")),
        on="checkout_id",
    )

    assert joined.height == payments.height
    assert joined.filter(pl.col("payment_method") != pl.col("chosen")).height == 0


def test_provider_is_derived_from_the_method(payments: pl.DataFrame) -> None:
    """ADR-009: the processor follows from the method rather than a draw."""
    for row in payments.select("payment_method", "payment_provider").unique().to_dicts():
        assert PROVIDER_BY_METHOD[row["payment_method"]] == row["payment_provider"]


def test_currency_is_the_configured_one(payments: pl.DataFrame) -> None:
    """F007 is single-currency, and the value comes from configuration."""
    assert payments["currency"].unique().to_list() == ["USD"]


def test_a_configured_currency_reaches_the_data(
    orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """Changing the setting changes every row."""
    generated = generate_payments(PaymentConfig(currency="INR"), orders, checkouts, SEED)

    assert generated["currency"].unique().to_list() == ["INR"]


# --------------------------------------------------------------------------
# Payment references
# --------------------------------------------------------------------------


def test_payment_references_are_unique(payments: pl.DataFrame) -> None:
    """The business identifier is never reused."""
    assert payments["payment_reference"].n_unique() == payments.height


def test_payment_references_match_the_documented_format(payments: pl.DataFrame) -> None:
    """Every reference reads as PREFIX-YYYYMMDD-NNNNNN."""
    pattern = re.compile(PAYMENT_REFERENCE_PATTERN)

    for reference in payments["payment_reference"].to_list():
        assert pattern.match(reference), reference


def test_payment_reference_embeds_its_own_date(payments: pl.DataFrame) -> None:
    """The date inside the reference is the day the payment was created."""
    mismatched = payments.filter(
        pl.col("payment_reference").str.slice(-15, 8) != pl.col("created_at").dt.strftime("%Y%m%d")
    )

    assert mismatched.height == 0


def test_payment_references_are_sequential_within_a_date(payments: pl.DataFrame) -> None:
    """The sequence restarts each day and runs 1..n without gaps."""
    numbered = (
        payments.with_columns(pl.col("created_at").dt.date().alias("day"))
        .group_by("day")
        .agg(
            pl.col("payment_reference").str.slice(-6).cast(pl.Int64).min().alias("lowest"),
            pl.col("payment_reference").str.slice(-6).cast(pl.Int64).max().alias("highest"),
            pl.len().alias("total"),
        )
    )

    assert numbered.filter(pl.col("lowest") != 1).height == 0
    assert numbered.filter(pl.col("highest") != pl.col("total")).height == 0


def test_the_reference_prefix_is_configurable(
    orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """A different prefix changes every reference."""
    custom = generate_payments(
        PaymentConfig(payment_reference_prefix="TXN"), orders, checkouts, SEED
    )

    assert all(reference.startswith("TXN-") for reference in custom["payment_reference"].to_list())


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


def test_payments_are_created_after_their_order(
    payments: pl.DataFrame, orders: pl.DataFrame
) -> None:
    """Money moves after the order document exists."""
    joined = payments.join(
        orders.select("order_id", pl.col("created_at").alias("ordered_at")), on="order_id"
    )

    assert joined.filter(pl.col("created_at") <= pl.col("ordered_at")).height == 0


def test_authorisation_is_recorded_exactly_when_the_payment_did_not_fail(
    payments: pl.DataFrame,
) -> None:
    """A failed payment never reached authorisation."""
    failed = payments.filter(pl.col("payment_status") == str(PaymentStatus.FAILED))
    rest = payments.filter(pl.col("payment_status") != str(PaymentStatus.FAILED))

    assert failed["authorized_at"].null_count() == failed.height
    assert rest["authorized_at"].null_count() == 0


def test_capture_is_recorded_only_for_captured_payments(payments: pl.DataFrame) -> None:
    """Only a captured payment ever took the money."""
    captured = payments.filter(pl.col("payment_status") == str(PaymentStatus.CAPTURED))
    rest = payments.filter(pl.col("payment_status") != str(PaymentStatus.CAPTURED))

    assert captured["captured_at"].null_count() == 0
    assert rest["captured_at"].null_count() == rest.height


def test_capture_follows_authorisation(payments: pl.DataFrame) -> None:
    """The money is taken after it is held, never before."""
    captured = payments.filter(pl.col("captured_at").is_not_null())

    assert captured.filter(pl.col("captured_at") < pl.col("authorized_at")).height == 0


def test_authorisation_is_no_earlier_than_the_attempt(payments: pl.DataFrame) -> None:
    """The record predates or coincides with the authorisation it carries."""
    assert payments.filter(pl.col("authorized_at") < pl.col("created_at")).height == 0


def test_capture_waits_stay_inside_the_configured_window(
    orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """Every capture falls in the configured minute range."""
    settings = PaymentConfig(min_capture_minutes=30, max_capture_minutes=45)
    generated = generate_payments(settings, orders, checkouts, SEED).filter(
        pl.col("captured_at").is_not_null()
    )

    waits = (
        generated.select(
            ((pl.col("captured_at") - pl.col("authorized_at")).dt.total_minutes()).alias("minutes")
        )["minutes"]
        .unique()
        .to_list()
    )

    assert waits
    assert min(waits) >= 30
    assert max(waits) <= 45


# --------------------------------------------------------------------------
# Status history
# --------------------------------------------------------------------------


def test_history_ids_are_unique_and_sequential(history: pl.DataFrame) -> None:
    """History ids form a dense sequence starting at one."""
    assert history["history_id"].to_list() == list(range(1, history.height + 1))


def test_every_payment_has_a_history(payments: pl.DataFrame, history: pl.DataFrame) -> None:
    """No payment is left without a record of how it ended."""
    assert set(history["payment_id"].to_list()) == set(payments["payment_id"].to_list())


def test_a_failed_payment_has_a_single_row(payments: pl.DataFrame, history: pl.DataFrame) -> None:
    """It never got past the attempt, so there is nothing else to record."""
    failed = set(
        payments.filter(pl.col("payment_status") == str(PaymentStatus.FAILED))[
            "payment_id"
        ].to_list()
    )
    assert failed, "the sample should contain failed payments"

    rows = history.filter(pl.col("payment_id").is_in(list(failed)))

    assert rows.height == len(failed)
    assert set(rows["status"].to_list()) == {str(PaymentStatus.FAILED)}


def test_a_captured_or_voided_payment_was_authorised_first(
    payments: pl.DataFrame, history: pl.DataFrame
) -> None:
    """Both outcomes are two-row histories opening at AUTHORIZED."""
    settled = set(
        payments.filter(pl.col("payment_status") != str(PaymentStatus.FAILED))[
            "payment_id"
        ].to_list()
    )
    rows = history.filter(pl.col("payment_id").is_in(list(settled)))

    assert rows.height == len(settled) * 2
    assert (
        rows.filter(
            (pl.col("sequence") == 1) & (pl.col("status") != str(PaymentStatus.AUTHORIZED))
        ).height
        == 0
    )


def test_sequences_start_at_one_and_are_contiguous(history: pl.DataFrame) -> None:
    """Numbering restarts per payment without gaps."""
    grouped = history.group_by("payment_id").agg(
        pl.col("sequence").min().alias("lowest"),
        pl.col("sequence").max().alias("highest"),
        pl.len().alias("total"),
    )

    assert grouped.filter(pl.col("lowest") != 1).height == 0
    assert grouped.filter(pl.col("highest") != pl.col("total")).height == 0


def test_history_is_chronological(history: pl.DataFrame) -> None:
    """Time moves forwards with the sequence."""
    ordered = history.sort("payment_id", "sequence").with_columns(
        pl.col("status_timestamp").shift(1).over("payment_id").alias("previous")
    )

    assert (
        ordered.filter(
            pl.col("previous").is_not_null() & (pl.col("status_timestamp") <= pl.col("previous"))
        ).height
        == 0
    )


def test_history_starts_no_earlier_than_the_payment(
    payments: pl.DataFrame, history: pl.DataFrame
) -> None:
    """The opening status is recorded when the payment is attempted."""
    first = history.filter(pl.col("sequence") == 1).select(
        "payment_id", pl.col("status_timestamp").alias("at")
    )
    joined = payments.join(first, on="payment_id", how="inner")

    assert joined.filter(pl.col("at") < pl.col("created_at")).height == 0


def test_capture_rows_carry_the_payment_capture_time(
    payments: pl.DataFrame, history: pl.DataFrame
) -> None:
    """The history and the payment agree on when the money moved."""
    rows = history.filter(pl.col("status") == str(PaymentStatus.CAPTURED)).join(
        payments.select("payment_id", "captured_at"), on="payment_id", how="inner"
    )

    assert rows.height > 0
    assert rows.filter(pl.col("status_timestamp") != pl.col("captured_at")).height == 0


def test_payment_status_equals_the_latest_history_row(
    payments: pl.DataFrame, history: pl.DataFrame
) -> None:
    """ADR-012: the history is the source of truth."""
    latest = (
        history.sort("payment_id", "sequence")
        .group_by("payment_id", maintain_order=True)
        .agg(pl.col("status").last().alias("latest"))
    )
    joined = payments.join(latest, on="payment_id", how="inner")

    assert joined.height == payments.height
    assert joined.filter(pl.col("payment_status") != pl.col("latest")).height == 0


def test_authorized_is_never_a_final_status(payments: pl.DataFrame) -> None:
    """Every payment settles: F007 leaves nothing in flight."""
    assert str(PaymentStatus.AUTHORIZED) not in set(payments["payment_status"].to_list())


def test_outcome_distribution_is_approximately_as_specified(
    many_orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """Roughly 92 / 3 / 5 per cent capture, void and fail."""
    generated = generate_payments(PaymentConfig(), many_orders, checkouts, SEED)
    total = generated.height
    share = {
        row["payment_status"]: row["count"] / total
        for row in generated["payment_status"].value_counts().to_dicts()
    }

    assert total >= 500, "the replicated sample should be large enough to read"
    assert share[str(PaymentStatus.CAPTURED)] == pytest.approx(0.92, abs=0.03)
    assert share.get(str(PaymentStatus.VOIDED), 0.0) == pytest.approx(0.03, abs=0.02)
    assert share.get(str(PaymentStatus.FAILED), 0.0) == pytest.approx(0.05, abs=0.02)


def test_every_payment_can_be_captured(orders: pl.DataFrame, checkouts: pl.DataFrame) -> None:
    """With a capture rate of one, nothing voids and nothing fails."""
    settings = PaymentConfig(capture_rate=1.0, void_rate=0.0, failure_rate=0.0)

    generated = generate_payments(settings, orders, checkouts, SEED)
    history = generate_payment_status_history(settings, generated, SEED)
    settled = apply_payment_status(generated, history)

    assert history.height == generated.height * 2
    assert set(settled["payment_status"].to_list()) == {str(PaymentStatus.CAPTURED)}


def test_every_payment_can_fail(orders: pl.DataFrame, checkouts: pl.DataFrame) -> None:
    """With a failure rate of one, each history is a single FAILED row."""
    settings = PaymentConfig(capture_rate=0.0, void_rate=0.0, failure_rate=1.0)

    generated = generate_payments(settings, orders, checkouts, SEED)
    history = generate_payment_status_history(settings, generated, SEED)
    settled = apply_payment_status(generated, history)

    assert history.height == generated.height
    assert set(history["status"].to_list()) == {str(PaymentStatus.FAILED)}
    assert set(settled["payment_status"].to_list()) == {str(PaymentStatus.FAILED)}
    assert settled["authorized_at"].null_count() == settled.height


def test_every_payment_can_be_voided(orders: pl.DataFrame, checkouts: pl.DataFrame) -> None:
    """With a void rate of one, each payment is authorised then released."""
    settings = PaymentConfig(capture_rate=0.0, void_rate=1.0, failure_rate=0.0)

    generated = generate_payments(settings, orders, checkouts, SEED)
    history = generate_payment_status_history(settings, generated, SEED)
    settled = apply_payment_status(generated, history)

    assert history.height == generated.height * 2
    assert set(settled["payment_status"].to_list()) == {str(PaymentStatus.VOIDED)}
    assert settled["captured_at"].null_count() == settled.height


# --------------------------------------------------------------------------
# Orchestration, batching and determinism
# --------------------------------------------------------------------------


def test_all_documented_datasets_are_generated(payment_data: PaymentData) -> None:
    """Every dataset named in the F007 output list is produced."""
    assert set(payment_data.datasets) == EXPECTED_OUTPUTS


def test_datasets_are_emitted_in_dependency_order(payment_data: PaymentData) -> None:
    """Payments come first, so the history can reference them."""
    assert list(payment_data.datasets) == [dataset.name for dataset in PAYMENT_DATASETS]


def test_no_dataset_is_empty(payment_data: PaymentData) -> None:
    """Both payment datasets carry rows."""
    assert all(count > 0 for count in payment_data.row_counts().values())


def test_generated_data_passes_validation(
    payment_data: PaymentData, payment_upstream: dict[str, pl.DataFrame]
) -> None:
    """The bundle satisfies the F007 acceptance criteria."""
    assert validate_payment_data({**payment_upstream, **payment_data.datasets}) == []


def test_batching_does_not_change_the_output(orders: pl.DataFrame, checkouts: pl.DataFrame) -> None:
    """Batch size is an implementation detail, not a data change."""
    small = PaymentConfig(batch_size=7)
    large = PaymentConfig(batch_size=1_000_000)

    small_payments = generate_payments(small, orders, checkouts, SEED)
    large_payments = generate_payments(large, orders, checkouts, SEED)

    assert small_payments.equals(large_payments)
    assert generate_payment_status_history(small, small_payments, SEED).equals(
        generate_payment_status_history(large, large_payments, SEED)
    )


def test_batches_are_bounded_by_the_configured_size(
    orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """No batch exceeds the configured size."""
    batches = list(iter_payment_batches(PaymentConfig(batch_size=40), orders, checkouts, SEED))

    assert batches
    assert all(batch.height <= 40 for batch in batches)


def test_generation_is_deterministic(
    payment_simulation_config: SimulationConfig, payment_upstream: dict[str, pl.DataFrame]
) -> None:
    """The same configuration and seed reproduce identical datasets."""
    first = generate_payment_data(payment_simulation_config, payment_upstream)
    second = generate_payment_data(payment_simulation_config, payment_upstream)

    assert first.seed == second.seed
    for name, frame in first:
        assert frame.equals(second[name]), f"{name} differs between runs"


def test_a_different_seed_changes_the_outcomes(
    payment_simulation_config: SimulationConfig, payment_upstream: dict[str, pl.DataFrame]
) -> None:
    """The seed drives which payments capture, void or fail."""
    other = SimulationConfig(
        platform=PlatformConfig(seed=97_531),
        master_data=payment_simulation_config.master_data,
        customers=payment_simulation_config.customers,
        journey=payment_simulation_config.journey,
        browsing=payment_simulation_config.browsing,
        engagement=payment_simulation_config.engagement,
        commerce=payment_simulation_config.commerce,
        checkout=payment_simulation_config.checkout,
        orders=payment_simulation_config.orders,
        payments=payment_simulation_config.payments,
    )

    baseline = generate_payment_data(payment_simulation_config, payment_upstream)
    varied = generate_payment_data(other, payment_upstream)

    assert not baseline["payment_status_history"].equals(varied["payment_status_history"])


def test_the_reference_does_not_depend_on_the_seed(
    orders: pl.DataFrame, checkouts: pl.DataFrame, config: PaymentConfig
) -> None:
    """References are fully derived from the order sequence."""
    first = generate_payments(config, orders, checkouts, SEED)
    second = generate_payments(config, orders, checkouts, 999)

    assert first["payment_reference"].to_list() == second["payment_reference"].to_list()
    assert first["payment_amount"].to_list() == second["payment_amount"].to_list()


@pytest.mark.parametrize("missing", REQUIRED_PAYMENT_DATASETS)
def test_missing_upstream_data_is_reported(
    payment_simulation_config: SimulationConfig,
    payment_upstream: dict[str, pl.DataFrame],
    missing: str,
) -> None:
    """Each required upstream dataset is checked before generation starts."""
    available = {name: frame for name, frame in payment_upstream.items() if name != missing}

    with pytest.raises(KeyError, match="Missing upstream data"):
        generate_payment_data(payment_simulation_config, available)


def test_missing_upstream_names_the_prerequisite_commands(
    payment_simulation_config: SimulationConfig,
    payment_upstream: dict[str, pl.DataFrame],
) -> None:
    """The error tells the user which commands to run first."""
    available = {name: frame for name, frame in payment_upstream.items() if name != "orders"}

    with pytest.raises(KeyError, match="generate commerce"):
        generate_payment_data(payment_simulation_config, available)


def test_no_orders_produces_empty_frames(
    config: PaymentConfig, orders: pl.DataFrame, checkouts: pl.DataFrame
) -> None:
    """A run with nothing to charge yields empty, schema-shaped frames."""
    generated = generate_payments(config, orders.clear(), checkouts, SEED)
    history = generate_payment_status_history(config, generated, SEED)

    assert generated.height == 0
    assert history.height == 0
    assert "payment_id" in generated.columns
    assert "history_id" in history.columns


def test_bundle_reports_row_counts(payment_data: PaymentData) -> None:
    """The bundle exposes counts for the CLI report."""
    assert payment_data.total_rows() == sum(payment_data.row_counts().values())


def test_unknown_dataset_access_raises(payment_data: PaymentData) -> None:
    """Requesting a dataset F007 does not produce fails clearly."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        payment_data["refunds"]


def test_payments_do_not_regenerate_upstream_data(
    payment_data: PaymentData, payment_upstream: dict[str, pl.DataFrame]
) -> None:
    """F007 consumes earlier output; it emits none of those datasets."""
    assert set(payment_data.datasets).isdisjoint(set(payment_upstream))
