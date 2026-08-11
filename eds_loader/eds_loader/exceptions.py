"""Custom exceptions for eds_loader.

Every exception raised by the loader inherits from :exc:`LoaderError` so a
caller can catch "anything the loader can fail with" with a single except
clause, or catch a specific subclass for targeted handling.

The two most important subclasses for end-users are:

- :exc:`ConnectorNotInstalledError` — always includes the exact
  ``pip install eds-loader[<extra>]`` command needed to fix the problem.
- :exc:`ConfigError` — always describes the offending field so the user
  can fix the YAML without guessing.
"""

from __future__ import annotations

__all__ = [
    "LoaderError",
    "ConfigError",
    "ConnectorNotFoundError",
    "ConnectorNotInstalledError",
    "LoadError",
]


class LoaderError(RuntimeError):
    """Base class for all eds_loader errors.

    Catch this to handle any loader failure without importing connector-
    specific exception types.
    """


class ConfigError(LoaderError):
    """Raised when the loader configuration is invalid or unreadable.

    Examples: missing required field, bad YAML syntax, unknown table name.
    """


class ConnectorNotFoundError(LoaderError):
    """Raised when no connector is registered for the requested kind.

    Args:
        kind: The unrecognised ``kind`` value from the config.
        available: Every kind currently in the registry.
    """

    def __init__(self, kind: str, available: list[str]) -> None:
        self.kind = kind
        self.available = available
        known = ", ".join(sorted(available)) if available else "(none registered yet)"
        super().__init__(
            f"Unknown connector kind {kind!r}.\n"
            f"Known connectors: {known}.\n"
            f"Run `eds-loader connectors` to see install status."
        )


class ConnectorNotInstalledError(LoaderError):
    """Raised when a connector is known but its driver package is not installed.

    The error message always includes the exact ``pip install`` command so
    the user can fix it immediately.

    Args:
        kind: The connector kind whose driver is missing.
        install_extra: The ``eds-loader[<extra>]`` name.
        missing_packages: Package names that could not be imported.
    """

    def __init__(
        self,
        kind: str,
        install_extra: str,
        missing_packages: list[str],
    ) -> None:
        self.kind = kind
        self.install_extra = install_extra
        self.missing_packages = missing_packages
        super().__init__(
            f"Connector {kind!r} requires packages that are not installed: "
            f"{', '.join(missing_packages)}.\n"
            f"Fix: pip install eds-loader[{install_extra}]"
        )


class LoadError(LoaderError):
    """Raised when data cannot be read from the source or written to the target.

    Connectors raise this (or a subclass) for runtime I/O failures — network
    errors, permission denied, schema mismatches, etc.
    """
