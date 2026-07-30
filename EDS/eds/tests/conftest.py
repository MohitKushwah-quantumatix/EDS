"""Shared fixtures for the F001 master data tests.

The generated bundle is session-scoped: generation is deterministic and
read-only for these tests, so building it once keeps the suite fast.
"""

from __future__ import annotations

import polars as pl
import pytest

from eds.config import (
    BrowsingConfig,
    CheckoutConfig,
    CommerceConfig,
    CustomerConfig,
    EngagementConfig,
    JourneyConfig,
    MasterDataConfig,
    OrderConfig,
    PaymentConfig,
    PlatformConfig,
    ReturnConfig,
    ReviewConfig,
    ShipmentConfig,
    SimulationConfig,
)
from eds.generators.commerce.checkout_generator import (
    CheckoutData,
    generate_checkout_data,
)
from eds.generators.commerce.commerce import CommerceData, generate_commerce_data
from eds.generators.commerce.orders import OrderData, generate_order_data
from eds.generators.commerce.payments import PaymentData, generate_payment_data
from eds.generators.commerce.returns import ReturnData, generate_return_data
from eds.generators.commerce.reviews import ReviewData, generate_review_data
from eds.generators.commerce.shipments import ShipmentData, generate_shipment_data
from eds.generators.customer_data import CustomerData, generate_customer_data
from eds.generators.customers.customer_generator import CustomerGeography
from eds.generators.journey.browsing import BrowsingData, generate_browsing_data
from eds.generators.journey.category_generator import CategoryCatalog
from eds.generators.journey.engagement import EngagementData, generate_engagement_data
from eds.generators.journey.journey import JourneyData, generate_journey_data
from eds.generators.journey.product_view_generator import ProductCatalog
from eds.generators.journey.session_generator import SessionLocations
from eds.generators.master_data import MasterData, generate_master_data

TEST_SEED = 20260728


@pytest.fixture(scope="session")
def small_master_data_config() -> MasterDataConfig:
    """Return a small but structurally complete master data configuration."""
    return MasterDataConfig(
        countries=("US",),
        cities_per_state=2,
        category_depth=3,
        root_categories=3,
        children_per_category=2,
        brand_count=8,
        supplier_count=6,
        warehouse_count=5,
        product_count=60,
        warehouses_per_product=2,
        batch_size=25,
    )


@pytest.fixture(scope="session")
def simulation_config(small_master_data_config: MasterDataConfig) -> SimulationConfig:
    """Return a deterministic simulation configuration for tests."""
    return SimulationConfig(
        platform=PlatformConfig(seed=TEST_SEED),
        master_data=small_master_data_config,
    )


@pytest.fixture(scope="session")
def master_data(simulation_config: SimulationConfig) -> MasterData:
    """Return a generated master data bundle."""
    return generate_master_data(simulation_config)


@pytest.fixture(scope="session")
def small_customer_config() -> CustomerConfig:
    """Return a small customer configuration that still exercises batching."""
    return CustomerConfig(
        customer_count=120,
        min_addresses=1,
        max_addresses=2,
        registration_years=5,
        batch_size=50,
    )


@pytest.fixture(scope="session")
def customer_simulation_config(
    small_master_data_config: MasterDataConfig, small_customer_config: CustomerConfig
) -> SimulationConfig:
    """Return a deterministic configuration covering master data and customers."""
    return SimulationConfig(
        platform=PlatformConfig(seed=TEST_SEED),
        master_data=small_master_data_config,
        customers=small_customer_config,
    )


@pytest.fixture(scope="session")
def customer_geography(master_data: MasterData) -> CustomerGeography:
    """Return the geography lookup extracted from the F001 datasets."""
    return CustomerGeography.from_frames(
        master_data["cities"], master_data["states"], master_data["countries"]
    )


@pytest.fixture(scope="session")
def customer_data(
    customer_simulation_config: SimulationConfig, master_data: MasterData
) -> CustomerData:
    """Return a generated customer data bundle."""
    return generate_customer_data(customer_simulation_config, master_data.datasets)


@pytest.fixture(scope="session")
def small_journey_config() -> JourneyConfig:
    """Return a small journey configuration that still exercises batching."""
    return JourneyConfig(
        bounce_rate=0.25,
        max_pages_viewed=25,
        session_years=5,
        batch_size=60,
    )


@pytest.fixture(scope="session")
def journey_simulation_config(
    customer_simulation_config: SimulationConfig, small_journey_config: JourneyConfig
) -> SimulationConfig:
    """Return a deterministic configuration covering every feature so far."""
    return SimulationConfig(
        platform=customer_simulation_config.platform,
        master_data=customer_simulation_config.master_data,
        customers=customer_simulation_config.customers,
        journey=small_journey_config,
    )


@pytest.fixture(scope="session")
def journey_upstream(
    master_data: MasterData, customer_data: CustomerData
) -> dict[str, pl.DataFrame]:
    """Return the F001 and F002 datasets the journey feature consumes."""
    return {**master_data.datasets, **customer_data.datasets}


@pytest.fixture(scope="session")
def session_locations(journey_upstream: dict[str, pl.DataFrame]) -> SessionLocations:
    """Return the browsing-location lookup built from upstream data."""
    return SessionLocations.from_frames(
        journey_upstream["customer_addresses"], journey_upstream["countries"]
    )


@pytest.fixture(scope="session")
def journey_data(
    journey_simulation_config: SimulationConfig, journey_upstream: dict[str, pl.DataFrame]
) -> JourneyData:
    """Return a generated journey data bundle."""
    return generate_journey_data(journey_simulation_config, journey_upstream)


@pytest.fixture(scope="session")
def small_browsing_config() -> BrowsingConfig:
    """Return a browsing configuration with a small batch size."""
    return BrowsingConfig(batch_size=400)


@pytest.fixture(scope="session")
def browsing_simulation_config(
    journey_simulation_config: SimulationConfig, small_browsing_config: BrowsingConfig
) -> SimulationConfig:
    """Return a deterministic configuration covering every feature so far."""
    return SimulationConfig(
        platform=journey_simulation_config.platform,
        master_data=journey_simulation_config.master_data,
        customers=journey_simulation_config.customers,
        journey=journey_simulation_config.journey,
        browsing=small_browsing_config,
    )


@pytest.fixture(scope="session")
def browsing_upstream(
    journey_upstream: dict[str, pl.DataFrame], journey_data: JourneyData
) -> dict[str, pl.DataFrame]:
    """Return the datasets the browsing feature consumes."""
    return {**journey_upstream, **journey_data.datasets}


@pytest.fixture(scope="session")
def category_catalog(browsing_upstream: dict[str, pl.DataFrame]) -> CategoryCatalog:
    """Return the browsable category catalog."""
    return CategoryCatalog.from_frame(browsing_upstream["categories"])


@pytest.fixture(scope="session")
def browsing_data(
    browsing_simulation_config: SimulationConfig, browsing_upstream: dict[str, pl.DataFrame]
) -> BrowsingData:
    """Return a generated browsing data bundle."""
    return generate_browsing_data(browsing_simulation_config, browsing_upstream)


@pytest.fixture(scope="session")
def small_engagement_config() -> EngagementConfig:
    """Return an engagement configuration with a small batch size."""
    return EngagementConfig(batch_size=500)


@pytest.fixture(scope="session")
def engagement_simulation_config(
    browsing_simulation_config: SimulationConfig, small_engagement_config: EngagementConfig
) -> SimulationConfig:
    """Return a deterministic configuration covering every feature so far."""
    return SimulationConfig(
        platform=browsing_simulation_config.platform,
        master_data=browsing_simulation_config.master_data,
        customers=browsing_simulation_config.customers,
        journey=browsing_simulation_config.journey,
        browsing=browsing_simulation_config.browsing,
        engagement=small_engagement_config,
    )


@pytest.fixture(scope="session")
def engagement_upstream(
    browsing_upstream: dict[str, pl.DataFrame], browsing_data: BrowsingData
) -> dict[str, pl.DataFrame]:
    """Return the datasets the engagement feature consumes."""
    return {**browsing_upstream, **browsing_data.datasets}


@pytest.fixture(scope="session")
def product_catalog(engagement_upstream: dict[str, pl.DataFrame]) -> ProductCatalog:
    """Return the product catalog with popularity weights."""
    return ProductCatalog.from_frames(
        engagement_upstream["categories"], engagement_upstream["products"], TEST_SEED
    )


@pytest.fixture(scope="session")
def engagement_data(
    engagement_simulation_config: SimulationConfig,
    engagement_upstream: dict[str, pl.DataFrame],
) -> EngagementData:
    """Return a generated engagement data bundle."""
    return generate_engagement_data(engagement_simulation_config, engagement_upstream)


@pytest.fixture(scope="session")
def small_commerce_config() -> CommerceConfig:
    """Return a commerce configuration with a small batch size."""
    return CommerceConfig(batch_size=200)


@pytest.fixture(scope="session")
def commerce_simulation_config(
    engagement_simulation_config: SimulationConfig, small_commerce_config: CommerceConfig
) -> SimulationConfig:
    """Return a deterministic configuration covering every feature so far."""
    return SimulationConfig(
        platform=engagement_simulation_config.platform,
        master_data=engagement_simulation_config.master_data,
        customers=engagement_simulation_config.customers,
        journey=engagement_simulation_config.journey,
        browsing=engagement_simulation_config.browsing,
        engagement=engagement_simulation_config.engagement,
        commerce=small_commerce_config,
    )


@pytest.fixture(scope="session")
def commerce_upstream(
    engagement_upstream: dict[str, pl.DataFrame], engagement_data: EngagementData
) -> dict[str, pl.DataFrame]:
    """Return the datasets the commerce feature consumes."""
    return {**engagement_upstream, **engagement_data.datasets}


@pytest.fixture(scope="session")
def commerce_data(
    commerce_simulation_config: SimulationConfig, commerce_upstream: dict[str, pl.DataFrame]
) -> CommerceData:
    """Return a generated commerce data bundle."""
    return generate_commerce_data(commerce_simulation_config, commerce_upstream)


@pytest.fixture(scope="session")
def small_checkout_config() -> CheckoutConfig:
    """Return a checkout configuration with a small batch size."""
    return CheckoutConfig(batch_size=150)


@pytest.fixture(scope="session")
def checkout_simulation_config(
    commerce_simulation_config: SimulationConfig, small_checkout_config: CheckoutConfig
) -> SimulationConfig:
    """Return a deterministic configuration covering every feature so far."""
    return SimulationConfig(
        platform=commerce_simulation_config.platform,
        master_data=commerce_simulation_config.master_data,
        customers=commerce_simulation_config.customers,
        journey=commerce_simulation_config.journey,
        browsing=commerce_simulation_config.browsing,
        engagement=commerce_simulation_config.engagement,
        commerce=commerce_simulation_config.commerce,
        checkout=small_checkout_config,
    )


@pytest.fixture(scope="session")
def checkout_upstream(
    commerce_upstream: dict[str, pl.DataFrame], commerce_data: CommerceData
) -> dict[str, pl.DataFrame]:
    """Return the datasets the checkout feature consumes."""
    return {**commerce_upstream, **commerce_data.datasets}


@pytest.fixture(scope="session")
def checkout_data(
    checkout_simulation_config: SimulationConfig, checkout_upstream: dict[str, pl.DataFrame]
) -> CheckoutData:
    """Return a generated checkout data bundle."""
    return generate_checkout_data(checkout_simulation_config, checkout_upstream)


@pytest.fixture(scope="session")
def small_order_config() -> OrderConfig:
    """Return an order configuration with a small batch size."""
    return OrderConfig(batch_size=25)


@pytest.fixture(scope="session")
def order_simulation_config(
    checkout_simulation_config: SimulationConfig, small_order_config: OrderConfig
) -> SimulationConfig:
    """Return a deterministic configuration covering every feature so far."""
    return SimulationConfig(
        platform=checkout_simulation_config.platform,
        master_data=checkout_simulation_config.master_data,
        customers=checkout_simulation_config.customers,
        journey=checkout_simulation_config.journey,
        browsing=checkout_simulation_config.browsing,
        engagement=checkout_simulation_config.engagement,
        commerce=checkout_simulation_config.commerce,
        checkout=checkout_simulation_config.checkout,
        orders=small_order_config,
    )


@pytest.fixture(scope="session")
def order_upstream(
    checkout_upstream: dict[str, pl.DataFrame], checkout_data: CheckoutData
) -> dict[str, pl.DataFrame]:
    """Return the datasets the order feature consumes."""
    return {**checkout_upstream, **checkout_data.datasets}


@pytest.fixture(scope="session")
def order_data(
    order_simulation_config: SimulationConfig, order_upstream: dict[str, pl.DataFrame]
) -> OrderData:
    """Return a generated order data bundle."""
    return generate_order_data(order_simulation_config, order_upstream)


@pytest.fixture(scope="session")
def small_payment_config() -> PaymentConfig:
    """Return a payment configuration with a small batch size."""
    return PaymentConfig(batch_size=25)


@pytest.fixture(scope="session")
def payment_simulation_config(
    order_simulation_config: SimulationConfig, small_payment_config: PaymentConfig
) -> SimulationConfig:
    """Return a deterministic configuration covering every feature so far."""
    return SimulationConfig(
        platform=order_simulation_config.platform,
        master_data=order_simulation_config.master_data,
        customers=order_simulation_config.customers,
        journey=order_simulation_config.journey,
        browsing=order_simulation_config.browsing,
        engagement=order_simulation_config.engagement,
        commerce=order_simulation_config.commerce,
        checkout=order_simulation_config.checkout,
        orders=order_simulation_config.orders,
        payments=small_payment_config,
    )


@pytest.fixture(scope="session")
def payment_upstream(
    order_upstream: dict[str, pl.DataFrame], order_data: OrderData
) -> dict[str, pl.DataFrame]:
    """Return the datasets the payment feature consumes."""
    return {**order_upstream, **order_data.datasets}


@pytest.fixture(scope="session")
def payment_data(
    payment_simulation_config: SimulationConfig, payment_upstream: dict[str, pl.DataFrame]
) -> PaymentData:
    """Return a generated payment data bundle."""
    return generate_payment_data(payment_simulation_config, payment_upstream)


@pytest.fixture(scope="session")
def small_shipment_config() -> ShipmentConfig:
    """Return a shipment configuration with a small batch size."""
    return ShipmentConfig(batch_size=25)


@pytest.fixture(scope="session")
def shipment_simulation_config(
    payment_simulation_config: SimulationConfig, small_shipment_config: ShipmentConfig
) -> SimulationConfig:
    """Return a deterministic configuration covering every feature so far."""
    return SimulationConfig(
        platform=payment_simulation_config.platform,
        master_data=payment_simulation_config.master_data,
        customers=payment_simulation_config.customers,
        journey=payment_simulation_config.journey,
        browsing=payment_simulation_config.browsing,
        engagement=payment_simulation_config.engagement,
        commerce=payment_simulation_config.commerce,
        checkout=payment_simulation_config.checkout,
        orders=payment_simulation_config.orders,
        payments=payment_simulation_config.payments,
        shipments=small_shipment_config,
    )


@pytest.fixture(scope="session")
def shipment_upstream(
    payment_upstream: dict[str, pl.DataFrame], payment_data: PaymentData
) -> dict[str, pl.DataFrame]:
    """Return the datasets the shipment feature consumes."""
    return {**payment_upstream, **payment_data.datasets}


@pytest.fixture(scope="session")
def shipment_data(
    shipment_simulation_config: SimulationConfig, shipment_upstream: dict[str, pl.DataFrame]
) -> ShipmentData:
    """Return a generated shipment data bundle."""
    return generate_shipment_data(shipment_simulation_config, shipment_upstream)


@pytest.fixture(scope="session")
def small_return_config() -> ReturnConfig:
    """Return a return configuration with a small batch size.

    The return rate is raised well above the shipped default: the test fixture
    carries a few dozen delivered shipments, and 12 per cent of those would
    leave too few returns for the lifecycle assertions to say anything.
    """
    return ReturnConfig(return_rate=0.60, batch_size=25)


@pytest.fixture(scope="session")
def return_simulation_config(
    shipment_simulation_config: SimulationConfig, small_return_config: ReturnConfig
) -> SimulationConfig:
    """Return a deterministic configuration covering every feature so far."""
    return SimulationConfig(
        platform=shipment_simulation_config.platform,
        master_data=shipment_simulation_config.master_data,
        customers=shipment_simulation_config.customers,
        journey=shipment_simulation_config.journey,
        browsing=shipment_simulation_config.browsing,
        engagement=shipment_simulation_config.engagement,
        commerce=shipment_simulation_config.commerce,
        checkout=shipment_simulation_config.checkout,
        orders=shipment_simulation_config.orders,
        payments=shipment_simulation_config.payments,
        shipments=shipment_simulation_config.shipments,
        returns=small_return_config,
    )


@pytest.fixture(scope="session")
def return_upstream(
    shipment_upstream: dict[str, pl.DataFrame], shipment_data: ShipmentData
) -> dict[str, pl.DataFrame]:
    """Return the datasets the return feature consumes."""
    return {**shipment_upstream, **shipment_data.datasets}


@pytest.fixture(scope="session")
def return_data(
    return_simulation_config: SimulationConfig, return_upstream: dict[str, pl.DataFrame]
) -> ReturnData:
    """Return a generated return data bundle."""
    return generate_return_data(return_simulation_config, return_upstream)


@pytest.fixture(scope="session")
def small_review_config() -> ReviewConfig:
    """Return a review configuration with a small batch size.

    The review rate is raised well above the shipped default: the test fixture
    carries a few dozen eligible items, and 18 per cent of those would leave
    too few reviews for the rating assertions to say anything.
    """
    return ReviewConfig(review_rate=0.70, batch_size=25)


@pytest.fixture(scope="session")
def review_simulation_config(
    return_simulation_config: SimulationConfig, small_review_config: ReviewConfig
) -> SimulationConfig:
    """Return a deterministic configuration covering every feature."""
    return SimulationConfig(
        platform=return_simulation_config.platform,
        master_data=return_simulation_config.master_data,
        customers=return_simulation_config.customers,
        journey=return_simulation_config.journey,
        browsing=return_simulation_config.browsing,
        engagement=return_simulation_config.engagement,
        commerce=return_simulation_config.commerce,
        checkout=return_simulation_config.checkout,
        orders=return_simulation_config.orders,
        payments=return_simulation_config.payments,
        shipments=return_simulation_config.shipments,
        returns=return_simulation_config.returns,
        reviews=small_review_config,
    )


@pytest.fixture(scope="session")
def review_upstream(
    return_upstream: dict[str, pl.DataFrame], return_data: ReturnData
) -> dict[str, pl.DataFrame]:
    """Return the datasets the review feature consumes."""
    return {**return_upstream, **return_data.datasets}


@pytest.fixture(scope="session")
def review_data(
    review_simulation_config: SimulationConfig, review_upstream: dict[str, pl.DataFrame]
) -> ReviewData:
    """Return a generated review data bundle."""
    return generate_review_data(review_simulation_config, review_upstream)
