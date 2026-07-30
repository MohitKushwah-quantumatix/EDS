"""The project workspace: where a simulated enterprise lives on disk.

The workspace owns the *bulk data* layout - where an adapter would write
datasets, where snapshots would go, where logs would go. It deliberately does
not own where the manifest and state documents live: that is the store's
business, and keeping the two apart is what lets a project keep its documents
in a database while its datasets stay on a filesystem.

Only ``data/`` is created. ``snapshots/`` and ``logs/`` are declared paths with
no implementation behind them yet: naming where something will live is cheap,
and creating an empty directory that nothing writes to is clutter that also
does not survive version control.

The workspace is filesystem-shaped, and knowingly so. Datasets are large and
adapters write them by location, so a ``Path`` is the honest type today. A
workspace backed by object storage would need a location abstraction, and that
is a change to make when there is an adapter that needs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eds.platform.project.errors import ProjectIssue

__all__ = ["DATA_DIRECTORY", "LOGS_DIRECTORY", "SNAPSHOTS_DIRECTORY", "Workspace"]

#: Where an adapter writes generated datasets.
DATA_DIRECTORY = "data"

#: Reserved for point-in-time copies. Snapshots are not implemented.
SNAPSHOTS_DIRECTORY = "snapshots"

#: Reserved for run logs. Logging to a workspace is not implemented.
LOGS_DIRECTORY = "logs"


@dataclass(frozen=True, slots=True)
class Workspace:
    """A directory holding one project.

    Attributes:
        root: The project directory.
    """

    root: Path

    @property
    def data_directory(self) -> Path:
        """Return where generated datasets belong."""
        return self.root / DATA_DIRECTORY

    @property
    def snapshots_directory(self) -> Path:
        """Return where snapshots would belong. Reserved, not created."""
        return self.root / SNAPSHOTS_DIRECTORY

    @property
    def logs_directory(self) -> Path:
        """Return where logs would belong. Reserved, not created."""
        return self.root / LOGS_DIRECTORY

    def exists(self) -> bool:
        """Report whether the workspace directory is present."""
        return self.root.is_dir()

    def create(self) -> None:
        """Create the workspace and the directories that are actually used.

        Idempotent: creating an existing workspace is not an error, because
        the caller that decides whether a *project* may be created has already
        made that judgement.

        Raises:
            OSError: If the directories cannot be created.
        """
        self.data_directory.mkdir(parents=True, exist_ok=True)

    def validate(self) -> list[ProjectIssue]:
        """Check the workspace is structurally usable.

        Returns:
            Every issue found. Empty means the layout is sound.
        """
        if not self.root.exists():
            return [
                ProjectIssue(
                    subject=str(self.root),
                    rule="missing_workspace",
                    detail="the project directory does not exist",
                )
            ]
        if not self.root.is_dir():
            return [
                ProjectIssue(
                    subject=str(self.root),
                    rule="workspace_not_a_directory",
                    detail="the project path exists but is not a directory",
                )
            ]
        if not self.data_directory.is_dir():
            return [
                ProjectIssue(
                    subject=DATA_DIRECTORY,
                    rule="missing_data_directory",
                    detail=f"the workspace has no {DATA_DIRECTORY}/ directory for datasets",
                )
            ]
        return []
