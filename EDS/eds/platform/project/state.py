"""Durable simulation state.

State is everything about a project that changes between runs, as opposed to
the identity in :class:`~eds.platform.project.manifest.ProjectManifest`, which
never does.

**This module stores state; it does not advance it.** ``current_date`` is
recorded, never incremented - advancing it is the clock's job, and the clock
does not exist. ``completed_stages`` is recorded, never appended to by anything
here - deciding that a stage completed is the scheduler's job, and the
scheduler does not exist.

The record is frozen, so "updating" state means building a new one with
:func:`dataclasses.replace` and writing it. That is not a limitation to work
around later: it is what makes a state document a value that can be compared,
logged and reasoned about, rather than a mutable object whose history is lost
the moment it changes.

There is deliberately no ``updated_at``. When a document was written is the
store's business, and a field that changes on every write would mean the same
state never serialises to the same bytes twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from eds.platform.project.errors import CorruptDocumentError
from eds.platform.project.store import Document
from eds.platform.project.versions import STATE_VERSION, require_supported_version

__all__ = ["STATE_KEY", "SimulationState"]

#: Logical document key the state is stored under.
STATE_KEY = "state"


@dataclass(frozen=True, slots=True)
class SimulationState:
    """What a project has done so far.

    Attributes:
        current_date: The simulated date the project has reached, or ``None``
            before anything has run. Stored only; nothing here advances it.
        completed_stages: Stage identifiers already completed, in the order
            they completed. Identifiers are the execution model's
            ``"<domain>:<stage>"`` form, carried as opaque strings so that
            state does not depend on the execution model.
        last_identifiers: The highest identifier issued per dataset, so a
            resumed run can continue numbering rather than collide. Keyed by
            dataset name.
        state_version: Shape of this document.
    """

    current_date: date | None = None
    completed_stages: tuple[str, ...] = ()
    last_identifiers: dict[str, int] = field(default_factory=dict)
    state_version: int = STATE_VERSION

    def __post_init__(self) -> None:
        """Reject state that could not be trusted.

        Raises:
            ValueError: If a stage is recorded twice, or an identifier is
                negative. A stage completing twice means either a lost write
                or a scheduler bug, and silently accepting it would hide both.
        """
        seen: set[str] = set()
        for stage in self.completed_stages:
            if stage in seen:
                raise ValueError(f"stage {stage!r} is recorded as completed more than once")
            seen.add(stage)
        for dataset, value in self.last_identifiers.items():
            if value < 0:
                raise ValueError(f"last identifier for {dataset!r} cannot be negative, got {value}")

    @property
    def last_completed_stage(self) -> str | None:
        """Return the most recently completed stage, if any.

        The full ordered record is kept rather than only this, because stages
        at one dependency level may complete in any order and a resumed run
        needs to know which of them are done - not merely which was last.
        """
        return self.completed_stages[-1] if self.completed_stages else None

    def to_document(self) -> dict[str, Any]:
        """Render the state as a storable document.

        Returns:
            A plain mapping of primitives, with the date in ISO 8601.
        """
        return {
            "current_date": self.current_date.isoformat() if self.current_date else None,
            "completed_stages": list(self.completed_stages),
            "last_identifiers": dict(sorted(self.last_identifiers.items())),
            "state_version": self.state_version,
        }

    @classmethod
    def from_document(cls, document: Document) -> SimulationState:
        """Rebuild state from a stored document.

        Args:
            document: The stored document.

        Returns:
            The state.

        Raises:
            CorruptDocumentError: If a field is absent or malformed.
            UnsupportedVersionError: If the state version is one this platform
                cannot read.
        """
        version = document.get("state_version")
        if not isinstance(version, int) or isinstance(version, bool):
            raise CorruptDocumentError(
                f"state field 'state_version' must be an integer, found {version!r}"
            )
        require_supported_version("state", version, STATE_VERSION)

        raw_date = document.get("current_date")
        if raw_date is None:
            current_date = None
        elif isinstance(raw_date, str):
            try:
                current_date = date.fromisoformat(raw_date)
            except ValueError as exc:
                raise CorruptDocumentError(
                    f"state current_date {raw_date!r} is not an ISO 8601 date"
                ) from exc
        else:
            raise CorruptDocumentError(
                f"state current_date must be a string or null, found {raw_date!r}"
            )

        raw_stages = document.get("completed_stages", [])
        if not isinstance(raw_stages, list) or not all(isinstance(s, str) for s in raw_stages):
            raise CorruptDocumentError(
                f"state completed_stages must be a list of strings, found {raw_stages!r}"
            )

        raw_identifiers = document.get("last_identifiers", {})
        if not isinstance(raw_identifiers, dict) or not all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
            for k, v in raw_identifiers.items()
        ):
            raise CorruptDocumentError(
                "state last_identifiers must map dataset names to integers, "
                f"found {raw_identifiers!r}"
            )

        try:
            return cls(
                current_date=current_date,
                completed_stages=tuple(raw_stages),
                last_identifiers=dict(raw_identifiers),
                state_version=version,
            )
        except ValueError as exc:
            raise CorruptDocumentError(f"state is not valid: {exc}") from exc
