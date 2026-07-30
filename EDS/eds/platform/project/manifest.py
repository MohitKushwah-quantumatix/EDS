"""The project manifest: a simulated enterprise's durable identity.

Everything here is set when a project is created and never changes afterwards.
That is the point of the split from :class:`~eds.platform.project.state.SimulationState`:
identity is what makes two runs the *same* project, so a field that can change
during a run does not belong here.

The seed lives here rather than in state for exactly that reason. Reproducing a
project means running it with the seed it was created with; a seed that could
be edited between runs would make "the same project" meaningless.

There is no separate ``ProjectMetadata``. A manifest is metadata plus the
version of the document carrying it, and splitting one dataclass into two that
always travel together adds a name without adding a distinction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from eds.platform.metadata import PLATFORM_CONTRACT_VERSION
from eds.platform.project.errors import CorruptDocumentError
from eds.platform.project.store import Document
from eds.platform.project.versions import MANIFEST_VERSION, require_supported_version
from eds.version import __version__

__all__ = ["MANIFEST_KEY", "ProjectManifest"]

#: Logical document key the manifest is stored under.
MANIFEST_KEY = "manifest"


@dataclass(frozen=True, slots=True)
class ProjectManifest:
    """The immutable identity of one simulated enterprise.

    Attributes:
        project_id: Stable unique identifier, assigned at creation.
        name: Human-readable project name.
        domain: Name of the domain being simulated, such as ``"retail"``.
        seed: The run seed. ``None`` means the project was created without one
            and is not reproducible.
        created_at: When the project was created, timezone-aware.
        platform_version: Distribution version that created it. Provenance
            only - never a compatibility gate.
        platform_contract_version: Domain and adapter contract version the
            project was built against.
        manifest_version: Shape of this document.
    """

    project_id: str
    name: str
    domain: str
    seed: int | None
    created_at: datetime
    platform_version: str = __version__
    platform_contract_version: int = PLATFORM_CONTRACT_VERSION
    manifest_version: int = MANIFEST_VERSION

    def __post_init__(self) -> None:
        """Reject a manifest that could not identify a project.

        Raises:
            ValueError: If the identifier, name or domain is empty, or if
                ``created_at`` carries no timezone. A naive timestamp cannot be
                compared across machines, and a project outlives the machine
                that created it.
        """
        for field, value in (
            ("project_id", self.project_id),
            ("name", self.name),
            ("domain", self.domain),
        ):
            if not value.strip():
                raise ValueError(f"manifest {field} must not be empty")
        if self.created_at.tzinfo is None:
            raise ValueError("manifest created_at must be timezone-aware")

    def to_document(self) -> dict[str, Any]:
        """Render the manifest as a storable document.

        Returns:
            A plain mapping of primitives, with the timestamp in ISO 8601.
        """
        return {
            "project_id": self.project_id,
            "name": self.name,
            "domain": self.domain,
            "seed": self.seed,
            "created_at": self.created_at.isoformat(),
            "platform_version": self.platform_version,
            "platform_contract_version": self.platform_contract_version,
            "manifest_version": self.manifest_version,
        }

    @classmethod
    def from_document(cls, document: Document) -> ProjectManifest:
        """Rebuild a manifest from a stored document.

        Args:
            document: The stored document.

        Returns:
            The manifest.

        Raises:
            CorruptDocumentError: If a required field is absent or malformed.
            UnsupportedVersionError: If the manifest version is one this
                platform cannot read.
        """
        version = _require_int(document, "manifest_version")
        require_supported_version("manifest", version, MANIFEST_VERSION)

        contract = _require_int(document, "platform_contract_version")
        if contract > PLATFORM_CONTRACT_VERSION:
            raise CorruptDocumentError(
                f"project was built against platform contract {contract}; "
                f"this platform implements contract {PLATFORM_CONTRACT_VERSION}"
            )

        raw_created = _require_str(document, "created_at")
        try:
            created_at = datetime.fromisoformat(raw_created)
        except ValueError as exc:
            raise CorruptDocumentError(
                f"manifest created_at {raw_created!r} is not ISO 8601"
            ) from exc
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)

        seed = document.get("seed")
        if seed is not None and not isinstance(seed, int):
            raise CorruptDocumentError(
                f"manifest seed must be an integer or absent, found {seed!r}"
            )

        try:
            return cls(
                project_id=_require_str(document, "project_id"),
                name=_require_str(document, "name"),
                domain=_require_str(document, "domain"),
                seed=seed,
                created_at=created_at,
                platform_version=_require_str(document, "platform_version"),
                platform_contract_version=contract,
                manifest_version=version,
            )
        except ValueError as exc:
            raise CorruptDocumentError(f"manifest is not valid: {exc}") from exc


def _require_str(document: Document, field: str) -> str:
    """Read a required string field from a document.

    Args:
        document: The stored document.
        field: Field name.

    Returns:
        The value.

    Raises:
        CorruptDocumentError: If the field is absent or not a string.
    """
    value = document.get(field)
    if not isinstance(value, str):
        raise CorruptDocumentError(f"manifest field {field!r} must be a string, found {value!r}")
    return value


def _require_int(document: Document, field: str) -> int:
    """Read a required integer field from a document.

    Args:
        document: The stored document.
        field: Field name.

    Returns:
        The value.

    Raises:
        CorruptDocumentError: If the field is absent or not an integer.
    """
    value = document.get(field)
    # bool is an int in Python; a version that is True is a corrupt document.
    if not isinstance(value, int) or isinstance(value, bool):
        raise CorruptDocumentError(f"manifest field {field!r} must be an integer, found {value!r}")
    return value
