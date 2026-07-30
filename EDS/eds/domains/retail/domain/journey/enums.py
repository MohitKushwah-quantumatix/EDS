"""Enumerations for the customer journey domain.

These cover the persona catalogue and the technical and marketing attributes
recorded on a browsing session. They live beside the journey schema so F003.1
adds no risk to the master data or customer features.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "Browser",
    "DeviceType",
    "EntryMethod",
    "ExitPage",
    "LandingPage",
    "OperatingSystem",
    "PersonaName",
    "TrafficSource",
    "ViewSource",
]


class PersonaName(StrEnum):
    """The behavioural persona assigned to a customer."""

    WINDOW_SHOPPER = "WINDOW_SHOPPER"
    RESEARCHER = "RESEARCHER"
    BARGAIN_HUNTER = "BARGAIN_HUNTER"
    LOYAL_CUSTOMER = "LOYAL_CUSTOMER"
    IMPULSE_BUYER = "IMPULSE_BUYER"
    SEASONAL_SHOPPER = "SEASONAL_SHOPPER"


class DeviceType(StrEnum):
    """Device class a session was opened on."""

    MOBILE = "MOBILE"
    DESKTOP = "DESKTOP"
    TABLET = "TABLET"


class Browser(StrEnum):
    """Browser a session was opened in."""

    CHROME = "CHROME"
    EDGE = "EDGE"
    SAFARI = "SAFARI"
    FIREFOX = "FIREFOX"
    OPERA = "OPERA"


class OperatingSystem(StrEnum):
    """Operating system the session's device runs."""

    ANDROID = "ANDROID"
    IOS = "IOS"
    WINDOWS = "WINDOWS"
    MACOS = "MACOS"
    LINUX = "LINUX"


class TrafficSource(StrEnum):
    """Channel that brought the visitor to the site."""

    ORGANIC_SEARCH = "ORGANIC_SEARCH"
    PAID_SEARCH = "PAID_SEARCH"
    REFERRAL = "REFERRAL"
    DIRECT = "DIRECT"
    EMAIL_CAMPAIGN = "EMAIL_CAMPAIGN"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    DISPLAY_ADS = "DISPLAY_ADS"


class LandingPage(StrEnum):
    """Page type a session started on."""

    HOMEPAGE = "HOMEPAGE"
    CATEGORY = "CATEGORY"
    SEARCH = "SEARCH"
    PROMOTION = "PROMOTION"
    BRAND = "BRAND"
    CAMPAIGN = "CAMPAIGN"


class ExitPage(StrEnum):
    """Page type a session ended on."""

    HOMEPAGE = "HOMEPAGE"
    CATEGORY = "CATEGORY"
    PRODUCT = "PRODUCT"
    SEARCH = "SEARCH"
    PROMOTION = "PROMOTION"


class EntryMethod(StrEnum):
    """How a visitor arrived at a category page."""

    HOMEPAGE = "HOMEPAGE"
    NAVIGATION_MENU = "NAVIGATION_MENU"
    PROMOTION_BANNER = "PROMOTION_BANNER"
    SEARCH_RESULT = "SEARCH_RESULT"
    RECOMMENDATION = "RECOMMENDATION"
    BRAND_PAGE = "BRAND_PAGE"


class ViewSource(StrEnum):
    """What led the visitor to open a product page."""

    CATEGORY = "CATEGORY"
    SEARCH = "SEARCH"
    RECOMMENDATION = "RECOMMENDATION"
    PROMOTION = "PROMOTION"
    BRAND_PAGE = "BRAND_PAGE"
