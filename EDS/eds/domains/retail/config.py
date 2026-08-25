"""Business configuration for the Retail domain.

One Pydantic model per feature, aggregated by :class:`SimulationConfig`, plus
the loader for each ``configs/*.yaml`` file. Every model is frozen and forbids
unknown keys, so a malformed or out-of-range configuration fails at load time
with a precise error rather than part-way through a long generation run.

The domain-independent machinery - :class:`~eds.core.config.PlatformConfig`,
:class:`~eds.core.config.ConfigError`, and the YAML helpers - lives in
:mod:`eds.core.config` (PADR-002). This module holds only what is specific to
retail.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eds.core.config import (
    DEFAULT_CONFIG_DIR,
    ConfigError,
    build_model,
    read_yaml_mapping,
)

#: Retail-specific configuration directory.
RETAIL_CONFIG_DIR: Final[Path] = DEFAULT_CONFIG_DIR / "retail"


def _retail_config_dir(config_dir: Path | None = None) -> Path:
    """Resolve the retail configuration directory.

    Supports both the flat layout (``configs/master_data.yaml``) and the
    domain-subdirectory layout (``configs/retail/master_data.yaml``) so that
    existing callers and tests continue to work unchanged.
    """
    base = config_dir or DEFAULT_CONFIG_DIR
    if (base / MASTER_DATA_CONFIG_FILE).is_file():
        return base
    return base / "retail"

from eds.platform.config import PlatformConfig, load_platform_config

__all__ = [
    "BrowsingConfig",
    "CheckoutConfig",
    "CommerceConfig",
    "ConfigError",
    "DEFAULT_CARRIERS",
    "DEFAULT_DELIVERY_DAYS",
    "DEFAULT_RATING_WEIGHTS",
    "DEFAULT_REFUND_TYPES",
    "DEFAULT_REVIEW_TEXTS",
    "DEFAULT_REVIEW_TITLES",
    "EVOLUTION_CONFIG_FILE",
    "EngagementConfig",
    "EvolutionConfig",
    "CustomerConfig",
    "JourneyConfig",
    "MasterDataConfig",
    "OrderConfig",
    "PaymentConfig",
    "PlatformConfig",
    "ReturnConfig",
    "ReviewConfig",
    "ShipmentConfig",
    "SimulationConfig",
    "load_browsing_config",
    "load_checkout_config",
    "load_commerce_config",
    "load_config",
    "load_engagement_config",
    "load_evolution_config",
    "load_order_config",
    "load_payment_config",
    "load_return_config",
    "load_review_config",
    "load_shipment_config",
    "load_customer_config",
    "load_journey_config",
    "load_master_data_config",
    "load_platform_config",
]

MASTER_DATA_CONFIG_FILE: Final[str] = "master_data.yaml"
CUSTOMER_CONFIG_FILE: Final[str] = "customers.yaml"
JOURNEY_CONFIG_FILE: Final[str] = "journey.yaml"
BROWSING_CONFIG_FILE: Final[str] = "browsing.yaml"
ENGAGEMENT_CONFIG_FILE: Final[str] = "engagement.yaml"
COMMERCE_CONFIG_FILE: Final[str] = "commerce.yaml"
CHECKOUT_CONFIG_FILE: Final[str] = "checkout.yaml"
ORDER_CONFIG_FILE: Final[str] = "orders.yaml"
PAYMENT_CONFIG_FILE: Final[str] = "payments.yaml"
SHIPMENT_CONFIG_FILE: Final[str] = "shipments.yaml"
RETURN_CONFIG_FILE: Final[str] = "returns.yaml"
REVIEW_CONFIG_FILE: Final[str] = "reviews.yaml"
EVOLUTION_CONFIG_FILE: Final[str] = "evolution.yaml"

#: How often each star rating is left, used when ``reviews.yaml`` does not say.
#: The shape is the familiar J-curve: most reviewers are happy, and the
#: unhappy ones are the next most likely to bother writing anything.
DEFAULT_RATING_WEIGHTS: Final[dict[int, float]] = {
    5: 0.40,
    4: 0.30,
    3: 0.15,
    2: 0.10,
    1: 0.05,
}

#: Review titles per rating. Short, fixed phrases rather than generated prose.
DEFAULT_REVIEW_TITLES: Final[dict[int, tuple[str, ...]]] = {
    5: ("Excellent Product", "Highly Recommended", "Loved It"),
    4: ("Good Quality", "Worth Buying"),
    3: ("Average Experience", "Meets Expectations"),
    2: ("Could Be Better", "Not As Expected"),
    1: ("Very Disappointed", "Poor Quality"),
}

#: Review bodies per rating. One sentence each, by design.
DEFAULT_REVIEW_TEXTS: Final[dict[int, tuple[str, ...]]] = {
    5: (
        "The product exceeded my expectations.",
        "Excellent quality and it arrived quickly.",
    ),
    4: (
        "The product is well made and does the job.",
        "Good value for the money.",
    ),
    3: (
        "The product is acceptable for the price.",
        "It works, but nothing stood out.",
    ),
    2: (
        "The product is not quite what I expected.",
        "The quality is lower than the description suggested.",
    ),
    1: (
        "The product did not meet expectations.",
        "The item arrived in poor condition.",
    ),
}

#: How a return is settled, and how often. Used when ``returns.yaml`` does not
#: name the refund types. The reason vocabulary is deliberately absent: that is
#: master data, read from ``return_reasons.parquet``.
DEFAULT_REFUND_TYPES: Final[dict[str, float]] = {
    "FULL_REFUND": 0.70,
    "STORE_CREDIT": 0.20,
    "REPLACEMENT": 0.10,
}

#: Carriers available for each shipping method, used when ``shipments.yaml``
#: does not name them. The keys are F005 shipping methods; the configuration
#: layer treats them as opaque strings and the generator checks the coverage.
DEFAULT_CARRIERS: Final[dict[str, tuple[str, ...]]] = {
    "STANDARD": ("UPS", "FedEx", "DHL"),
    "EXPRESS": ("FedEx Priority", "DHL Express"),
    "NEXT_DAY": ("UPS Next Day",),
    "STORE_PICKUP": ("Store Pickup",),
}

#: Inclusive ``(min, max)`` delivery day range promised for each method.
DEFAULT_DELIVERY_DAYS: Final[dict[str, tuple[int, int]]] = {
    "STANDARD": (3, 7),
    "EXPRESS": (1, 3),
    "NEXT_DAY": (1, 1),
    "STORE_PICKUP": (0, 0),
}


class MasterDataConfig(BaseModel):
    """Business configuration for the F001 master data generator.

    Attributes:
        countries: ISO 3166-1 alpha-2 codes to include. Must be non-empty.
        cities_per_state: Cities generated for each state.
        category_depth: Depth of the category tree, from 1 to 4.
        root_categories: Number of level-1 categories.
        children_per_category: Child categories created per non-leaf category.
        brand_count: Number of brands.
        supplier_count: Number of suppliers.
        warehouse_count: Number of warehouses.
        product_count: Number of products.
        warehouses_per_product: Warehouses each product is stocked in.
        batch_size: Rows generated per batch for large datasets.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    countries: tuple[str, ...] = ("US",)
    cities_per_state: int = Field(default=5, ge=1, le=1000)
    category_depth: int = Field(default=3, ge=1, le=4)
    root_categories: int = Field(default=8, ge=1, le=100)
    children_per_category: int = Field(default=4, ge=1, le=50)
    brand_count: int = Field(default=50, ge=1)
    supplier_count: int = Field(default=25, ge=1)
    warehouse_count: int = Field(default=10, ge=1)
    product_count: int = Field(default=1_000, ge=1)
    warehouses_per_product: int = Field(default=3, ge=1)
    batch_size: int = Field(default=100_000, ge=1)

    @field_validator("countries", mode="before")
    @classmethod
    def _normalise_countries(cls, value: object) -> object:
        """Upper-case and de-duplicate country codes while preserving order."""
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return value
        seen: dict[str, None] = {}
        for item in value:
            if isinstance(item, str):
                seen.setdefault(item.strip().upper(), None)
            else:
                return value
        return tuple(seen)

    @field_validator("countries")
    @classmethod
    def _require_at_least_one_country(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Reject an empty country list, which would yield no geography."""
        if not value:
            raise ValueError("countries must contain at least one country code")
        return value

    @model_validator(mode="after")
    def _check_warehouse_coverage(self) -> MasterDataConfig:
        """Ensure every product can be stocked in the requested warehouses."""
        if self.warehouses_per_product > self.warehouse_count:
            raise ValueError(
                f"warehouses_per_product ({self.warehouses_per_product}) cannot exceed "
                f"warehouse_count ({self.warehouse_count})"
            )
        return self

    @property
    def inventory_row_estimate(self) -> int:
        """Return the number of inventory rows this configuration implies."""
        return self.product_count * self.warehouses_per_product


class EvolutionConfig(BaseModel):
    """How much business happens on one simulated day.

    These are the only settings that describe *change* rather than *shape*.
    Every other model here answers "what does the enterprise look like"; this
    one answers "what does a day do to it".

    The founding day ignores every one of them: it uses the snapshot
    generators, which build a whole enterprise with a history already behind
    it. From the second day onwards these rates decide how many people join,
    how many of them come back, and what a purchase is worth in points.

    Attributes:
        new_customers_per_day: How many customers register on a simulated day.
            Zero is meaningful: a business that acquires nobody still trades.
        active_customer_rate: Share of the existing customer base that opens a
            session on a given day.
        max_daily_sessions: Most sessions one active customer starts in a day.
        loyalty_points_per_unit: Points awarded per unit of settled spend.
            Balances are recomputed from lifetime spend and never decrease.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    new_customers_per_day: int = Field(default=5, ge=0)
    active_customer_rate: float = Field(default=0.02, ge=0.0, le=1.0)
    max_daily_sessions: int = Field(default=2, ge=1)
    loyalty_points_per_unit: float = Field(default=1.0, ge=0.0)


class CustomerConfig(BaseModel):
    """Business configuration for the F002 customer generator.

    Attributes:
        customer_count: Number of customers to generate.
        min_addresses: Fewest addresses a customer may have.
        max_addresses: Most addresses a customer may have.
        registration_years: How far back registration dates may reach.
        reference_date: The "as of" date the dataset is generated relative to.
            Fixed rather than today's date so that a run is reproducible on any
            day.
        batch_size: Rows generated per batch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_count: int = Field(default=1_000, ge=1)
    min_addresses: int = Field(default=1, ge=1)
    max_addresses: int = Field(default=2, ge=1)
    registration_years: int = Field(default=5, ge=1, le=50)
    reference_date: date = date(2026, 1, 1)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_address_bounds(self) -> CustomerConfig:
        """Ensure the address range is not inverted."""
        if self.min_addresses > self.max_addresses:
            raise ValueError(
                f"min_addresses ({self.min_addresses}) cannot exceed "
                f"max_addresses ({self.max_addresses})"
            )
        return self

    @property
    def earliest_registration_date(self) -> date:
        """Return the oldest registration date this configuration allows."""
        return max(self.reference_date - timedelta(days=365 * self.registration_years), date(2026, 1, 1))


class JourneyConfig(BaseModel):
    """Business configuration for the F003.1 journey generator.

    The reference date and registration window are deliberately absent: a
    session is anchored to its customer's registration date, so both come from
    :class:`CustomerConfig` and cannot disagree with the customer data.

    Attributes:
        bounce_rate: Share of sessions that end on the landing page.
        max_pages_viewed: Upper bound on pages viewed in a non-bounce session.
        session_years: Window, in years, that sessions must fall within.
        batch_size: Rows generated per batch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    bounce_rate: float = Field(default=0.25, ge=0.0, le=1.0)
    max_pages_viewed: int = Field(default=25, ge=2)
    session_years: int = Field(default=5, ge=1, le=50)
    batch_size: int = Field(default=100_000, ge=1)


class BrowsingConfig(BaseModel):
    """Business configuration for the F003.2 browsing generator.

    Per-persona view and search ranges live in the generators, as F003.1 does
    for its persona profiles. These settings are the global envelope every
    persona range is clamped into.

    Attributes:
        min_category_views: Fewest category views in a session.
        max_category_views: Most category views in a session.
        min_view_seconds: Shortest time spent on a category page.
        max_view_seconds: Longest time spent on a category page.
        min_searches: Fewest searches in a session.
        max_searches: Most searches in a session.
        max_results_count: Largest result count a search may report.
        no_results_rate: Share of searches that return nothing.
        click_through_rate: Share of searches with results that get a click.
        batch_size: Rows generated per batch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_category_views: int = Field(default=1, ge=1)
    max_category_views: int = Field(default=10, ge=1)
    min_view_seconds: int = Field(default=5, ge=1)
    max_view_seconds: int = Field(default=180, ge=1)
    min_searches: int = Field(default=0, ge=0)
    max_searches: int = Field(default=10, ge=0)
    max_results_count: int = Field(default=250, ge=0)
    no_results_rate: float = Field(default=0.06, ge=0.0, le=1.0)
    click_through_rate: float = Field(default=0.55, ge=0.0, le=1.0)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_bounds(self) -> BrowsingConfig:
        """Ensure no range is inverted."""
        if self.min_category_views > self.max_category_views:
            raise ValueError(
                f"min_category_views ({self.min_category_views}) cannot exceed "
                f"max_category_views ({self.max_category_views})"
            )
        if self.min_view_seconds > self.max_view_seconds:
            raise ValueError(
                f"min_view_seconds ({self.min_view_seconds}) cannot exceed "
                f"max_view_seconds ({self.max_view_seconds})"
            )
        if self.min_searches > self.max_searches:
            raise ValueError(
                f"min_searches ({self.min_searches}) cannot exceed "
                f"max_searches ({self.max_searches})"
            )
        return self


class EngagementConfig(BaseModel):
    """Business configuration for the F003.3 engagement generator.

    Per-persona view counts, durations, and wishlist adoption rates live in
    the generators, as earlier journey features do for their profiles.

    Attributes:
        min_product_views: Fewest product views per category view.
        max_product_views: Most product views per category view.
        min_view_seconds: Shortest time spent on a product page.
        max_view_seconds: Longest time spent on a product page.
        wishlist_view_rate: Scales a persona's wishlist propensity into a
            per-product-view chance of adding to the wishlist. Only customers
            who adopt the wishlist at all are offered the chance.
        batch_size: Rows generated per batch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_product_views: int = Field(default=1, ge=1)
    max_product_views: int = Field(default=8, ge=1)
    min_view_seconds: int = Field(default=5, ge=1)
    max_view_seconds: int = Field(default=600, ge=1)
    wishlist_view_rate: float = Field(default=0.28, ge=0.0, le=1.0)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_bounds(self) -> EngagementConfig:
        """Ensure no range is inverted."""
        if self.min_product_views > self.max_product_views:
            raise ValueError(
                f"min_product_views ({self.min_product_views}) cannot exceed "
                f"max_product_views ({self.max_product_views})"
            )
        if self.min_view_seconds > self.max_view_seconds:
            raise ValueError(
                f"min_view_seconds ({self.min_view_seconds}) cannot exceed "
                f"max_view_seconds ({self.max_view_seconds})"
            )
        return self


class CommerceConfig(BaseModel):
    """Business configuration for the F004 shopping cart generator.

    Per-persona cart rates, sizes, and statuses live in the generators, as
    earlier journey features do for their profiles.

    Attributes:
        cart_session_rate: Scales a persona's cart propensity into a
            per-session chance of starting a cart.
        min_quantity: Fewest units of one product in a cart.
        max_quantity: Most units of one product in a cart.
        max_cart_items: Upper bound on distinct products in one cart.
        removal_rate: Share of cart items the customer later removes.
        batch_size: Rows generated per batch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    cart_session_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    min_quantity: int = Field(default=1, ge=1)
    max_quantity: int = Field(default=5, ge=1)
    max_cart_items: int = Field(default=7, ge=1)
    removal_rate: float = Field(default=0.12, ge=0.0, le=1.0)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_bounds(self) -> CommerceConfig:
        """Ensure the quantity range is not inverted."""
        if self.min_quantity > self.max_quantity:
            raise ValueError(
                f"min_quantity ({self.min_quantity}) cannot exceed "
                f"max_quantity ({self.max_quantity})"
            )
        return self


class CheckoutConfig(BaseModel):
    """Business configuration for the F005 checkout generator.

    Status, shipping, and payment splits live in the generator, as earlier
    features do for their distributions.

    Attributes:
        min_tax_rate: Lowest tax rate applied to the subtotal.
        max_tax_rate: Highest tax rate applied to the subtotal.
        same_address_rate: Share of checkouts billed to the shipping address.
        min_checkout_seconds: Shortest time from starting to finishing.
        max_checkout_seconds: Longest time from starting to finishing.
        batch_size: Rows generated per batch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_tax_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    max_tax_rate: float = Field(default=0.18, ge=0.0, le=1.0)
    same_address_rate: float = Field(default=0.80, ge=0.0, le=1.0)
    min_checkout_seconds: int = Field(default=30, ge=1)
    max_checkout_seconds: int = Field(default=900, ge=1)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_bounds(self) -> CheckoutConfig:
        """Ensure no range is inverted."""
        if self.min_tax_rate > self.max_tax_rate:
            raise ValueError(
                f"min_tax_rate ({self.min_tax_rate}) cannot exceed "
                f"max_tax_rate ({self.max_tax_rate})"
            )
        if self.min_checkout_seconds > self.max_checkout_seconds:
            raise ValueError(
                f"min_checkout_seconds ({self.min_checkout_seconds}) cannot exceed "
                f"max_checkout_seconds ({self.max_checkout_seconds})"
            )
        return self


class OrderConfig(BaseModel):
    """Business configuration for the F006 order generator.

    Attributes:
        order_lead_seconds: Delay between a checkout completing and its order
            being created.
        confirmed_rate: Share of orders that reach ``CONFIRMED``.
        processing_rate: Share of orders that reach ``PROCESSING``. An order
            only reaches it after being confirmed, so this cannot exceed
            ``confirmed_rate``.
        min_confirm_minutes: Shortest wait from creation to confirmation.
        max_confirm_minutes: Longest wait from creation to confirmation.
        min_processing_minutes: Shortest wait from confirmation to processing.
        max_processing_minutes: Longest wait from confirmation to processing.
        order_number_prefix: Leading token of the business order number.
        batch_size: Rows generated per batch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_lead_seconds: int = Field(default=1, ge=1)
    confirmed_rate: float = Field(default=0.95, ge=0.0, le=1.0)
    processing_rate: float = Field(default=0.90, ge=0.0, le=1.0)
    min_confirm_minutes: int = Field(default=1, ge=1)
    max_confirm_minutes: int = Field(default=1_440, ge=1)
    min_processing_minutes: int = Field(default=30, ge=1)
    max_processing_minutes: int = Field(default=2_880, ge=1)
    order_number_prefix: str = Field(default="ORD", min_length=1, max_length=8)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_bounds(self) -> OrderConfig:
        """Ensure the lifecycle rates and waits are coherent."""
        if self.processing_rate > self.confirmed_rate:
            raise ValueError(
                f"processing_rate ({self.processing_rate}) cannot exceed "
                f"confirmed_rate ({self.confirmed_rate}): an order is only "
                "processed after it is confirmed"
            )
        if self.min_confirm_minutes > self.max_confirm_minutes:
            raise ValueError(
                f"min_confirm_minutes ({self.min_confirm_minutes}) cannot exceed "
                f"max_confirm_minutes ({self.max_confirm_minutes})"
            )
        if self.min_processing_minutes > self.max_processing_minutes:
            raise ValueError(
                f"min_processing_minutes ({self.min_processing_minutes}) cannot exceed "
                f"max_processing_minutes ({self.max_processing_minutes})"
            )
        return self


class PaymentConfig(BaseModel):
    """Business configuration for the F007 payment generator.

    Attributes:
        currency: ISO 4217 code recorded on every payment. Read from here
            rather than inferred from the order's geography.
        capture_rate: Share of payments authorised and then captured.
        void_rate: Share of payments authorised and then voided.
        failure_rate: Share of payments that fail outright.
        authorization_lead_seconds: Delay between an order being created and
            its payment being authorised.
        min_capture_minutes: Shortest wait from authorisation to capture.
        max_capture_minutes: Longest wait from authorisation to capture.
        min_void_minutes: Shortest wait from authorisation to voiding.
        max_void_minutes: Longest wait from authorisation to voiding.
        payment_reference_prefix: Leading token of the payment reference.
        batch_size: Rows generated per batch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    currency: str = Field(default="USD", min_length=3, max_length=3)
    capture_rate: float = Field(default=0.92, ge=0.0, le=1.0)
    void_rate: float = Field(default=0.03, ge=0.0, le=1.0)
    failure_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    authorization_lead_seconds: int = Field(default=1, ge=1)
    min_capture_minutes: int = Field(default=1, ge=1)
    max_capture_minutes: int = Field(default=180, ge=1)
    min_void_minutes: int = Field(default=5, ge=1)
    max_void_minutes: int = Field(default=1_440, ge=1)
    payment_reference_prefix: str = Field(default="PAY", min_length=1, max_length=8)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_bounds(self) -> PaymentConfig:
        """Ensure the outcome shares total one and no wait is inverted."""
        total = self.capture_rate + self.void_rate + self.failure_rate
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"capture_rate, void_rate and failure_rate must sum to 1.0, got {total}"
            )
        if self.min_capture_minutes > self.max_capture_minutes:
            raise ValueError(
                f"min_capture_minutes ({self.min_capture_minutes}) cannot exceed "
                f"max_capture_minutes ({self.max_capture_minutes})"
            )
        if self.min_void_minutes > self.max_void_minutes:
            raise ValueError(
                f"min_void_minutes ({self.min_void_minutes}) cannot exceed "
                f"max_void_minutes ({self.max_void_minutes})"
            )
        return self


class ShipmentConfig(BaseModel):
    """Business configuration for the F008 shipment generator.

    ``carriers`` and ``delivery_days`` are both keyed by shipping method, and
    both must cover every method exactly: the generator looks up each shipment
    by the method its checkout recorded, so a missing key would leave a
    shipment with no carrier to choose from.

    Attributes:
        carriers: Carriers available for each shipping method. One is chosen
            per shipment, so the method determines the candidates.
        delivery_days: Inclusive ``(min, max)`` day range promised for each
            shipping method.
        shipment_lead_seconds: Delay between a payment being captured and its
            shipment being created.
        delivered_rate: Share of shipments that reach ``DELIVERED``.
        in_transit_rate: Share that stop at ``IN_TRANSIT``.
        shipped_rate: Share that stop at ``SHIPPED``.
        min_pack_minutes: Shortest wait from creation to packing.
        max_pack_minutes: Longest wait from creation to packing.
        min_dispatch_minutes: Shortest wait from packing to dispatch.
        max_dispatch_minutes: Longest wait from packing to dispatch.
        min_transit_hours: Shortest wait from dispatch to being in transit.
        max_transit_hours: Longest wait from dispatch to being in transit.
        min_delivery_hours: Shortest wait from being in transit to delivery.
        max_delivery_hours: Longest wait from being in transit to delivery.
        shipment_number_prefix: Leading token of the business shipment number.
        tracking_number_prefix: Leading token of the tracking number.
        batch_size: Rows generated per batch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    carriers: dict[str, tuple[str, ...]] = Field(default_factory=lambda: dict(DEFAULT_CARRIERS))
    delivery_days: dict[str, tuple[int, int]] = Field(
        default_factory=lambda: dict(DEFAULT_DELIVERY_DAYS)
    )
    shipment_lead_seconds: int = Field(default=1, ge=1)
    delivered_rate: float = Field(default=0.90, ge=0.0, le=1.0)
    in_transit_rate: float = Field(default=0.07, ge=0.0, le=1.0)
    shipped_rate: float = Field(default=0.03, ge=0.0, le=1.0)
    min_pack_minutes: int = Field(default=30, ge=1)
    max_pack_minutes: int = Field(default=1_440, ge=1)
    min_dispatch_minutes: int = Field(default=60, ge=1)
    max_dispatch_minutes: int = Field(default=1_440, ge=1)
    min_transit_hours: int = Field(default=2, ge=1)
    max_transit_hours: int = Field(default=48, ge=1)
    min_delivery_hours: int = Field(default=4, ge=1)
    max_delivery_hours: int = Field(default=120, ge=1)
    shipment_number_prefix: str = Field(default="SHP", min_length=1, max_length=8)
    tracking_number_prefix: str = Field(default="TRK", min_length=1, max_length=8)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_bounds(self) -> ShipmentConfig:
        """Ensure the lifecycle rates, waits, and per-method tables cohere.

        Which shipping methods must appear is a domain question, so it is
        checked by the generator against the methods actually present in the
        data rather than here: the configuration layer deliberately knows
        nothing about the commerce enums.
        """
        for name, table in (("carriers", self.carriers), ("delivery_days", self.delivery_days)):
            if not table:
                raise ValueError(f"{name} must list at least one shipping method")

        for method, options in self.carriers.items():
            if not options:
                raise ValueError(f"carriers[{method!r}] must list at least one carrier")

        for method, (lowest, highest) in self.delivery_days.items():
            if lowest < 0:
                raise ValueError(f"delivery_days[{method!r}] cannot promise negative days")
            if lowest > highest:
                raise ValueError(
                    f"delivery_days[{method!r}] minimum ({lowest}) cannot exceed "
                    f"its maximum ({highest})"
                )

        total = self.delivered_rate + self.in_transit_rate + self.shipped_rate
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"delivered_rate, in_transit_rate and shipped_rate must sum to 1.0, got {total}"
            )

        for low_name, low, high_name, high in (
            ("min_pack_minutes", self.min_pack_minutes, "max_pack_minutes", self.max_pack_minutes),
            (
                "min_dispatch_minutes",
                self.min_dispatch_minutes,
                "max_dispatch_minutes",
                self.max_dispatch_minutes,
            ),
            (
                "min_transit_hours",
                self.min_transit_hours,
                "max_transit_hours",
                self.max_transit_hours,
            ),
            (
                "min_delivery_hours",
                self.min_delivery_hours,
                "max_delivery_hours",
                self.max_delivery_hours,
            ),
        ):
            if low > high:
                raise ValueError(f"{low_name} ({low}) cannot exceed {high_name} ({high})")
        return self


class ReturnConfig(BaseModel):
    """Business configuration for the F009 return generator.

    The reason vocabulary is deliberately not here: the specification requires
    it to come from ``return_reasons.parquet``, so the generator reads it from
    master data rather than from configuration.

    Attributes:
        return_rate: Share of eligible delivered shipments that are returned.
        refund_types: How a return is settled, mapped to its share. The shares
            must sum to one.
        min_request_days: Soonest a customer asks after taking delivery.
        max_request_days: Latest a customer asks after taking delivery.
        completed_rate: Share of returns that reach ``COMPLETED``.
        received_rate: Share that stop at ``RECEIVED``.
        in_transit_rate: Share that stop at ``IN_TRANSIT``.
        approved_rate: Share that stop at ``APPROVED``.
        min_approval_hours: Shortest wait from request to approval.
        max_approval_hours: Longest wait from request to approval.
        min_dispatch_hours: Shortest wait from approval to the customer
            sending the item back.
        max_dispatch_hours: Longest wait from approval to that dispatch.
        min_transit_hours: Shortest wait from dispatch to the warehouse
            receiving the item.
        max_transit_hours: Longest wait from dispatch to receipt.
        min_completion_hours: Shortest wait from receipt to completion.
        max_completion_hours: Longest wait from receipt to completion.
        return_number_prefix: Leading token of the business return number.
        batch_size: Rows generated per batch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    return_rate: float = Field(default=0.12, ge=0.0, le=1.0)
    refund_types: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_REFUND_TYPES))
    min_request_days: int = Field(default=1, ge=0)
    max_request_days: int = Field(default=21, ge=0)
    completed_rate: float = Field(default=0.85, ge=0.0, le=1.0)
    received_rate: float = Field(default=0.08, ge=0.0, le=1.0)
    in_transit_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    approved_rate: float = Field(default=0.02, ge=0.0, le=1.0)
    min_approval_hours: int = Field(default=2, ge=1)
    max_approval_hours: int = Field(default=72, ge=1)
    min_dispatch_hours: int = Field(default=4, ge=1)
    max_dispatch_hours: int = Field(default=120, ge=1)
    min_transit_hours: int = Field(default=24, ge=1)
    max_transit_hours: int = Field(default=168, ge=1)
    min_completion_hours: int = Field(default=2, ge=1)
    max_completion_hours: int = Field(default=96, ge=1)
    return_number_prefix: str = Field(default="RET", min_length=1, max_length=8)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_bounds(self) -> ReturnConfig:
        """Ensure the lifecycle rates, refund shares, and waits cohere."""
        if not self.refund_types:
            raise ValueError("refund_types must list at least one settlement type")
        for name, share in self.refund_types.items():
            if share < 0.0:
                raise ValueError(f"refund_types[{name!r}] cannot be negative")
        refund_total = sum(self.refund_types.values())
        if abs(refund_total - 1.0) > 1e-9:
            raise ValueError(f"refund_types shares must sum to 1.0, got {refund_total}")

        lifecycle_total = (
            self.completed_rate + self.received_rate + self.in_transit_rate + self.approved_rate
        )
        if abs(lifecycle_total - 1.0) > 1e-9:
            raise ValueError(
                "completed_rate, received_rate, in_transit_rate and approved_rate "
                f"must sum to 1.0, got {lifecycle_total}"
            )

        for low_name, low, high_name, high in (
            ("min_request_days", self.min_request_days, "max_request_days", self.max_request_days),
            (
                "min_approval_hours",
                self.min_approval_hours,
                "max_approval_hours",
                self.max_approval_hours,
            ),
            (
                "min_dispatch_hours",
                self.min_dispatch_hours,
                "max_dispatch_hours",
                self.max_dispatch_hours,
            ),
            (
                "min_transit_hours",
                self.min_transit_hours,
                "max_transit_hours",
                self.max_transit_hours,
            ),
            (
                "min_completion_hours",
                self.min_completion_hours,
                "max_completion_hours",
                self.max_completion_hours,
            ),
        ):
            if low > high:
                raise ValueError(f"{low_name} ({low}) cannot exceed {high_name} ({high})")
        return self


class ReviewConfig(BaseModel):
    """Business configuration for the F010 review generator.

    ``rating_weights``, ``titles`` and ``texts`` are all keyed by rating, and
    the titles and texts must cover every rating the weights can produce: the
    generator looks up the wording by the rating it drew, so a missing key
    would leave a review with nothing to say.

    Attributes:
        review_rate: Share of eligible delivered items that are reviewed.
        rating_weights: Star rating mapped to its share. The shares must sum
            to one.
        titles: Candidate titles for each rating.
        texts: Candidate one-sentence bodies for each rating.
        min_review_days: Soonest a customer writes after taking delivery.
        max_review_days: Latest a customer writes after taking delivery.
        review_number_prefix: Leading token of the business review number.
        batch_size: Rows generated per batch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    review_rate: float = Field(default=0.18, ge=0.0, le=1.0)
    rating_weights: dict[int, float] = Field(default_factory=lambda: dict(DEFAULT_RATING_WEIGHTS))
    titles: dict[int, tuple[str, ...]] = Field(default_factory=lambda: dict(DEFAULT_REVIEW_TITLES))
    texts: dict[int, tuple[str, ...]] = Field(default_factory=lambda: dict(DEFAULT_REVIEW_TEXTS))
    min_review_days: int = Field(default=1, ge=0)
    max_review_days: int = Field(default=30, ge=0)
    review_number_prefix: str = Field(default="REV", min_length=1, max_length=8)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_bounds(self) -> ReviewConfig:
        """Ensure the ratings, their wording, and the delay window cohere."""
        if not self.rating_weights:
            raise ValueError("rating_weights must list at least one rating")
        for rating, share in self.rating_weights.items():
            if not 1 <= rating <= 5:
                raise ValueError(f"rating_weights key {rating} is outside the 1-5 star range")
            if share < 0.0:
                raise ValueError(f"rating_weights[{rating}] cannot be negative")

        total = sum(self.rating_weights.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"rating_weights shares must sum to 1.0, got {total}")

        for name, table in (("titles", self.titles), ("texts", self.texts)):
            missing = sorted(set(self.rating_weights) - set(table))
            if missing:
                raise ValueError(
                    f"{name} must cover every rating in rating_weights. Missing: {missing}"
                )
            for rating, options in table.items():
                if not options:
                    raise ValueError(f"{name}[{rating}] must offer at least one phrase")

        if self.min_review_days > self.max_review_days:
            raise ValueError(
                f"min_review_days ({self.min_review_days}) cannot exceed "
                f"max_review_days ({self.max_review_days})"
            )
        return self


class SimulationConfig(BaseModel):
    """The complete configuration for a simulation run.

    Attributes:
        platform: Platform-level defaults.
        master_data: Master data generation settings.
        customers: Customer generation settings.
        journey: Customer journey generation settings.
        browsing: Category browsing and search settings.
        engagement: Product view and wishlist settings.
        commerce: Shopping cart settings.
        checkout: Checkout settings.
        orders: Order settings.
        payments: Payment settings.
        shipments: Shipment settings.
        returns: Return settings.
        reviews: Review settings.
        evolution: How much business one simulated day brings.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    platform: PlatformConfig = PlatformConfig()
    master_data: MasterDataConfig = MasterDataConfig()
    customers: CustomerConfig = CustomerConfig()
    journey: JourneyConfig = JourneyConfig()
    browsing: BrowsingConfig = BrowsingConfig()
    engagement: EngagementConfig = EngagementConfig()
    commerce: CommerceConfig = CommerceConfig()
    checkout: CheckoutConfig = CheckoutConfig()
    orders: OrderConfig = OrderConfig()
    payments: PaymentConfig = PaymentConfig()
    shipments: ShipmentConfig = ShipmentConfig()
    returns: ReturnConfig = ReturnConfig()
    reviews: ReviewConfig = ReviewConfig()
    evolution: EvolutionConfig = EvolutionConfig()


def load_master_data_config(config_dir: Path | None = None) -> MasterDataConfig:
    """Load master data settings from ``master_data.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated master data configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (_retail_config_dir(config_dir)) / MASTER_DATA_CONFIG_FILE
    return build_model(MasterDataConfig, read_yaml_mapping(path), path)


def load_customer_config(config_dir: Path | None = None) -> CustomerConfig:
    """Load customer settings from ``customers.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated customer configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (_retail_config_dir(config_dir)) / CUSTOMER_CONFIG_FILE
    return build_model(CustomerConfig, read_yaml_mapping(path), path)


def load_journey_config(config_dir: Path | None = None) -> JourneyConfig:
    """Load journey settings from ``journey.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated journey configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (_retail_config_dir(config_dir)) / JOURNEY_CONFIG_FILE
    return build_model(JourneyConfig, read_yaml_mapping(path), path)


def load_browsing_config(config_dir: Path | None = None) -> BrowsingConfig:
    """Load browsing settings from ``browsing.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated browsing configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (_retail_config_dir(config_dir)) / BROWSING_CONFIG_FILE
    return build_model(BrowsingConfig, read_yaml_mapping(path), path)


def load_engagement_config(config_dir: Path | None = None) -> EngagementConfig:
    """Load engagement settings from ``engagement.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated engagement configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (_retail_config_dir(config_dir)) / ENGAGEMENT_CONFIG_FILE
    return build_model(EngagementConfig, read_yaml_mapping(path), path)


def load_commerce_config(config_dir: Path | None = None) -> CommerceConfig:
    """Load commerce settings from ``commerce.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated commerce configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (_retail_config_dir(config_dir)) / COMMERCE_CONFIG_FILE
    return build_model(CommerceConfig, read_yaml_mapping(path), path)


def load_checkout_config(config_dir: Path | None = None) -> CheckoutConfig:
    """Load checkout settings from ``checkout.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated checkout configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (_retail_config_dir(config_dir)) / CHECKOUT_CONFIG_FILE
    return build_model(CheckoutConfig, read_yaml_mapping(path), path)


def load_order_config(config_dir: Path | None = None) -> OrderConfig:
    """Load order settings from ``orders.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated order configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (_retail_config_dir(config_dir)) / ORDER_CONFIG_FILE
    return build_model(OrderConfig, read_yaml_mapping(path), path)


def load_payment_config(config_dir: Path | None = None) -> PaymentConfig:
    """Load payment settings from ``payments.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated payment configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (_retail_config_dir(config_dir)) / PAYMENT_CONFIG_FILE
    return build_model(PaymentConfig, read_yaml_mapping(path), path)


def load_shipment_config(config_dir: Path | None = None) -> ShipmentConfig:
    """Load shipment settings from ``shipments.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated shipment configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (_retail_config_dir(config_dir)) / SHIPMENT_CONFIG_FILE
    return build_model(ShipmentConfig, read_yaml_mapping(path), path)


def load_return_config(config_dir: Path | None = None) -> ReturnConfig:
    """Load return settings from ``returns.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated return configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (_retail_config_dir(config_dir)) / RETURN_CONFIG_FILE
    return build_model(ReturnConfig, read_yaml_mapping(path), path)


def load_review_config(config_dir: Path | None = None) -> ReviewConfig:
    """Load review settings from ``reviews.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated review configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (_retail_config_dir(config_dir)) / REVIEW_CONFIG_FILE
    return build_model(ReviewConfig, read_yaml_mapping(path), path)


def load_evolution_config(config_dir: Path | None = None) -> EvolutionConfig:
    """Load daily evolution settings from ``evolution.yaml``.

    The only loader that tolerates a missing file. Every other configuration
    file describes something the generators cannot run without; this one
    describes how a day changes an enterprise, and a configuration directory
    written before Retail could evolve has no opinion about that. Defaulting
    rather than failing means such a directory still loads and still produces
    exactly what it always did.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated evolution configuration, or the defaults if the file is
        absent.

    Raises:
        ConfigError: If the file exists but is invalid.
    """
    path = (_retail_config_dir(config_dir)) / EVOLUTION_CONFIG_FILE
    if not path.is_file():
        return EvolutionConfig()
    return build_model(EvolutionConfig, read_yaml_mapping(path), path)


def load_config(config_dir: Path | None = None) -> SimulationConfig:
    """Load the complete simulation configuration.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated configuration for a run.

    Raises:
        ConfigError: If any file is missing or invalid.
    """
    return SimulationConfig(
        platform=load_platform_config(config_dir),
        master_data=load_master_data_config(config_dir),
        customers=load_customer_config(config_dir),
        journey=load_journey_config(config_dir),
        browsing=load_browsing_config(config_dir),
        engagement=load_engagement_config(config_dir),
        commerce=load_commerce_config(config_dir),
        checkout=load_checkout_config(config_dir),
        orders=load_order_config(config_dir),
        payments=load_payment_config(config_dir),
        shipments=load_shipment_config(config_dir),
        returns=load_return_config(config_dir),
        reviews=load_review_config(config_dir),
        evolution=load_evolution_config(config_dir),
    )




