"""The one thing the scheduler cannot do itself: run a stage.

**This protocol exists because the platform deliberately has no way to execute
a domain.** PADR-006 removed ``generate()`` from
:class:`~eds.platform.domain.SimulationDomain` after it failed to survive
contact with Retail: a domain does not generate in one call, it generates in
ordered stages that read what earlier stages wrote, and a no-argument
``generate()`` could only be implemented by duplicating the CLI's orchestration
inside the domain. The protocol describes; it does not execute.

That decision was right and it is still right, but it leaves the scheduler with
nothing to call. There were three ways out. Let the scheduler import a domain -
which makes the platform know about Retail, and breaks PADR-002. Add
``execute()`` back to the domain protocol - which changes a frozen module and
reopens a question P001.1 closed with evidence. Or **take the executor as an
argument**, which is what this is.

The third is the only one that keeps every existing decision intact. The
scheduler orchestrates and knows nothing about business; whoever supplies the
executor knows about business and nothing about orchestration; and the seam
between them is a protocol with one method. It also means the scheduler is
testable with a fake executor, which is how every behaviour in P006 is
verified without generating a single row.

**Executors raise; they do not return failures.** A generator that hits a bad
row raises, and requiring every executor to catch everything and return a
:class:`~eds.platform.runtime.failure.Failure` would push error handling into
each of them and make forgetting it silent. Raising
:class:`StageExecutionError` says which kind of failure it was; anything else
is classified as ``INTERNAL``, because an exception the platform cannot name is
a defect rather than a condition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

from eds.platform.execution.plan import PlannedStage
from eds.platform.runtime.failure import ExecutionWarning, FailureType

__all__ = ["StageExecutionError", "StageExecutor", "StageOutput", "StageRequest"]


@dataclass(frozen=True, slots=True)
class StageRequest:
    """Everything an executor needs to run one stage once.

    Assembled by the scheduler from the run it was given, so an executor never
    has to reach back into a project, a plan or a clock. It is a value: an
    executor may keep it, log it or compare it.

    Attributes:
        stage: The stage to run, exactly as P002 planned it. Its ``requires``
            and ``produces`` say what to read and write.
        simulation_date: The simulated date this tick covers. Every stage in
            one tick shares it, which is what makes a tick a coherent moment.
        run_id: The run this belongs to.
        project_id: The project being simulated.
        seed: The project's run seed, or ``None`` if it has none.
        data_directory: Where the project's datasets live. A path because
            adapters write by location today (PADR-009); an executor writing
            somewhere else is free to ignore it.
    """

    stage: PlannedStage
    simulation_date: date
    run_id: str
    project_id: str
    seed: int | None
    data_directory: Path

    @property
    def stage_id(self) -> str:
        """Return the stage's stable identifier."""
        return self.stage.stage_id


@dataclass(frozen=True, slots=True)
class StageOutput:
    """What an executor reports about work it finished.

    Facts only, and only the facts the scheduler needs to build a
    :class:`~eds.platform.runtime.results.StageResult`. An executor that wants
    to report more has somewhere to put it: a warning carries a rule and a
    detail.

    Attributes:
        rows_by_dataset: How many rows each dataset gained. Empty is
            legitimate - a stage may correctly produce nothing on a given
            simulated day.
        warnings: What was worth reporting and did not stop the work.
    """

    rows_by_dataset: dict[str, int] = field(default_factory=dict)
    warnings: tuple[ExecutionWarning, ...] = ()


@runtime_checkable
class StageExecutor(Protocol):
    """Runs one stage of one domain.

    The whole of the platform's business-facing surface at execution time.
    Implementations know how to generate, validate and write; they know
    nothing about ordering, ticks, state or events, because the scheduler
    already does.

    Implementations must be deterministic: the same request must produce the
    same rows, on every machine and in every run. That is the property the
    whole platform rests on (ADR-005), and the scheduler cannot enforce it -
    it can only avoid breaking it, which it does by never passing anything
    that varies.
    """

    def execute(self, request: StageRequest) -> StageOutput:
        """Run one stage once.

        Args:
            request: What to run, when, for whom, and where.

        Returns:
            What the stage produced.

        Raises:
            StageExecutionError: If the stage could not be completed, naming
                which kind of failure it was.
        """
        ...


class StageExecutionError(Exception):
    """Raised by an executor when a stage could not be completed.

    Carries the classification the executor is in a position to make and the
    scheduler is not: only the executor knows whether a stage died generating,
    validating or writing.

    Attributes:
        failure_type: Which kind of failure this was.
        cause: The underlying error rendered as text, or ``None``. Text rather
            than an exception, because it ends up in a stored contract
            (PADR-012).
    """

    def __init__(
        self,
        message: str,
        failure_type: FailureType = FailureType.GENERATION,
        cause: str | None = None,
    ) -> None:
        """Build the error.

        Args:
            message: What happened, in a sentence somebody can act on.
            failure_type: Which kind of failure. Generation by default, which
                is where most stage failures come from.
            cause: The underlying error as text.
        """
        super().__init__(message)
        self.failure_type = failure_type
        self.cause = cause
