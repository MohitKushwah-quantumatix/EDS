"""The project handle.

A :class:`Project` binds the three things needed to work with one simulated
enterprise: its identity (the manifest), where its data lives (the workspace),
and how its documents persist (the store). It is a handle, not a document -
holding one means a project exists and its manifest was readable.

**No runtime.** The project reads and writes state; it never interprets it. It
does not advance a date, decide that a stage completed, run a generator or
touch an adapter. Those belong to components that do not exist yet, and the
project exists so that when they do arrive they have somewhere to put what they
learn.

This supersedes the placeholder :class:`Project` P001 declared, which held
``name``, ``domain``, ``seed`` and ``output_directory`` and had no consumer.
PADR-007 deferred its real shape until something needed it; this module is that
something.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from eds.platform.domain import SimulationDomain, get_domain, list_domains
from eds.platform.metadata import PlatformMetadata, platform_metadata
from eds.platform.project.errors import (
    ProjectExistsError,
    ProjectIssue,
    ProjectNotFoundError,
    ProjectValidationError,
)
from eds.platform.project.manifest import MANIFEST_KEY, ProjectManifest
from eds.platform.project.state import STATE_KEY, SimulationState
from eds.platform.project.store import FileStateStore, StateStore
from eds.platform.project.workspace import Workspace

__all__ = ["Project", "create_project", "open_project"]


@dataclass(frozen=True, slots=True)
class Project:
    """One simulated enterprise: its identity, its workspace, and its store.

    Attributes:
        manifest: The project's immutable identity.
        workspace: Where its datasets live.
        store: How its documents persist.
    """

    manifest: ProjectManifest
    workspace: Workspace
    store: StateStore

    @property
    def project_id(self) -> str:
        """Return the project's stable identifier."""
        return self.manifest.project_id

    @property
    def name(self) -> str:
        """Return the project's name."""
        return self.manifest.name

    @property
    def domain_name(self) -> str:
        """Return the name of the domain this project simulates."""
        return self.manifest.domain

    @property
    def seed(self) -> int | None:
        """Return the run seed the project was created with."""
        return self.manifest.seed

    @property
    def platform(self) -> PlatformMetadata:
        """Return the metadata of the platform currently running."""
        return platform_metadata()

    def domain(self) -> SimulationDomain:
        """Resolve the domain this project simulates.

        Resolution is deliberately not done when the project is opened. A
        project must be inspectable on a machine where its domain is not
        installed - reading a manifest to discover *what a project needs* is
        exactly when the domain is absent.

        Returns:
            The registered domain.

        Raises:
            KeyError: If the domain is not registered. Importing the domain's
                package registers it.
        """
        return get_domain(self.manifest.domain)

    def has_state(self) -> bool:
        """Report whether any state has been written yet."""
        return self.store.exists(STATE_KEY)

    def read_state(self) -> SimulationState:
        """Read the project's durable state.

        A project that has never run has no state document. That is not an
        error, so an empty state is returned - the caller should not have to
        distinguish "nothing has happened" from "something is wrong".

        Returns:
            The stored state, or an empty state if none has been written.

        Raises:
            CorruptDocumentError: If a state document exists but cannot be
                understood.
            UnsupportedVersionError: If its version cannot be read.
        """
        if not self.store.exists(STATE_KEY):
            return SimulationState()
        return SimulationState.from_document(self.store.read(STATE_KEY))

    def write_state(self, state: SimulationState) -> None:
        """Write the project's durable state, replacing any previous value.

        Args:
            state: The state to persist.

        Raises:
            StateStoreError: If the state cannot be written.
        """
        self.store.write(STATE_KEY, state.to_document())

    def validate(self) -> list[ProjectIssue]:
        """Check the project is structurally usable.

        Loadable and usable are different questions. A project whose domain is
        not installed still loads - its manifest is intact - but it cannot be
        run, and that is worth reporting rather than raising.

        Returns:
            Every issue found. Empty means the project is sound.
        """
        issues = self.workspace.validate()
        if self.manifest.domain not in list_domains():
            issues.append(
                ProjectIssue(
                    subject=self.manifest.domain,
                    rule="unknown_domain",
                    detail=f"no domain is registered under that name; "
                    f"registered: {list(list_domains())}",
                )
            )
        return issues

    def assert_valid(self) -> None:
        """Validate the project and raise if it is not usable.

        Raises:
            ProjectValidationError: If any issue is found.
        """
        if issues := self.validate():
            raise ProjectValidationError(tuple(issues))


def _store_for(workspace: Workspace) -> FileStateStore:
    """Return the default store for a workspace.

    Documents live in the workspace root beside the data directory. A caller
    wanting them elsewhere - a database, an object store - passes their own
    store instead.

    Args:
        workspace: The project workspace.

    Returns:
        A file store rooted at the workspace.
    """
    return FileStateStore(workspace.root)


def create_project(
    root: Path,
    name: str,
    domain: str,
    seed: int | None = None,
    project_id: str | None = None,
    created_at: datetime | None = None,
    store: StateStore | None = None,
) -> Project:
    """Create a new project and write its manifest.

    ``project_id`` and ``created_at`` are parameters rather than always being
    generated, so that a test can produce a byte-identical project twice. Left
    alone they are a fresh UUID and the current UTC time.

    Args:
        root: Directory to create the project in. Created if absent.
        name: Human-readable project name.
        domain: Name of the domain to simulate. Not required to be registered
            yet - a project may be created before its domain is installed.
        seed: Run seed. ``None`` means the project is not reproducible.
        project_id: Stable identifier. Generated when omitted.
        created_at: Creation timestamp, timezone-aware. Now, when omitted.
        store: Where documents persist. A file store in ``root`` when omitted.

    Returns:
        The created project.

    Raises:
        ProjectExistsError: If a manifest already exists at that location.
            Creating over a project would discard its identity and its history.
        ValueError: If the manifest would not be a valid identity.
        StateStoreError: If the manifest cannot be written.
    """
    workspace = Workspace(root=root)
    documents = store if store is not None else _store_for(workspace)

    if documents.exists(MANIFEST_KEY):
        raise ProjectExistsError(
            f"a project already exists at {root}. Open it instead, or choose another location."
        )

    manifest = ProjectManifest(
        project_id=project_id if project_id is not None else uuid4().hex,
        name=name,
        domain=domain,
        seed=seed,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )

    workspace.create()
    documents.write(MANIFEST_KEY, manifest.to_document())
    return Project(manifest=manifest, workspace=workspace, store=documents)


def open_project(root: Path, store: StateStore | None = None) -> Project:
    """Open an existing project.

    Opening reads and checks the manifest and nothing else. State is read on
    demand, and the domain is resolved on demand, so a project remains
    inspectable when it has never run or when its domain is not installed.

    Args:
        root: The project directory.
        store: Where documents persist. A file store in ``root`` when omitted.

    Returns:
        The opened project.

    Raises:
        ProjectNotFoundError: If no manifest exists at that location.
        CorruptDocumentError: If the manifest cannot be understood.
        UnsupportedVersionError: If the manifest version cannot be read.
    """
    workspace = Workspace(root=root)
    documents = store if store is not None else _store_for(workspace)

    if not documents.exists(MANIFEST_KEY):
        raise ProjectNotFoundError(
            f"no project at {root}: there is no {MANIFEST_KEY!r} document. "
            "Create one, or check the path."
        )

    manifest = ProjectManifest.from_document(documents.read(MANIFEST_KEY))
    return Project(manifest=manifest, workspace=workspace, store=documents)
