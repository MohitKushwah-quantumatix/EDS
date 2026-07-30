"""The part of a run that can be written down.

A :class:`RunConfiguration` is the *portable* half of a run: which stages, in
what mode, until when, and whether anything is written. Every field is a
primitive or a closed value, so it round-trips through a document, fits in a
YAML file, and maps one-to-one onto a future set of CLI flags.

The other half - the project, the plan, the clock - cannot be written down. A
project handle holds a live store, and a clock holds a calendar, which is code.
That asymmetry is the reason the two are separate types rather than one object
with a serialisable subset: what can be persisted and what must be resolved are
different things, and a type that is half-serialisable invites somebody to
persist it anyway.

**No time configuration lives here.** A period, a tick and a calendar are held
by the clock, and restating them would create two records of the same fact that
could disagree. Where a run's *time* configuration gets persisted is a question
P004 left open, and it stays open: closing it by duplicating the clock's fields
would be the wrong answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from eds.platform.run.mode import RunMode
from eds.platform.run.stop import (
    EndOfPeriod,
    StopCondition,
    stop_condition_from_document,
)

__all__ = ["RunConfiguration"]


@dataclass(frozen=True, slots=True)
class RunConfiguration:
    """What was asked for, independent of what it was asked of.

    Attributes:
        mode: Which stages the run wants. Full, by default.
        targets: Stage names, unqualified. Only a targeted run may have them,
            and a targeted run must.
        stop_condition: When the run should stop. The end of the clock's
            period, by default.
        dry_run: Whether the run is a rehearsal - planned and validated, with
            nothing produced. Independent of the mode, so any mode may be
            rehearsed.
    """

    mode: RunMode = RunMode.FULL
    targets: tuple[str, ...] = ()
    stop_condition: StopCondition = field(default_factory=EndOfPeriod)
    dry_run: bool = False

    def __post_init__(self) -> None:
        """Reject a configuration that contradicts itself.

        These are checks a configuration can make alone, without a plan or a
        clock to compare against; whether the targets *exist* is a question
        for the run.

        Raises:
            ValueError: If a targeted run names no stages, if any other mode
                names some, or if a target is blank or repeated.
        """
        if self.mode.accepts_targets and not self.targets:
            raise ValueError(
                "a targeted run must name at least one stage; "
                f"use {RunMode.FULL.value!r} to run everything"
            )
        if not self.mode.accepts_targets and self.targets:
            raise ValueError(
                f"a {self.mode.value!r} run cannot name target stages "
                f"(got {list(self.targets)}); use {RunMode.TARGETED.value!r} to name stages"
            )
        seen: set[str] = set()
        for target in self.targets:
            if not target.strip():
                raise ValueError("a target stage name must not be blank")
            if target in seen:
                raise ValueError(f"target stage {target!r} is named more than once")
            seen.add(target)

    def __str__(self) -> str:
        """Render the configuration for a message."""
        what = f"{self.mode.value} run"
        if self.targets:
            what += f" of {list(self.targets)}"
        rehearsal = " (dry run)" if self.dry_run else ""
        return f"{what}, stopping {self.stop_condition}{rehearsal}"

    def to_document(self) -> dict[str, Any]:
        """Render the configuration as a storable document.

        Returns:
            A plain mapping of primitives that
            :meth:`from_document` reads back unchanged.
        """
        return {
            "mode": self.mode.value,
            "targets": list(self.targets),
            "stop_condition": self.stop_condition.to_document(),
            "dry_run": self.dry_run,
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> RunConfiguration:
        """Rebuild a configuration from a stored document.

        Args:
            document: The stored document.

        Returns:
            The configuration.

        Raises:
            ValueError: If a field is absent, malformed, or contradicts
                another.
        """
        raw_mode = document.get("mode", RunMode.FULL.value)
        known = [member.value for member in RunMode]
        if not isinstance(raw_mode, str):
            raise ValueError(f"run mode {raw_mode!r} is not one of {known}")
        try:
            mode = RunMode(raw_mode)
        except ValueError as exc:
            raise ValueError(f"run mode {raw_mode!r} is not one of {known}") from exc

        raw_targets = document.get("targets", [])
        if not isinstance(raw_targets, list) or not all(
            isinstance(target, str) for target in raw_targets
        ):
            raise ValueError(f"run targets must be a list of stage names, found {raw_targets!r}")

        raw_stop = document.get("stop_condition", {"kind": "end_of_period"})
        if not isinstance(raw_stop, dict):
            raise ValueError(f"run stop_condition must be an object, found {raw_stop!r}")

        dry_run = document.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise ValueError(f"run dry_run must be true or false, found {dry_run!r}")

        return cls(
            mode=mode,
            targets=tuple(raw_targets),
            stop_condition=stop_condition_from_document(raw_stop),
            dry_run=dry_run,
        )
