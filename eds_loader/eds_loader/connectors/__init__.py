"""eds_loader.connectors — public surface of the connector sub-package."""

from __future__ import annotations

from eds_loader.connectors.base import Readable, Writable, WriteResult
from eds_loader.connectors.registry import (
    CONNECTORS,
    ConnectorSpec,
    get_connector,
    list_connectors,
    register_connector,
)

__all__ = [
    "Readable",
    "Writable",
    "WriteResult",
    "ConnectorSpec",
    "CONNECTORS",
    "register_connector",
    "get_connector",
    "list_connectors",
]
