"""Tests for the commercial reference-data generators."""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import MasterDataConfig
from eds.domain.enums import CouponDiscountType, PaymentMethodType, ServiceLevel
from eds.generators.commercial.generator import (
    generate_coupon_types,
    generate_payment_methods,
    generate_shipping_methods,
    generate_tax_codes,
)


def test_payment_methods_are_deterministic_without_a_seed() -> None:
    """The catalogue is fixed, so repeated calls are identical."""
    assert generate_payment_methods().equals(generate_payment_methods())


def test_payment_method_codes_are_unique() -> None:
    """Method codes form a natural key."""
    frame = generate_payment_methods()

    assert frame["method_code"].n_unique() == frame.height


def test_payment_method_types_are_known_enum_values() -> None:
    """Every method type is a declared enum member."""
    frame = generate_payment_methods()
    known = {str(member) for member in PaymentMethodType}

    assert set(frame["method_type"].to_list()) <= known


def test_processing_fees_are_non_negative() -> None:
    """A negative processing fee would be a revenue bug downstream."""
    assert all(fee >= 0 for fee in generate_payment_methods()["processing_fee_pct"].to_list())


def test_shipping_methods_have_coherent_transit_windows() -> None:
    """The minimum transit day never exceeds the maximum."""
    frame = generate_shipping_methods()
    pairs = zip(
        frame["min_transit_days"].to_list(), frame["max_transit_days"].to_list(), strict=True
    )

    assert all(minimum <= maximum for minimum, maximum in pairs)


def test_shipping_service_levels_are_known_enum_values() -> None:
    """Every service level is a declared enum member."""
    frame = generate_shipping_methods()
    known = {str(member) for member in ServiceLevel}

    assert set(frame["service_level"].to_list()) <= known


def test_shipping_costs_are_non_negative() -> None:
    """Base and per-kilogram costs are never negative."""
    frame = generate_shipping_methods()

    assert all(cost >= 0 for cost in frame["base_cost"].to_list())
    assert all(cost >= 0 for cost in frame["cost_per_kg"].to_list())


def test_coupon_types_use_known_discount_types() -> None:
    """Every discount type is a declared enum member."""
    frame = generate_coupon_types()
    known = {str(member) for member in CouponDiscountType}

    assert set(frame["discount_type"].to_list()) <= known


def test_percentage_coupons_do_not_exceed_one_hundred_percent() -> None:
    """A percentage discount above 100 would produce negative revenue."""
    frame = generate_coupon_types().filter(
        pl.col("discount_type") == str(CouponDiscountType.PERCENTAGE)
    )

    assert all(value <= 100 for value in frame["discount_value"].to_list())


def test_tax_codes_are_generated_per_country() -> None:
    """Tax codes are repeated for each configured country."""
    one = generate_tax_codes(MasterDataConfig(countries=("US",)))
    two = generate_tax_codes(MasterDataConfig(countries=("US", "CA")))

    assert two.height == one.height * 2


def test_tax_codes_are_unique_across_countries() -> None:
    """The country prefix keeps tax codes unique."""
    frame = generate_tax_codes(MasterDataConfig(countries=("US", "CA", "GB")))

    assert frame["tax_code"].n_unique() == frame.height


def test_tax_code_country_ids_are_sequential() -> None:
    """Tax code country ids line up with the generated countries."""
    frame = generate_tax_codes(MasterDataConfig(countries=("US", "CA")))

    assert set(frame["country_id"].to_list()) == {1, 2}


@pytest.mark.parametrize("rate", [0.0, 100.0])
def test_tax_rates_are_within_percentage_bounds(rate: float) -> None:
    """Generated tax rates stay inside a sane percentage range."""
    frame = generate_tax_codes(MasterDataConfig(countries=("US",)))

    assert all(0.0 <= value <= 100.0 for value in frame["tax_rate_pct"].to_list())
    assert rate >= 0.0
