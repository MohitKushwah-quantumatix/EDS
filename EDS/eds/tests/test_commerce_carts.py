"""Tests for the shopping cart generator."""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import CommerceConfig
from eds.domain.commerce.enums import CartStatus
from eds.domain.commerce.schema import CART_ITEMS
from eds.domain.journey.enums import PersonaName
from eds.generators.commerce.cart_generator import (
    PERSONA_CART_PROFILES,
    generate_carts,
    persona_cart_profile,
    plan_carts,
)
from eds.generators.commerce.commerce import CommerceData
from eds.generators.frames import empty_frame

SEED = 7070


@pytest.fixture
def config() -> CommerceConfig:
    """Return a commerce configuration with a small batch size."""
    return CommerceConfig(batch_size=200)


@pytest.fixture
def carts(commerce_data: CommerceData) -> pl.DataFrame:
    """Return the generated shopping carts frame."""
    return commerce_data["shopping_carts"]


@pytest.fixture
def cart_items(commerce_data: CommerceData) -> pl.DataFrame:
    """Return the generated cart items frame."""
    return commerce_data["cart_items"]


@pytest.fixture
def sessions(commerce_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the sessions frame."""
    return commerce_upstream["sessions"]


@pytest.fixture
def personas(commerce_upstream: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Return the customer personas frame."""
    return commerce_upstream["customer_personas"]


def test_every_persona_has_a_cart_profile() -> None:
    """All six personas can fill a cart."""
    assert set(PERSONA_CART_PROFILES) == {str(member) for member in PersonaName}


def test_loyal_customer_has_the_highest_checkout_weight() -> None:
    """The documented persona guidance is encoded in the profiles."""
    checkout = {name: profile.status_weights[1] for name, profile in PERSONA_CART_PROFILES.items()}

    assert checkout[str(PersonaName.LOYAL_CUSTOMER)] == max(checkout.values())


def test_window_shopper_abandons_most() -> None:
    """A window shopper's carts are mostly abandoned."""
    abandoned = {name: profile.status_weights[0] for name, profile in PERSONA_CART_PROFILES.items()}

    assert abandoned[str(PersonaName.WINDOW_SHOPPER)] == max(abandoned.values())


def test_researcher_wishlists_most_and_impulse_buyer_least() -> None:
    """Wishlist-before-cart ordering matches the specification."""
    rates = {name: profile.wishlist_rate for name, profile in PERSONA_CART_PROFILES.items()}

    assert rates[str(PersonaName.RESEARCHER)] == max(rates.values())
    assert rates[str(PersonaName.IMPULSE_BUYER)] == min(rates.values())


def test_impulse_buyer_has_the_smallest_carts() -> None:
    """The impulse buyer's size weights are the most concentrated on one."""
    single = {name: profile.size_weights[0] for name, profile in PERSONA_CART_PROFILES.items()}

    assert single[str(PersonaName.IMPULSE_BUYER)] == max(single.values())


def test_unknown_persona_profile_raises() -> None:
    """A persona without a cart profile fails with the supported list."""
    with pytest.raises(KeyError, match="Supported personas"):
        persona_cart_profile("TIME_TRAVELLER")


def test_bounced_sessions_never_start_a_cart(
    config: CommerceConfig, sessions: pl.DataFrame, personas: pl.DataFrame
) -> None:
    """A single page view does not reach a cart."""
    planned = plan_carts(config, sessions, personas, SEED)
    bounced = set(sessions.filter(pl.col("bounce"))["session_id"].to_list())

    assert not ({cart.session_id for cart in planned} & bounced)


def test_planning_is_deterministic(
    config: CommerceConfig, sessions: pl.DataFrame, personas: pl.DataFrame
) -> None:
    """The same seed plans the same carts."""
    assert plan_carts(config, sessions, personas, SEED) == plan_carts(
        config, sessions, personas, SEED
    )


def test_planning_varies_with_the_seed(
    config: CommerceConfig, sessions: pl.DataFrame, personas: pl.DataFrame
) -> None:
    """A different seed plans different carts."""
    assert plan_carts(config, sessions, personas, 1) != plan_carts(config, sessions, personas, 2)


def test_a_zero_rate_plans_no_carts(sessions: pl.DataFrame, personas: pl.DataFrame) -> None:
    """Turning the rate off produces no carts at all."""
    assert plan_carts(CommerceConfig(cart_session_rate=0.0), sessions, personas, SEED) == []


def test_unknown_persona_on_a_session_is_reported(
    config: CommerceConfig, sessions: pl.DataFrame, personas: pl.DataFrame
) -> None:
    """A session naming an unsupported persona fails loudly."""
    broken = sessions.with_columns(pl.lit("TIME_TRAVELLER").alias("persona_name"))

    with pytest.raises(KeyError, match="Supported personas"):
        plan_carts(config, broken, personas, SEED)


def test_cart_ids_are_unique(carts: pl.DataFrame) -> None:
    """Cart ids form a primary key."""
    assert carts["cart_id"].n_unique() == carts.height


def test_a_session_has_at_most_one_cart(carts: pl.DataFrame) -> None:
    """Session is a natural key on carts."""
    assert carts["session_id"].n_unique() == carts.height


def test_every_cart_belongs_to_its_session_customer(
    carts: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """The cart's customer is the customer who owned the session."""
    joined = carts.join(
        sessions.select("session_id", pl.col("customer_id").alias("session_customer")),
        on="session_id",
        how="inner",
    )

    assert joined.height == carts.height
    assert joined.filter(pl.col("customer_id") != pl.col("session_customer")).height == 0


def test_a_customer_may_have_multiple_carts(carts: pl.DataFrame) -> None:
    """Carts are per session, so a customer can hold several."""
    assert carts["customer_id"].n_unique() < carts.height


def test_cart_statuses_are_declared_values(carts: pl.DataFrame) -> None:
    """Every status comes from the enum."""
    assert set(carts["cart_status"].to_list()) <= {str(m) for m in CartStatus}


def test_cart_status_distribution_is_approximately_as_specified(
    carts: pl.DataFrame,
) -> None:
    """Statuses follow roughly the documented 55/40/5 split."""
    share = {
        row["cart_status"]: row["count"] / carts.height
        for row in carts["cart_status"].value_counts().to_dicts()
    }

    assert share[str(CartStatus.ABANDONED)] == pytest.approx(0.55, abs=0.10)
    assert share[str(CartStatus.CHECKED_OUT)] == pytest.approx(0.40, abs=0.10)
    assert share[str(CartStatus.ACTIVE)] == pytest.approx(0.05, abs=0.05)


def test_loyal_customers_check_out_more_than_window_shoppers(
    carts: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """The persona guidance shows up in the generated data."""
    joined = carts.join(sessions.select("session_id", "persona_name"), on="session_id")
    loyal = joined.filter(pl.col("persona_name") == str(PersonaName.LOYAL_CUSTOMER))
    window = joined.filter(pl.col("persona_name") == str(PersonaName.WINDOW_SHOPPER))

    loyal_share = (
        loyal.filter(pl.col("cart_status") == str(CartStatus.CHECKED_OUT)).height / loyal.height
    )
    window_share = (
        window.filter(pl.col("cart_status") == str(CartStatus.CHECKED_OUT)).height / window.height
    )

    assert loyal_share > window_share


def test_researchers_have_larger_carts_than_impulse_buyers(
    carts: pl.DataFrame, sessions: pl.DataFrame
) -> None:
    """Cart size follows the persona profile."""
    joined = carts.join(sessions.select("session_id", "persona_name"), on="session_id")
    researcher = joined.filter(pl.col("persona_name") == str(PersonaName.RESEARCHER))
    impulse = joined.filter(pl.col("persona_name") == str(PersonaName.IMPULSE_BUYER))

    researcher_mean = sum(researcher["item_count"].to_list()) / researcher.height
    impulse_mean = sum(impulse["item_count"].to_list()) / impulse.height

    assert researcher_mean > impulse_mean


def test_every_cart_holds_at_least_one_item(carts: pl.DataFrame) -> None:
    """An empty cart is never written."""
    assert carts.filter(pl.col("item_count") < 1).height == 0


def test_item_count_matches_the_items_present(
    carts: pl.DataFrame, cart_items: pl.DataFrame
) -> None:
    """The denormalised count agrees with the item rows."""
    actual = cart_items.group_by("cart_id").len().rename({"len": "actual"})
    joined = carts.join(actual, on="cart_id", how="left").with_columns(
        pl.col("actual").fill_null(0)
    )

    assert joined.filter(pl.col("item_count") != pl.col("actual")).height == 0


def test_cart_size_distribution_is_approximately_as_specified(
    carts: pl.DataFrame,
) -> None:
    """Sizes follow roughly the documented 55/25/12/5/3 split."""
    total = carts.height
    counts = carts["item_count"].to_list()
    share = {size: counts.count(size) / total for size in (1, 2, 3, 4)}
    five_plus = sum(1 for size in counts if size >= 5) / total

    assert share[1] == pytest.approx(0.55, abs=0.12)
    assert share[2] == pytest.approx(0.25, abs=0.10)
    assert share[3] == pytest.approx(0.12, abs=0.08)
    assert share[4] == pytest.approx(0.05, abs=0.05)
    assert five_plus == pytest.approx(0.03, abs=0.05)


def test_updated_at_is_after_created_at(carts: pl.DataFrame) -> None:
    """Audit timestamps are strictly ordered."""
    assert carts.filter(pl.col("updated_at") <= pl.col("created_at")).height == 0


def test_carts_fall_inside_their_session(carts: pl.DataFrame, sessions: pl.DataFrame) -> None:
    """A cart is opened and last touched inside its session."""
    joined = carts.join(sessions.select("session_id", "start_time", "end_time"), on="session_id")

    assert joined.filter(pl.col("created_at") < pl.col("start_time")).height == 0
    assert joined.filter(pl.col("updated_at") > pl.col("end_time")).height == 0


def test_a_cart_with_no_items_is_dropped(
    config: CommerceConfig, sessions: pl.DataFrame, personas: pl.DataFrame
) -> None:
    """A planned cart that received nothing is never written."""
    planned = plan_carts(config, sessions, personas, SEED)

    written = generate_carts(planned, empty_frame(CART_ITEMS), config.batch_size)

    assert planned
    assert written.height == 0


def test_batching_does_not_change_the_output(
    config: CommerceConfig,
    sessions: pl.DataFrame,
    personas: pl.DataFrame,
    cart_items: pl.DataFrame,
) -> None:
    """Batch size is an implementation detail, not a data change."""
    planned = plan_carts(config, sessions, personas, SEED)

    small = generate_carts(planned, cart_items, 13)
    large = generate_carts(planned, cart_items, 1_000_000)

    assert small.equals(large)
