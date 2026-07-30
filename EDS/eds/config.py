"""Backward-compatible alias for the pre-platform configuration module.

Configuration is now split along the platform boundary (PADR-002):

* :mod:`eds.core.config` owns the domain-independent machinery - the YAML
  helpers and ``ConfigError``.
* :mod:`eds.platform.config` owns ``PlatformConfig``, the run-level settings.
* :mod:`eds.domains.retail.config` owns every Retail settings model and
  loader.

This module re-exports all three under their original names so that code
written against the old flat layout keeps working unchanged (PADR-005). New
code should import from whichever of the two modules actually owns the name.
"""

from __future__ import annotations

from eds.core.config import (
    DEFAULT_CONFIG_DIR as DEFAULT_CONFIG_DIR,
)
from eds.core.config import (
    ConfigError as ConfigError,
)
from eds.core.config import (
    build_model as build_model,
)
from eds.core.config import (
    read_yaml_mapping as read_yaml_mapping,
)
from eds.domains.retail.config import (
    BROWSING_CONFIG_FILE as BROWSING_CONFIG_FILE,
)
from eds.domains.retail.config import (
    CHECKOUT_CONFIG_FILE as CHECKOUT_CONFIG_FILE,
)
from eds.domains.retail.config import (
    COMMERCE_CONFIG_FILE as COMMERCE_CONFIG_FILE,
)
from eds.domains.retail.config import (
    CUSTOMER_CONFIG_FILE as CUSTOMER_CONFIG_FILE,
)
from eds.domains.retail.config import (
    DEFAULT_CARRIERS as DEFAULT_CARRIERS,
)
from eds.domains.retail.config import (
    DEFAULT_DELIVERY_DAYS as DEFAULT_DELIVERY_DAYS,
)
from eds.domains.retail.config import (
    DEFAULT_RATING_WEIGHTS as DEFAULT_RATING_WEIGHTS,
)
from eds.domains.retail.config import (
    DEFAULT_REFUND_TYPES as DEFAULT_REFUND_TYPES,
)
from eds.domains.retail.config import (
    DEFAULT_REVIEW_TEXTS as DEFAULT_REVIEW_TEXTS,
)
from eds.domains.retail.config import (
    DEFAULT_REVIEW_TITLES as DEFAULT_REVIEW_TITLES,
)
from eds.domains.retail.config import (
    ENGAGEMENT_CONFIG_FILE as ENGAGEMENT_CONFIG_FILE,
)
from eds.domains.retail.config import (
    EVOLUTION_CONFIG_FILE as EVOLUTION_CONFIG_FILE,
)
from eds.domains.retail.config import (
    JOURNEY_CONFIG_FILE as JOURNEY_CONFIG_FILE,
)
from eds.domains.retail.config import (
    MASTER_DATA_CONFIG_FILE as MASTER_DATA_CONFIG_FILE,
)
from eds.domains.retail.config import (
    ORDER_CONFIG_FILE as ORDER_CONFIG_FILE,
)
from eds.domains.retail.config import (
    PAYMENT_CONFIG_FILE as PAYMENT_CONFIG_FILE,
)
from eds.domains.retail.config import (
    RETURN_CONFIG_FILE as RETURN_CONFIG_FILE,
)
from eds.domains.retail.config import (
    REVIEW_CONFIG_FILE as REVIEW_CONFIG_FILE,
)
from eds.domains.retail.config import (
    SHIPMENT_CONFIG_FILE as SHIPMENT_CONFIG_FILE,
)
from eds.domains.retail.config import (
    BrowsingConfig as BrowsingConfig,
)
from eds.domains.retail.config import (
    CheckoutConfig as CheckoutConfig,
)
from eds.domains.retail.config import (
    CommerceConfig as CommerceConfig,
)
from eds.domains.retail.config import (
    CustomerConfig as CustomerConfig,
)
from eds.domains.retail.config import (
    EngagementConfig as EngagementConfig,
)
from eds.domains.retail.config import (
    EvolutionConfig as EvolutionConfig,
)
from eds.domains.retail.config import (
    JourneyConfig as JourneyConfig,
)
from eds.domains.retail.config import (
    MasterDataConfig as MasterDataConfig,
)
from eds.domains.retail.config import (
    OrderConfig as OrderConfig,
)
from eds.domains.retail.config import (
    PaymentConfig as PaymentConfig,
)
from eds.domains.retail.config import (
    ReturnConfig as ReturnConfig,
)
from eds.domains.retail.config import (
    ReviewConfig as ReviewConfig,
)
from eds.domains.retail.config import (
    ShipmentConfig as ShipmentConfig,
)
from eds.domains.retail.config import (
    SimulationConfig as SimulationConfig,
)
from eds.domains.retail.config import (
    load_browsing_config as load_browsing_config,
)
from eds.domains.retail.config import (
    load_checkout_config as load_checkout_config,
)
from eds.domains.retail.config import (
    load_commerce_config as load_commerce_config,
)
from eds.domains.retail.config import (
    load_config as load_config,
)
from eds.domains.retail.config import (
    load_customer_config as load_customer_config,
)
from eds.domains.retail.config import (
    load_engagement_config as load_engagement_config,
)
from eds.domains.retail.config import (
    load_evolution_config as load_evolution_config,
)
from eds.domains.retail.config import (
    load_journey_config as load_journey_config,
)
from eds.domains.retail.config import (
    load_master_data_config as load_master_data_config,
)
from eds.domains.retail.config import (
    load_order_config as load_order_config,
)
from eds.domains.retail.config import (
    load_payment_config as load_payment_config,
)
from eds.domains.retail.config import (
    load_return_config as load_return_config,
)
from eds.domains.retail.config import (
    load_review_config as load_review_config,
)
from eds.domains.retail.config import (
    load_shipment_config as load_shipment_config,
)
from eds.platform.config import (
    PLATFORM_CONFIG_FILE as PLATFORM_CONFIG_FILE,
)
from eds.platform.config import (
    PlatformConfig as PlatformConfig,
)
from eds.platform.config import (
    load_platform_config as load_platform_config,
)
