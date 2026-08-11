"""Connector registry — maps a ``kind`` name to its implementation class.

This is the single lookup table that the loader uses at runtime.  Connectors
self-register by calling :func:`register_connector` at import time; the
registry itself is just a plain dict.

**Step 2 ships with an empty registry.**  Each subsequent build step adds its
connector file and calls ``register_connector(...)`` once, at module level.
No changes to this file are required when a new connector arrives.

Lookup behaviour
----------------
- Unknown ``kind`` → :exc:`~eds_loader.exceptions.ConnectorNotFoundError`
  with the list of all registered kinds.
- Known ``kind`` whose Python driver is not installed →
  :exc:`~eds_loader.exceptions.ConnectorNotInstalledError` with the exact
  ``pip install eds-loader[<extra>]`` command.
- Everything present → the connector class is instantiated and returned.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any

from eds_loader.exceptions import ConnectorNotFoundError, ConnectorNotInstalledError

__all__ = [
    "ConnectorSpec",
    "CONNECTORS",
    "register_connector",
    "get_connector",
    "list_connectors",
]


@dataclass
class ConnectorSpec:
    """Everything the registry needs to know about one connector.

    Attributes:
        connector_class: The class to instantiate.  ``None`` means the
            connector is planned but not yet implemented.
        required_packages: Top-level package names that must be importable
            for this connector to work.  Checked at lookup time so the
            error is immediate and human-readable.
        install_extra: The ``pip install eds-loader[<extra>]`` suffix the
            user needs if a required package is missing.
        can_read: Whether this connector implements :class:`~eds_loader.connectors.base.Readable`.
        can_write: Whether this connector implements :class:`~eds_loader.connectors.base.Writable`.
        description: One-line description shown by ``eds-loader connectors``.
    """

    connector_class: type | None
    required_packages: list[str] = field(default_factory=list)
    install_extra: str = ""
    can_read: bool = False
    can_write: bool = False
    description: str = ""


#: Central registry.  Populated by :func:`register_connector` calls in each
#: connector module.  Empty until connectors are added (Steps 3–9).
CONNECTORS: dict[str, ConnectorSpec] = {}


def register_connector(kind: str, spec: ConnectorSpec) -> None:
    """Add or replace a connector in the global registry.

    Called once per connector file, at module level, so the connector
    becomes available as soon as its module is imported.

    If a connector with *kind* is already registered and its
    ``connector_class`` is non-``None`` (i.e. fully implemented), the
    existing registration wins.  This prevents stale system-installed
    packages from clobbering a newer editable install or vice-versa.

    Args:
        kind: Short identifier used in config YAML (e.g. ``"local_fs"``,
            ``"postgres"``).
        spec: Complete specification for this connector.
    """
    existing = CONNECTORS.get(kind)
    if existing is not None and existing.connector_class is not None:
        # Already registered with a working implementation — keep it.
        return
    CONNECTORS[kind] = spec


def _is_package_available(package: str) -> bool:
    """Return ``True`` if *package* can be imported from the current environment.

    Handles both import-style names (``"azure.storage.blob"``) and PyPI
    distribution names with hyphens (``"azure-storage-blob"``).  Hyphens are
    converted to underscores and the result is tried as an import; if that
    fails, the original string is also attempted.
    """
    # Try the name as-is first (covers dotted paths like "azure.storage.blob")
    try:
        importlib.import_module(package)
        return True
    except (ImportError, ModuleNotFoundError):
        pass

    # Normalise hyphens → underscores and retry
    normalised = package.replace("-", "_")
    if normalised != package:
        try:
            importlib.import_module(normalised)
            return True
        except (ImportError, ModuleNotFoundError):
            pass

    return False


def get_connector(kind: str, raw_config: dict[str, Any]) -> Any:
    """Look up and instantiate a connector.

    Args:
        kind: The ``kind`` value from the config section (``source.kind``
            or ``target.kind``).
        raw_config: All config fields for this connector *except* ``kind``,
            passed to the connector class as keyword arguments.

    Returns:
        An instantiated connector.  Depending on its :class:`~eds_loader.connectors.registry.ConnectorSpec`,
        it may implement :class:`~eds_loader.connectors.base.Readable`,
        :class:`~eds_loader.connectors.base.Writable`, or both.

    Raises:
        ~eds_loader.exceptions.ConnectorNotFoundError: If *kind* is not in
            the registry.
        ~eds_loader.exceptions.ConnectorNotInstalledError: If any of the
            connector's :attr:`~ConnectorSpec.required_packages` are absent.
    """
    if kind not in CONNECTORS:
        raise ConnectorNotFoundError(kind=kind, available=list(CONNECTORS))

    spec = CONNECTORS[kind]

    missing = [pkg for pkg in spec.required_packages if not _is_package_available(pkg)]
    if missing:
        raise ConnectorNotInstalledError(
            kind=kind,
            install_extra=spec.install_extra,
            missing_packages=missing,
        )

    if spec.connector_class is None:
        # Connector is registered (known) but implementation not shipped yet.
        raise ConnectorNotInstalledError(
            kind=kind,
            install_extra=spec.install_extra,
            missing_packages=spec.required_packages or [f"eds-loader[{spec.install_extra}]"],
        )

    return spec.connector_class(**raw_config)


def list_connectors() -> dict[str, ConnectorSpec]:
    """Return a snapshot of every registered connector, keyed by kind.

    The returned dict is a shallow copy — mutations do not affect the
    registry.
    """
    return dict(CONNECTORS)
