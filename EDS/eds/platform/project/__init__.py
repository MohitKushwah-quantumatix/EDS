"""The simulation project: a durable home for one simulated enterprise.

A project is what makes an enterprise simulation resumable. It owns identity -
who this enterprise is, which domain it simulates, which seed reproduces it -
and it owns the durable state that says how far it has got.

**Nothing here executes anything.** The project stores a simulated date; it
never advances one. It stores which stages completed; it never decides that one
did. It provides the home that a clock, a scheduler and a growth engine will
write into when they arrive (PADR-004, PADR-009).

State belongs to the platform, never to a domain. A domain declares what it
generates and how; whether a particular enterprise has generated it yet is not
the domain's business, and no domain imports this package.
"""

from eds.platform.project.errors import (
    CorruptDocumentError,
    ProjectError,
    ProjectExistsError,
    ProjectIssue,
    ProjectNotFoundError,
    ProjectValidationError,
    StateStoreError,
    UnsupportedVersionError,
)
from eds.platform.project.manifest import MANIFEST_KEY, ProjectManifest
from eds.platform.project.project import Project, create_project, open_project
from eds.platform.project.state import STATE_KEY, SimulationState
from eds.platform.project.store import Document, FileStateStore, StateStore
from eds.platform.project.versions import (
    MANIFEST_VERSION,
    STATE_VERSION,
    require_supported_version,
)
from eds.platform.project.workspace import (
    DATA_DIRECTORY,
    LOGS_DIRECTORY,
    SNAPSHOTS_DIRECTORY,
    Workspace,
)

__all__ = [
    "DATA_DIRECTORY",
    "LOGS_DIRECTORY",
    "MANIFEST_KEY",
    "MANIFEST_VERSION",
    "SNAPSHOTS_DIRECTORY",
    "STATE_KEY",
    "STATE_VERSION",
    "CorruptDocumentError",
    "Document",
    "FileStateStore",
    "Project",
    "ProjectError",
    "ProjectExistsError",
    "ProjectIssue",
    "ProjectManifest",
    "ProjectNotFoundError",
    "ProjectValidationError",
    "SimulationState",
    "StateStore",
    "StateStoreError",
    "UnsupportedVersionError",
    "Workspace",
    "create_project",
    "open_project",
    "require_supported_version",
]
