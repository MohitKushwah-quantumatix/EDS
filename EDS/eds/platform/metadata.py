"""Platform identity.

Kept apart from :mod:`eds.version` deliberately: the package version tracks the
distribution, while the platform contract version tracks the shape a domain or
adapter must conform to. They move at different rates once a second domain
exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from eds.version import __version__

__all__ = ["PLATFORM_CONTRACT_VERSION", "PLATFORM_NAME", "PlatformMetadata", "platform_metadata"]

#: Human-readable platform name.
PLATFORM_NAME: Final[str] = "Enterprise Data Simulator"

#: Version of the domain and adapter contracts, not of the distribution. A
#: domain written against contract 1 keeps working until this major changes.
PLATFORM_CONTRACT_VERSION: Final[int] = 1


@dataclass(frozen=True, slots=True)
class PlatformMetadata:
    """Static facts about the running platform.

    Attributes:
        name: Human-readable platform name.
        version: Distribution version, from :mod:`eds.version`.
        contract_version: Version of the domain and adapter contracts.
    """

    name: str
    version: str
    contract_version: int


def platform_metadata() -> PlatformMetadata:
    """Return the metadata of the running platform.

    Returns:
        The platform name, distribution version, and contract version.
    """
    return PlatformMetadata(
        name=PLATFORM_NAME,
        version=__version__,
        contract_version=PLATFORM_CONTRACT_VERSION,
    )
