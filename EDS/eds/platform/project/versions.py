"""Explicit version ownership.

Three versions move independently, and conflating any two of them is how a
platform ends up unable to say whether it can read its own files.

``PLATFORM_CONTRACT_VERSION``
    Owned by :mod:`eds.platform.metadata`. Versions the *domain and adapter
    contracts* - what a domain or adapter must implement. Recorded in a
    manifest so a project can say which contract it was built against.

``MANIFEST_VERSION``
    Versions the *shape of the manifest document*. Changes when a field is
    added, removed or reinterpreted.

``STATE_VERSION``
    Versions the *shape of the state document*. Changes far more often than
    the manifest, because state grows as runtime features arrive - which is
    precisely why it must not share the manifest's number.

The distribution version (``eds.version.__version__``) is deliberately *not* a
compatibility gate. It is recorded for provenance so a human can tell which
build produced a project, but semantic versioning of a distribution says
nothing reliable about document compatibility.

Migration is a non-goal, so compatibility is exact-match. That is deliberately
strict: silently reading an older document by guessing at its missing fields is
how corruption becomes invisible.
"""

from __future__ import annotations

from typing import Final

from eds.platform.project.errors import UnsupportedVersionError

__all__ = ["MANIFEST_VERSION", "STATE_VERSION", "require_supported_version"]

#: Shape of the manifest document.
MANIFEST_VERSION: Final[int] = 1

#: Shape of the state document.
STATE_VERSION: Final[int] = 1


def require_supported_version(document: str, found: int, supported: int) -> None:
    """Check that a stored document's version is one this platform can read.

    Args:
        document: What is being checked, for the message - ``"manifest"``.
        found: The version recorded in the document.
        supported: The version this platform understands.

    Raises:
        UnsupportedVersionError: If the versions differ. The message
            distinguishes a document from the future, which cannot be
            understood, from one from the past, which would need a migration
            that is not implemented.
    """
    if found == supported:
        return
    if found > supported:
        raise UnsupportedVersionError(
            f"{document} version {found} was written by a newer platform; "
            f"this platform understands version {supported}. Upgrade to read this project."
        )
    raise UnsupportedVersionError(
        f"{document} version {found} predates this platform's version {supported}, "
        "and project migration is not implemented."
    )
