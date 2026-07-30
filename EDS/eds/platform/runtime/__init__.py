"""The runtime contracts: the language execution is described in.

This package answers **"what happened?"**. It does not make anything happen.

Every type in it is a frozen record of facts. Nothing here runs a stage, tracks
a lifecycle, fires a callback, retries anything or reads the wall clock. There
is no bus, no observer and no dispatch: a scheduler produces these values and
whatever wants them reads them.

**Why they exist.** A scheduler that had to invent its own result type would
invent one shaped by how it happens to execute, and then a growth engine, a
snapshot writer and a change-capture reader would each be coupled to that
scheduler rather than to the platform. Defining the vocabulary first means the
scheduler has nothing left to invent, and means these contracts can be built
and tested without any of those components existing.

**Everything is deterministic.** No contract carries wall-clock time. Two runs
of the same simulation with the same seed produce equal results and equal event
streams, which is what makes a result worth storing, comparing and asserting on
(ADR-005). A scheduler may log elapsed seconds beside a contract; it does not
belong inside one.

**They depend on almost nothing.** The only platform import in this package is
the date vocabulary from :mod:`eds.platform.time.dates`. A result does not
import a plan, a project, a clock or a run - identifiers are opaque strings -
so a stored result can be read back on a machine where none of those exist
(PADR-012).
"""

from eds.platform.runtime.errors import InvalidStatusTransitionError, RuntimeContractError
from eds.platform.runtime.events import (
    EXECUTION_EVENT_KINDS,
    ExecutionEvent,
    RunCompleted,
    RunFailed,
    RunStarted,
    StageCompleted,
    StageFailed,
    StageStarted,
    execution_event_from_document,
    in_sequence,
)
from eds.platform.runtime.failure import ExecutionWarning, Failure, FailureType
from eds.platform.runtime.progress import Progress
from eds.platform.runtime.results import RunResult, StageResult
from eds.platform.runtime.status import (
    STATUS_TRANSITIONS,
    TERMINAL_STATUSES,
    ExecutionStatus,
    is_valid_transition,
    require_valid_transition,
)

__all__ = [
    "EXECUTION_EVENT_KINDS",
    "STATUS_TRANSITIONS",
    "TERMINAL_STATUSES",
    "ExecutionEvent",
    "ExecutionStatus",
    "ExecutionWarning",
    "Failure",
    "FailureType",
    "InvalidStatusTransitionError",
    "Progress",
    "RunCompleted",
    "RunFailed",
    "RunResult",
    "RunStarted",
    "RuntimeContractError",
    "StageCompleted",
    "StageFailed",
    "StageResult",
    "StageStarted",
    "execution_event_from_document",
    "in_sequence",
    "is_valid_transition",
    "require_valid_transition",
]
