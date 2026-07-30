"""Tests for Retail over simulated time.

Three kinds of test live here. The first checks the machinery on its own -
what each dataset does when a day passes, how identifiers continue, how a day
joins history. The second runs whole simulations of one, five, thirty and
three hundred and sixty-five days and asks whether what came out is a
business. The third is the awkward one: whether a year of trading produced the
same year however the run was divided up, interrupted or resumed.

The scale is deliberately tiny. What is being tested is whether an enterprise
*evolves coherently*, and that is not a function of how many customers it has.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from eds.core.validation.issues import ValidationIssue
from eds.domains.retail.config import SimulationConfig, load_config
from eds.domains.retail.registry import RetailDomain
from eds.domains.retail.temporal.context import BusinessContext
from eds.domains.retail.temporal.datasets import RETAIL_DATASETS, retail_dataset
from eds.domains.retail.temporal.day import (
    HISTORY_READ,
    RETAIL_STAGE_NAMES,
    STAGE_DATASETS,
    advance_day,
)
from eds.domains.retail.temporal.identity import (
    DAILY_SEQUENCES,
    continue_daily_sequences,
    disambiguate,
    identity_offsets,
    last_identifier,
    renumber,
    restate_key_codes,
)
from eds.domains.retail.temporal.merge import merge_dataset, merge_history
from eds.domains.retail.temporal.rules import validate_temporal_history
from eds.domains.retail.temporal.temporality import (
    DATASET_TEMPORALITY,
    Temporality,
    temporality_of,
)
from eds.platform.project.project import Project, create_project
from eds.platform.run.configuration import RunConfiguration
from eds.platform.run.mode import RunMode
from eds.platform.run.run import create_run
from eds.platform.run.stop import AfterStage, AfterTicks
from eds.platform.scheduler.report import ExecutionReport
from eds.platform.scheduler.scheduler import execute
from eds.platform.time.clock import create_clock
from eds.runners.retail import RetailExecutor

DAY = date(2026, 1, 1)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _configured(**evolution: object) -> SimulationConfig:
    """Return a tiny enterprise with the given evolution settings.

    Args:
        **evolution: Overrides for the evolution configuration.

    Returns:
        The settings.
    """
    config = load_config()
    return config.model_copy(
        update={
            "master_data": config.master_data.model_copy(
                update={
                    "product_count": 40,
                    "brand_count": 4,
                    "supplier_count": 3,
                    "warehouse_count": 2,
                    "warehouses_per_product": 2,
                    "root_categories": 3,
                    "children_per_category": 2,
                }
            ),
            "customers": config.customers.model_copy(update={"customer_count": 25}),
            "evolution": config.evolution.model_copy(update=evolution),
        }
    )


@pytest.fixture(scope="module")
def busy() -> SimulationConfig:
    """Return settings under which something happens every day."""
    return _configured(active_customer_rate=0.6, new_customers_per_day=3, max_daily_sessions=2)


@pytest.fixture(scope="module")
def quiet() -> SimulationConfig:
    """Return settings under which a year of trading stays small."""
    return _configured(active_customer_rate=0.05, new_customers_per_day=1, max_daily_sessions=1)


def _simulate(
    root: Path,
    config: SimulationConfig,
    days: int,
    start: date = DAY,
    project: Project | None = None,
    seed: int = 42,
) -> tuple[Project, ExecutionReport]:
    """Run a simulation for a number of consecutive days.

    Args:
        root: Where the project lives.
        config: Retail settings.
        days: How many days to run.
        start: The first business date.
        project: An existing project to carry on, or ``None`` to create one.
        seed: The enterprise seed, when creating a project.

    Returns:
        The project and what the run reported.
    """
    shop = project or create_project(root, name="Shop", domain="retail", seed=seed)
    if project is not None:
        _release(shop)
    clock = create_clock(start, end=start + timedelta(days=days - 1))
    report = execute(
        create_run(shop, clock, RunConfiguration(stop_condition=AfterTicks(days))),
        RetailExecutor(config=config),
    )
    return shop, report


def _release(shop: Project) -> None:
    """Clear the clock position a project recorded, so a new run may start.

    **This is a platform limitation showing through, and it is deliberate that
    it shows.** ``SimulationRun`` refuses any run whose clock does not stand
    exactly where the project last stopped, and the scheduler leaves the clock
    on the final tick rather than past it - so there is no date a second run
    can legally start on. Re-running the last date would trade that day twice;
    starting on the next one is refused.

    Retail has no such difficulty. Its history is on disk, a day is seeded by
    its date, and a stage continues from what it finds - so carrying an
    enterprise forward is a matter of pointing a new run at a later date. What
    is cleared here is the platform's *bookkeeping*, never the data.

    Args:
        shop: The project to carry forward.
    """
    shop.write_state(replace(shop.read_state(), current_date=None, completed_stages=()))


def _read(shop: Project, name: str) -> pl.DataFrame:
    """Return one of a project's datasets.

    Args:
        shop: The project.
        name: Dataset name.

    Returns:
        The frame.
    """
    return pl.read_parquet(shop.workspace.data_directory / f"{name}.parquet")


def _digests(directory: Path) -> dict[str, str]:
    """Return a hash of every dataset file in a directory.

    Args:
        directory: Where the datasets are.

    Returns:
        File name to SHA-256.
    """
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.glob("*.parquet"))
    }


@pytest.fixture(scope="module")
def year(tmp_path_factory: pytest.TempPathFactory, busy: SimulationConfig) -> Project:
    """Return a project that has traded for twelve consecutive days."""
    shop, report = _simulate(tmp_path_factory.mktemp("busy"), busy, days=12)
    assert report.succeeded, report.result.failure
    return shop


# --------------------------------------------------------------------------
# What each dataset does when a day passes
# --------------------------------------------------------------------------


def test_every_dataset_declares_how_it_behaves_in_time() -> None:
    """A dataset with no declared temporality has no defined second day."""
    assert set(DATASET_TEMPORALITY) == set(RetailDomain().dataset_names)


def test_the_classification_covers_the_schema_registry() -> None:
    """The gathered declarations are the ones the domain produces."""
    assert {dataset.name for dataset in RETAIL_DATASETS} == set(DATASET_TEMPORALITY)


def test_an_unclassified_dataset_is_refused_rather_than_guessed() -> None:
    """Silently appending to something that should be replaced corrupts it."""
    with pytest.raises(KeyError, match="has not declared how it behaves over time"):
        temporality_of("weather")


def test_an_unknown_dataset_has_no_declaration() -> None:
    """The lookup names the domain rather than raising a bare KeyError."""
    with pytest.raises(KeyError, match="produces no dataset named"):
        retail_dataset("weather")


def test_commerce_is_history_and_never_a_snapshot() -> None:
    """A parcel that arrived does not unarrive."""
    for name in STAGE_DATASETS["commerce"]:
        assert temporality_of(name) is Temporality.APPEND_ONLY


def test_only_stock_and_loyalty_are_rewritten() -> None:
    """The two datasets that are a picture of now rather than a record."""
    rewritten = {
        name
        for name, kind in DATASET_TEMPORALITY.items()
        if kind in {Temporality.MUTABLE_SNAPSHOT, Temporality.SLOWLY_CHANGING}
    }
    assert rewritten == {"inventory", "customer_loyalty"}


# --------------------------------------------------------------------------
# Joining a day to history
# --------------------------------------------------------------------------


def _frame(**columns: list[object]) -> pl.DataFrame:
    """Build a small frame.

    Args:
        **columns: Column name to values.

    Returns:
        The frame.
    """
    return pl.DataFrame(columns)


def test_a_founding_day_merges_nothing() -> None:
    """With no history there is nothing to join to, so nothing is done."""
    produced = _frame(session_id=[1, 2], customer_id=[7, 8])
    assert merge_dataset("sessions", None, produced) is produced
    assert merge_dataset("sessions", produced.clear(), produced) is produced


def test_append_only_keeps_history_first_and_unchanged() -> None:
    """The existing prefix of the file is what it was, row for row."""
    history = _frame(session_id=[1, 2], customer_id=[7, 8])
    today = _frame(session_id=[3], customer_id=[9])

    merged = merge_dataset("sessions", history, today)

    assert merged.head(2).equals(history)
    assert merged["session_id"].to_list() == [1, 2, 3]


def test_static_discards_the_day_and_keeps_history() -> None:
    """A day of trading does not reopen a country."""
    history = _frame(country_id=[1], country_code=["GB"])
    today = _frame(country_id=[1], country_code=["XX"])

    assert merge_dataset("countries", history, today).equals(history)


def test_a_mutable_snapshot_takes_the_day_whole() -> None:
    """Yesterday's stock level is not history, it is a stale number."""
    history = _frame(inventory_id=[1], quantity_on_hand=[10])
    today = _frame(inventory_id=[1], quantity_on_hand=[4])

    assert merge_dataset("inventory", history, today).equals(today)


def test_slowly_changing_updates_in_place_and_appends() -> None:
    """One row per subject, kept, with the few attributes that move moved."""
    history = _frame(loyalty_id=[1, 2], points_balance=[10, 20])
    today = _frame(loyalty_id=[2, 3], points_balance=[99, 0])

    merged = merge_dataset("customer_loyalty", history, today)

    assert merged["loyalty_id"].to_list() == [1, 2, 3]
    assert merged["points_balance"].to_list() == [10, 99, 0]


def test_merging_a_day_touches_only_what_the_day_produced() -> None:
    """A dataset the day did not change is not in the result to be rewritten."""
    history = {"sessions": _frame(session_id=[1]), "countries": _frame(country_id=[1])}
    merged = merge_history(history, {"sessions": _frame(session_id=[2])})

    assert set(merged) == {"sessions"}


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def test_an_absent_history_has_issued_no_identifiers() -> None:
    """Which makes the first identifier issued one, as a founding run does."""
    assert last_identifier(None, "customer_id") == 0
    assert last_identifier(_frame(customer_id=[]), "customer_id") == 0
    assert last_identifier(_frame(customer_id=[4, 9, 2]), "customer_id") == 9


def test_renumbering_shifts_the_key_and_the_keys_that_point_at_it() -> None:
    """Two customers numbered one is not a numbering problem, it is two people."""
    produced = {
        "customers": _frame(customer_id=[1, 2]),
        "customer_addresses": _frame(address_id=[1, 2], customer_id=[1, 2], city_id=[5, 5]),
    }
    history = {"customers": _frame(customer_id=[40]), "customer_addresses": _frame(address_id=[70])}

    shifted = renumber(produced, identity_offsets(history, produced))

    assert shifted["customers"]["customer_id"].to_list() == [41, 42]
    assert shifted["customer_addresses"]["address_id"].to_list() == [71, 72]
    assert shifted["customer_addresses"]["customer_id"].to_list() == [41, 42]
    # The city was not generated today, so its identifier is already right.
    assert shifted["customer_addresses"]["city_id"].to_list() == [5, 5]


def test_renumbering_leaves_an_absent_reference_absent() -> None:
    """A cart item added from no wishlist still came from no wishlist."""
    produced = {
        "wishlists": _frame(wishlist_id=[1], customer_id=[1], product_view_id=[1], product_id=[1]),
        "cart_items": _frame(
            cart_item_id=[1],
            cart_id=[1],
            customer_id=[1],
            product_id=[1],
            product_view_id=[1],
            wishlist_id=[None],
        ),
    }
    shifted = renumber(produced, identity_offsets({"wishlists": _frame(wishlist_id=[3])}, produced))

    assert shifted["cart_items"]["wishlist_id"].to_list() == [None]


def test_a_code_that_renders_an_identifier_is_rebuilt() -> None:
    """``CUST-00000042`` is a rendering of customer 42, not a label."""
    produced = {"customers": _frame(customer_id=[42], customer_number=["CUST-00000001"])}

    assert restate_key_codes(produced)["customers"]["customer_number"].to_list() == [
        "CUST-00000042"
    ]


def test_a_daily_sequence_continues_the_day_it_lands_on() -> None:
    """History keeps its numbers; a later day's rows take the next ones."""
    history = {
        "orders": _frame(
            order_id=[1, 2],
            order_date=[DAY, DAY],
            order_number=["ORD-20260101-000001", "ORD-20260101-000002"],
        )
    }
    produced = {
        "orders": _frame(
            order_id=[3, 4],
            order_date=[DAY, DAY + timedelta(days=1)],
            order_number=["ORD-20260101-000001", "ORD-20260102-000001"],
        )
    }

    continued = continue_daily_sequences(produced, history, {"orders": "ORD"})

    assert continued["orders"]["order_number"].to_list() == [
        "ORD-20260101-000003",
        "ORD-20260102-000001",
    ]


def test_every_daily_sequence_names_a_column_its_dataset_has() -> None:
    """The generators build the day from a timestamp and drop it again."""
    for sequence in DAILY_SEQUENCES:
        columns = retail_dataset(sequence.dataset).columns
        assert sequence.column in columns
        assert sequence.moment_column in columns


def test_only_colliding_values_are_rewritten() -> None:
    """The generator's own fallback rule, applied with a wider memory."""
    cohort = _frame(customer_id=[41, 42], email=["a@x.com", "b@x.com"])

    resolved = disambiguate(
        cohort, "email", ["a@x.com"], lambda value, key: f"{value}.{key}", "customer_id"
    )

    assert resolved["email"].to_list() == ["a@x.com.41", "b@x.com"]


# --------------------------------------------------------------------------
# The business context
# --------------------------------------------------------------------------


def test_a_day_is_seeded_by_its_date_and_not_by_its_position() -> None:
    """Which is what lets a run be divided up and still agree with itself."""
    one = BusinessContext(DAY, seed=42)
    same = BusinessContext(DAY, seed=42)
    later = BusinessContext(DAY + timedelta(days=1), seed=42)

    assert one.stream("customers") == same.stream("customers")
    assert one.stream("customers") != later.stream("customers")
    assert one.stream("customers") != one.stream("sessions")


def test_an_enterprise_that_could_not_reproduce_itself_is_refused() -> None:
    """A seed is the whole of what makes a simulation repeatable."""
    with pytest.raises(ValueError, match="must not be negative"):
        BusinessContext(DAY, seed=-1)


def test_retail_knows_nothing_about_the_platform_that_runs_it() -> None:
    """The context is a date and a seed. There is nothing else to know."""
    assert set(BusinessContext.__dataclass_fields__) == {"business_date", "seed"}


# --------------------------------------------------------------------------
# The rules that only exist because time passes
# --------------------------------------------------------------------------


def _rules(datasets: Mapping[str, pl.DataFrame]) -> set[str]:
    """Return the rules a history breaks.

    Args:
        datasets: The enterprise.

    Returns:
        The rule identifiers reported.
    """
    return {issue.rule for issue in validate_temporal_history(datasets)}


def test_a_payment_cannot_settle_an_order_that_was_never_placed() -> None:
    """It takes two days to break this; one day's output cannot."""
    history = {
        "orders": _frame(order_id=[1], order_date=[DAY]),
        "payments": _frame(
            payment_id=[1], order_id=[1], created_at=[DAY - timedelta(days=1)], customer_id=[1]
        ),
    }
    assert "payment_precedes_order" in _rules(history)


def test_a_review_cannot_precede_the_parcel_arriving() -> None:
    """Nobody reviews what they have not received."""
    history = {
        "shipments": _frame(shipment_id=[1], delivered_at=[DAY]),
        "reviews": _frame(review_id=[1], shipment_id=[1], created_at=[DAY - timedelta(days=2)]),
    }
    assert "review_precedes_delivery" in _rules(history)


def test_an_undelivered_parcel_has_no_delivery_to_be_later_than() -> None:
    """A null parent moment is not a violation, it is an absence."""
    history = {
        "shipments": _frame(shipment_id=[1], delivered_at=[None]),
        "reviews": _frame(review_id=[1], shipment_id=[1], created_at=[DAY]),
    }
    assert _rules(history) == set()


def test_an_identifier_issued_twice_is_reported() -> None:
    """The property renumbering exists to preserve."""
    history = {"customers": _frame(customer_id=[1, 1], customer_number=["a", "b"])}
    assert "duplicate_identifier" in _rules(history)


def test_a_business_key_issued_twice_is_reported() -> None:
    """So is the one that fails loudest when renumbering goes wrong."""
    history = {"customers": _frame(customer_id=[1, 2], customer_number=["a", "a"])}
    assert "duplicate_business_key" in _rules(history)


def test_a_history_that_could_have_happened_reports_nothing() -> None:
    """The rules are checks, not a tax."""
    history = {
        "customers": _frame(customer_id=[1], registration_date=[DAY]),
        "orders": _frame(order_id=[1], customer_id=[1], order_date=[DAY + timedelta(days=3)]),
    }
    assert _rules(history) == set()


def test_an_empty_history_is_coherent() -> None:
    """A history that has not reached commerce is incomplete, not wrong."""
    assert validate_temporal_history({}) == []
    assert isinstance(validate_temporal_history({}), list)


def test_an_issue_names_the_dataset_and_the_rule() -> None:
    """A diagnostic that cannot be traced back is not one."""
    history = {"customers": _frame(customer_id=[1, 1])}
    issue = validate_temporal_history(history)[0]

    assert isinstance(issue, ValidationIssue)
    assert issue.dataset == "customers"


# --------------------------------------------------------------------------
# What a day is
# --------------------------------------------------------------------------


def test_the_stages_are_the_ones_the_domain_declares() -> None:
    """Derived from the same schema declarations, and pinned against them."""
    for stage in RetailDomain().stages:
        assert STAGE_DATASETS[stage.name] == stage.produces
    assert tuple(stage.name for stage in RetailDomain().stages) == RETAIL_STAGE_NAMES


def test_every_stage_reads_its_own_history() -> None:
    """Continuing a history means knowing what the history is."""
    for stage, produced in STAGE_DATASETS.items():
        assert set(produced) <= set(HISTORY_READ[stage])


def test_the_two_stages_that_read_further_read_what_they_are_caused_by() -> None:
    """Stock falls because things were sold; points are earned by spending."""
    assert set(HISTORY_READ["master-data"]) - set(STAGE_DATASETS["master-data"]) == {
        "orders",
        "order_lines",
    }
    assert set(HISTORY_READ["customers"]) - set(STAGE_DATASETS["customers"]) == {"orders"}


def test_a_stage_retail_does_not_run_is_refused_by_name(quiet: SimulationConfig) -> None:
    """Rather than silently producing nothing."""
    with pytest.raises(KeyError, match="runs no stage named"):
        advance_day("growth", quiet, BusinessContext(DAY, seed=1), {}, {})


def test_a_stage_with_no_history_founds_one(quiet: SimulationConfig) -> None:
    """There is no tick counter. A stage that has nothing builds something."""
    day = advance_day("master-data", quiet, BusinessContext(DAY, seed=1), {}, {})

    assert day.is_founding
    assert set(day.generated) == set(STAGE_DATASETS["master-data"])
    assert day.persisted is day.generated


def test_the_execution_date_is_the_reference_date(quiet: SimulationConfig) -> None:
    """The configured reference date is a default for callers with no date."""
    founded = date(2030, 7, 9)
    day = advance_day("master-data", quiet, BusinessContext(founded, seed=1), {}, {})

    assert day.settings.customers.reference_date == founded
    assert quiet.customers.reference_date != founded


# --------------------------------------------------------------------------
# One day, five days, thirty days
# --------------------------------------------------------------------------


def test_one_day_founds_an_enterprise(tmp_path: Path, quiet: SimulationConfig) -> None:
    """Thirty-nine datasets, and nothing evolved because nothing preceded it."""
    shop, report = _simulate(tmp_path, quiet, days=1)

    assert report.succeeded
    assert len(_digests(shop.workspace.data_directory)) == len(RetailDomain().dataset_names)


def test_five_days_grow_the_customer_base(tmp_path: Path, busy: SimulationConfig) -> None:
    """Three people register a day, and they are people who were not there."""
    shop, report = _simulate(tmp_path, busy, days=5)
    customers = _read(shop, "customers")

    assert report.succeeded
    assert customers.height == 25 + 4 * busy.evolution.new_customers_per_day
    joined = customers.filter(pl.col("registration_date") > DAY)
    assert sorted(joined["registration_date"].unique().to_list()) == [
        DAY + timedelta(days=offset) for offset in range(1, 5)
    ]


def test_thirty_days_of_trading_produce_thirty_days_of_orders(
    tmp_path: Path, busy: SimulationConfig
) -> None:
    """Not one day of orders written thirty times."""
    shop, report = _simulate(tmp_path, busy, days=30)
    orders = _read(shop, "orders")
    traded = orders.filter(pl.col("order_date") > DAY)

    assert report.succeeded
    assert traded.height > 0
    # Orders land on many distinct days rather than being heaped on one.
    assert traded["order_date"].n_unique() >= 10


def _assert_a_long_run(tmp_path: Path, config: SimulationConfig, days: int) -> None:
    """Run consecutively for many days and check the result is a business.

    Args:
        tmp_path: Where the project lives.
        config: Retail settings.
        days: How many consecutive days to run.
    """
    shop, report = _simulate(tmp_path, config, days=days)

    assert report.succeeded, report.result.failure
    assert report.progress.completed_ticks == days

    customers = _read(shop, "customers")
    sessions = _read(shop, "sessions")
    last = DAY + timedelta(days=days - 1)

    assert customers.height == 25 + (days - 1) * config.evolution.new_customers_per_day
    assert customers["customer_id"].n_unique() == customers.height
    assert customers.filter(pl.col("registration_date") == last).height == 1
    assert sessions.filter(pl.col("start_time").dt.date() > DAY).height > 0

    everything = {name: _read(shop, name) for name in RetailDomain().dataset_names}
    assert validate_temporal_history(everything) == []


def test_four_months_of_trading_is_four_months_of_business(
    tmp_path: Path, quiet: SimulationConfig
) -> None:
    """A hundred and twenty consecutive days, each adding to the last.

    The longest run in the default suite. What it proves is not a number of
    days but that nothing degrades with them: no rewritten row, no lost
    identity, no repeated business key, no broken temporal rule.
    """
    _assert_a_long_run(tmp_path, quiet, days=120)


@pytest.mark.slow
def test_a_year_of_trading_is_a_year_of_business(tmp_path: Path, quiet: SimulationConfig) -> None:
    """The same, for a full simulated year.

    Marked slow and excluded from the default suite, because it takes minutes
    rather than seconds and asserts nothing the hundred-and-twenty-day run does
    not. Run it with ``pytest -m slow``. It is kept because "a year" is the
    claim this phase makes, and a claim with no test behind it is a hope.
    """
    _assert_a_long_run(tmp_path, quiet, days=365)


# --------------------------------------------------------------------------
# History is immutable and identities survive
# --------------------------------------------------------------------------


def test_a_later_day_never_rewrites_an_earlier_one(tmp_path: Path, busy: SimulationConfig) -> None:
    """Every append-only dataset keeps the rows it had, in the order it had."""
    shop, _ = _simulate(tmp_path, busy, days=4)
    before = {name: _read(shop, name) for name in RetailDomain().dataset_names}

    _simulate(tmp_path, busy, days=4, start=DAY + timedelta(days=4), project=shop)

    for name, earlier in before.items():
        later = _read(shop, name)
        if temporality_of(name) is Temporality.APPEND_ONLY:
            assert later.head(earlier.height).equals(earlier), name
        assert later.height >= earlier.height, name


def test_a_customer_keeps_their_identifier_for_ever(tmp_path: Path, busy: SimulationConfig) -> None:
    """And their registration date, and the name they registered under."""
    shop, _ = _simulate(tmp_path, busy, days=3)
    founding = _read(shop, "customers").select("customer_id", "full_name", "registration_date")

    _simulate(tmp_path, busy, days=6, start=DAY + timedelta(days=3), project=shop)
    later = _read(shop, "customers").select("customer_id", "full_name", "registration_date")

    assert later.head(founding.height).equals(founding)


def test_a_new_entity_never_takes_an_identifier_that_was_used(
    year: Project,
) -> None:
    """Across every dataset, not only the ones that obviously grow."""
    for dataset in RETAIL_DATASETS:
        frame = _read(year, dataset.name)
        key = frame[dataset.primary_key]
        assert key.n_unique() == key.len(), dataset.name


def test_every_business_key_is_still_unique_after_twelve_days(year: Project) -> None:
    """The thing that breaks first when a day's identifiers restart."""
    for dataset in RETAIL_DATASETS:
        frame = _read(year, dataset.name)
        for column in dataset.unique_columns:
            values = frame[column].drop_nulls()
            assert values.n_unique() == values.len(), f"{dataset.name}.{column}"


def test_the_accumulated_history_still_holds_together(year: Project) -> None:
    """Every temporal rule, over everything twelve days produced."""
    everything = {name: _read(year, name) for name in RetailDomain().dataset_names}
    assert validate_temporal_history(everything) == []


# --------------------------------------------------------------------------
# The business behaves like one
# --------------------------------------------------------------------------


def test_orders_never_precede_the_customer_who_placed_them(year: Project) -> None:
    """Including for the customers who registered part-way through."""
    orders = _read(year, "orders")
    customers = _read(year, "customers").select("customer_id", "registration_date")
    joined = orders.join(customers, on="customer_id", how="inner")

    assert joined.filter(pl.col("order_date") < pl.col("registration_date")).is_empty()


def test_a_review_follows_the_purchase_it_is_about(year: Project) -> None:
    """Reviews lag: the parcel has to arrive first."""
    reviews = _read(year, "reviews")
    shipments = _read(year, "shipments").select("shipment_id", "delivered_at")
    joined = reviews.join(shipments, on="shipment_id", how="inner").drop_nulls("delivered_at")

    assert not joined.is_empty()
    assert joined.filter(pl.col("created_at") < pl.col("delivered_at")).is_empty()


def test_loyalty_points_only_ever_accumulate(tmp_path: Path, busy: SimulationConfig) -> None:
    """A balance can fall in a real loyalty scheme. It cannot fall here."""
    shop, _ = _simulate(tmp_path, busy, days=5)
    before = _read(shop, "customer_loyalty").select("customer_id", "points_balance")

    _simulate(tmp_path, busy, days=5, start=DAY + timedelta(days=5), project=shop)
    after = _read(shop, "customer_loyalty").select(
        "customer_id", pl.col("points_balance").alias("later")
    )

    compared = before.join(after, on="customer_id", how="inner")
    assert compared.height == before.height
    assert compared.filter(pl.col("later") < pl.col("points_balance")).is_empty()


def test_somebody_who_bought_something_earns_something(year: Project) -> None:
    """Points are earned by spending, so a spender's balance is not zero."""
    orders = _read(year, "orders").group_by("customer_id").agg(pl.col("total_amount").sum())
    loyalty = _read(year, "customer_loyalty").select("customer_id", "points_balance")
    spenders = orders.join(loyalty, on="customer_id", how="inner")

    assert not spenders.is_empty()
    assert spenders.filter(pl.col("points_balance") <= 0).is_empty()


def test_stock_reflects_what_has_been_sold(tmp_path: Path, busy: SimulationConfig) -> None:
    """Inventory is a picture of now, and now has had things taken from it."""
    shop, _ = _simulate(tmp_path, busy, days=1)
    opening = _read(shop, "inventory")

    _simulate(tmp_path, busy, days=9, start=DAY + timedelta(days=1), project=shop)
    later = _read(shop, "inventory")

    assert later.height == opening.height
    assert later["inventory_id"].to_list() == opening["inventory_id"].to_list()
    assert later["quantity_on_hand"].sum() != opening["quantity_on_hand"].sum()


def test_nothing_is_ever_stocked_below_its_reorder_point(year: Project) -> None:
    """The reorder policy the columns describe, applied."""
    inventory = _read(year, "inventory")
    assert inventory.filter(pl.col("quantity_on_hand") <= pl.col("reorder_point")).is_empty()


def test_a_day_produces_the_sessions_of_that_day(year: Project) -> None:
    """Not a fresh five years of browsing on every tick."""
    sessions = _read(year, "sessions")
    evolved = sessions.filter(pl.col("start_time").dt.date() > DAY)

    assert not evolved.is_empty()
    assert evolved["start_time"].dt.date().to_list() == sorted(
        day for day in evolved["start_time"].dt.date().to_list() if day <= DAY + timedelta(days=11)
    )


# --------------------------------------------------------------------------
# Determinism, division and resume
# --------------------------------------------------------------------------


def test_the_same_seed_and_the_same_days_produce_the_same_year(
    tmp_path: Path, busy: SimulationConfig
) -> None:
    """No wall clock, and no randomness outside the seeded streams."""
    first, _ = _simulate(tmp_path / "a", busy, days=6)
    second, _ = _simulate(tmp_path / "b", busy, days=6)

    assert _digests(first.workspace.data_directory) == _digests(second.workspace.data_directory)


def test_a_different_seed_produces_a_different_business(
    tmp_path: Path, busy: SimulationConfig
) -> None:
    """Otherwise the seed would not be doing anything."""
    first, _ = _simulate(tmp_path / "a", busy, days=4, seed=1)
    second, _ = _simulate(tmp_path / "b", busy, days=4, seed=2)

    assert _digests(first.workspace.data_directory) != _digests(second.workspace.data_directory)


def test_how_a_year_was_divided_up_does_not_show_in_the_year(
    tmp_path: Path, busy: SimulationConfig
) -> None:
    """The strongest property here, and the one resume rests on.

    Nine days run at once, and nine days run as four then three then two,
    produce the same bytes. They can, because a day is seeded by its date and
    continues from what is on disk - so nothing about a run's shape reaches
    the data.
    """
    whole, _ = _simulate(tmp_path / "whole", busy, days=9)

    divided = create_project(tmp_path / "divided", name="Shop", domain="retail", seed=42)
    offset = 0
    for days in (4, 3, 2):
        _simulate(
            tmp_path / "divided",
            busy,
            days=days,
            start=DAY + timedelta(days=offset),
            project=divided,
        )
        offset += days

    assert _digests(divided.workspace.data_directory) == _digests(whole.workspace.data_directory)


def test_a_run_resumed_after_a_failed_stage_continues_the_same_business(
    tmp_path: Path, busy: SimulationConfig
) -> None:
    """Stopping part-way through the founding day loses nothing."""
    whole, _ = _simulate(tmp_path / "whole", busy, days=3)

    halted = create_project(tmp_path / "halted", name="Shop", domain="retail", seed=42)
    execute(
        create_run(
            halted,
            create_clock(DAY, end=DAY),
            RunConfiguration(stop_condition=AfterStage("customers")),
        ),
        RetailExecutor(config=busy),
    )
    execute(
        create_run(
            halted,
            create_clock(DAY, end=DAY),
            RunConfiguration(mode=RunMode.RESUME, stop_condition=AfterTicks(1)),
        ),
        RetailExecutor(config=busy),
    )
    _simulate(tmp_path / "halted", busy, days=2, start=DAY + timedelta(days=1), project=halted)

    assert _digests(halted.workspace.data_directory) == _digests(whole.workspace.data_directory)


def test_running_the_same_day_twice_is_not_the_same_as_running_two_days(
    tmp_path: Path, busy: SimulationConfig
) -> None:
    """A limitation worth pinning: a day is not idempotent.

    Re-running a business date against a history that already contains it
    appends that day's business a second time, because identifiers continue
    from what exists. Nothing in the platform asks for that - the scheduler
    records each stage once and a resume skips what completed - but it is what
    would happen, and a reader should not have to guess.
    """
    shop, _ = _simulate(tmp_path, busy, days=2)
    twice = _read(shop, "sessions").height

    _simulate(tmp_path, busy, days=1, start=DAY + timedelta(days=1), project=shop)

    assert _read(shop, "sessions").height > twice


# --------------------------------------------------------------------------
# The seam is unchanged
# --------------------------------------------------------------------------


def test_retail_never_learns_what_ran_it() -> None:
    """The domain may not import the platform's runtime, at any depth."""
    forbidden = (
        "eds.platform.run",
        "eds.platform.scheduler",
        "eds.platform.runtime",
        "eds.platform.time",
        "eds.platform.project",
        "eds.runners",
    )
    root = Path(__file__).resolve().parent.parent / "domains" / "retail"
    for source in root.rglob("*.py"):
        for line in source.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            assert not any(name in stripped for name in forbidden), f"{source.name}: {stripped}"


def _sources() -> Iterator[Path]:
    """Yield every temporal module's source file."""
    return (Path(__file__).resolve().parent.parent / "domains" / "retail" / "temporal").glob("*.py")


def test_no_temporal_module_reads_a_wall_clock() -> None:
    """A simulated day is the only day this package has heard of."""
    banned = ("datetime.now", "date.today", "time.time", "utcnow")
    for source in _sources():
        text = source.read_text(encoding="utf-8")
        assert not any(name in text for name in banned), source.name
