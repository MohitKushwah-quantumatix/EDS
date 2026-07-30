"""What a scheduler hands back.

A run produces three things that P005.1 already defines - an outcome, a
narrative and a position - and a function returning three values needs a name
for the triple. That is all this is. It **defines no contract**: every field is
a P005.1 type, unchanged.

The alternative was to put the events and the progress on
:class:`~eds.platform.runtime.results.RunResult`, which would have meant
editing a frozen module to accommodate its first consumer - the precise thing
P006 was told not to do. Returning a container costs one small type and keeps
the contracts as they were designed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from eds.platform.runtime.events import ExecutionEvent
from eds.platform.runtime.progress import Progress
from eds.platform.runtime.results import RunResult

__all__ = ["ExecutionReport"]


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    """Everything one execution produced.

    Attributes:
        result: What happened, aggregated. One
            :class:`~eds.platform.runtime.results.StageResult` per stage,
            whatever number of ticks the run took.
        events: How it got there, in emission order - which is already
            sequence order, because execution is sequential.
        progress: How far the run got, for a caller that wants a proportion
            rather than a narrative.
    """

    result: RunResult
    events: tuple[ExecutionEvent, ...] = ()
    progress: Progress = field(default_factory=Progress)

    @property
    def succeeded(self) -> bool:
        """Report whether the run did what was asked."""
        return self.result.is_successful

    def __str__(self) -> str:
        """Render the report for a log line."""
        return f"{self.result} [{len(self.events)} event(s)]"
