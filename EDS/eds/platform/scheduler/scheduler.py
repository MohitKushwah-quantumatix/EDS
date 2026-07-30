"""The runtime scheduler: the first thing in the platform that does anything.

It coordinates, and that is all it does. It does not know what a stage means,
what order stages go in, what a tick is worth, how state is stored, or what a
result looks like - five other modules already know those things, and the
scheduler's job is to call them in the right sequence.

**How little there is here is the point.** Every immutable value the platform
built earlier removed a decision from this module. The plan is already ordered,
so there is no sorting. The clock advances by returning a new clock, so there
is no time state to protect. The project owns persistence, so there is no
serialisation. The contracts refuse to contradict themselves, so there is no
consistency checking. What remains is a loop.

**The one thing it cannot do is run a stage.** The platform has no way to
execute a domain - PADR-006 removed ``generate()`` on evidence and that
decision stands - so the executor arrives as an argument
(:mod:`eds.platform.scheduler.executor`). The scheduler therefore has no
dependency on any domain, and a test proves it by executing whole runs with a
fake.

Sequential by design. No threads, no async, no queues. The plan already says
which stages *may* overlap - ``ExecutionPlan.levels()`` - so parallelism can
be added later by changing how one level is executed, without touching
ordering, persistence, events or results (PADR-013).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date

from eds.platform.execution.plan import PlannedStage
from eds.platform.run.mode import RunMode
from eds.platform.run.run import SimulationRun
from eds.platform.run.stop import AfterStage, AfterTicks, EndOfPeriod, StopCondition
from eds.platform.runtime.events import (
    ExecutionEvent,
    RunCompleted,
    RunFailed,
    RunStarted,
    StageCompleted,
    StageFailed,
    StageStarted,
)
from eds.platform.runtime.failure import ExecutionWarning, Failure, FailureType
from eds.platform.runtime.progress import Progress
from eds.platform.runtime.results import RunResult, StageResult
from eds.platform.runtime.status import ExecutionStatus
from eds.platform.scheduler.executor import StageExecutionError, StageExecutor, StageRequest
from eds.platform.scheduler.report import ExecutionReport
from eds.platform.time.clock import SimulationClock
from eds.platform.time.persistence import state_with_clock

__all__ = ["execute"]


def execute(run: SimulationRun, executor: StageExecutor) -> ExecutionReport:
    """Run a simulation and report what happened.

    Args:
        run: What to run. The scheduler never assembles one; it is given one
            whose parts have already been checked against each other
            (PADR-011).
        executor: How to run a stage. Supplied by the caller, because the
            platform has no way to execute a domain.

    Returns:
        The result, the event stream and the progress. Never raises for a
        failed run: a run that failed is an outcome, and making callers handle
        both an exception and a status would mean two ways to ask one
        question.

    Raises:
        CorruptDocumentError: If the project's state cannot be read. Reported
            as a validation issue rather than raised in every reachable case;
            this remains only for a state document that becomes unreadable
            between validation and the first write.
    """
    events = _Recorder(run.run_id)
    if issues := run.validate():
        return _refused(run, events, issues)

    clock = run.clock
    started_tick = clock.ticks_elapsed
    events.add(RunStarted(events.next(), run.run_id, clock.current_date, len(run.plan)))

    records = _Records(run.plan.stages)
    passes = 0
    failure: Failure | None = None

    if run.is_dry_run:
        # One pass, and no executor call. A rehearsal answers "what would run",
        # and the answer is the same on every tick, so repeating it 365 times
        # would produce noise rather than information.
        passes = 1
        records.skip_all()
        events.add(ExecutionWarning("", "dry_run", "nothing was executed and no state was written"))
    else:
        state = _completed_so_far(run)
        while True:
            passes += 1
            failure, stop = _one_pass(run, executor, clock, passes, events, records, state)
            if failure is not None or stop:
                break
            if _reached_stop(run.stop_condition, clock, passes):
                break
            if clock.is_finished:
                break
            clock = clock.advance()

    records.cancel_outstanding()
    return _report(run, events, records, clock, started_tick, passes, failure)


# --------------------------------------------------------------------------
# One tick
# --------------------------------------------------------------------------


def _one_pass(
    run: SimulationRun,
    executor: StageExecutor,
    clock: SimulationClock,
    pass_number: int,
    events: _Recorder,
    records: _Records,
    state: _Completed,
) -> tuple[Failure | None, bool]:
    """Run every executable stage once, at the clock's current date.

    Args:
        run: The run being executed.
        executor: How to run a stage.
        clock: Where in simulated time this pass sits. Every stage in the pass
            shares the date, which is what makes a tick one moment rather than
            a sequence of them.
        pass_number: Which tick this is, counting from one.
        events: Where events are recorded.
        records: Where per-stage facts accumulate.
        state: The project's completed-stage record.

    Returns:
        The failure that stopped the pass, if any, and whether the run's stop
        condition fired part-way through it.
    """
    for stage in _stages_for(run, pass_number):
        events.add(StageStarted(events.next(), run.run_id, clock.current_date, stage.stage_id))
        try:
            output = executor.execute(_request(run, stage, clock.current_date))
        except StageExecutionError as exc:
            failure = Failure(exc.failure_type, str(exc), stage.stage_id, exc.cause)
            records.fail(stage.stage_id, clock.current_date, failure)
            events.add(
                StageFailed(events.next(), run.run_id, clock.current_date, stage.stage_id, failure)
            )
            return failure, False
        except Exception as exc:  # noqa: BLE001 - an unnamed error is still a fact
            failure = Failure(
                FailureType.INTERNAL,
                f"stage {stage.name!r} raised an error the platform cannot classify",
                stage.stage_id,
                repr(exc),
            )
            records.fail(stage.stage_id, clock.current_date, failure)
            events.add(
                StageFailed(events.next(), run.run_id, clock.current_date, stage.stage_id, failure)
            )
            return failure, False

        records.complete(
            stage.stage_id, clock.current_date, output.rows_by_dataset, output.warnings
        )
        state.record(stage.stage_id)
        _persist(run, clock, state)
        events.add(
            StageCompleted(
                events.next(),
                run.run_id,
                clock.current_date,
                stage.stage_id,
                sum(output.rows_by_dataset.values()),
            )
        )
        if isinstance(run.stop_condition, AfterStage) and run.stop_condition.stage == stage.name:
            return None, True
    return None, False


def _stages_for(run: SimulationRun, pass_number: int) -> tuple[PlannedStage, ...]:
    """Return the stages to run on one tick.

    A resume honours the project's record on its **first** tick only: that is
    what resuming an interrupted run means - pick up where it stopped, then
    carry on normally. Deciding what is outstanding belongs to P005, so it is
    asked rather than recomputed.

    Args:
        run: The run being executed.
        pass_number: Which tick this is, counting from one.

    Returns:
        The stages, in the plan's order. Never reordered - P002 already
        decided.
    """
    if pass_number == 1 and run.mode is RunMode.RESUME:
        return run.remaining_stages()
    return run.plan.stages


def _request(run: SimulationRun, stage: PlannedStage, when: date) -> StageRequest:
    """Build what an executor needs from what the run already holds.

    Args:
        run: The run being executed.
        stage: The stage to run.
        when: The simulated date of this tick.

    Returns:
        The request.
    """
    return StageRequest(
        stage=stage,
        simulation_date=when,
        run_id=run.run_id,
        project_id=run.project.project_id,
        seed=run.project.seed,
        data_directory=run.project.workspace.data_directory,
    )


def _persist(run: SimulationRun, clock: SimulationClock, state: _Completed) -> None:
    """Record progress, after a stage succeeded and never before.

    Persisting only completed work is what makes a failed run resumable rather
    than ambiguous. If a partially-run stage were recorded, a resume would skip
    work that was never finished and the datasets would be silently short; if
    a failed stage were recorded, the failure would be forgotten. Recording
    only what finished means the project's state is always a true statement
    about what exists.

    The scheduler asks the project to write. It never touches a store and
    never serialises anything (PADR-009).

    Args:
        run: The run being executed.
        clock: Where in simulated time the run has reached.
        state: The completed-stage record.
    """
    current = run.read_state()
    run.project.write_state(
        replace(state_with_clock(current, clock), completed_stages=state.ordered)
    )


def _reached_stop(condition: StopCondition, clock: SimulationClock, passes: int) -> bool:
    """Report whether the run's stop condition has been met after a tick.

    ``AfterStage`` is not checked here: it fires the moment its stage
    completes, part-way through a tick, which is the only reading that makes
    naming an early stage useful.

    Args:
        condition: The run's stop condition.
        clock: Where in simulated time the run has reached.
        passes: How many ticks have been executed.

    Returns:
        Whether to stop.
    """
    match condition:
        case AfterTicks(count):
            return passes >= count
        case EndOfPeriod():
            return clock.is_finished
        case AfterStage():
            return False


# --------------------------------------------------------------------------
# Accumulating facts
# --------------------------------------------------------------------------


@dataclass(slots=True)
class _StageRecord:
    """What has happened to one stage so far, across every tick it ran on.

    Mutable, and private. The scheduler holds the run; the contracts it
    produces are immutable values built once at the end (PADR-012).

    Attributes:
        stage_id: The stage's stable identifier.
        status: Where it has got to.
        first_date: The simulated date it first ran on.
        last_date: The simulated date it last ran on.
        rows: Rows produced, summed across ticks.
        warnings: Every warning it reported.
        failure: Why it failed, if it did.
    """

    stage_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    first_date: date | None = None
    last_date: date | None = None
    rows: dict[str, int] = field(default_factory=dict)
    warnings: tuple[ExecutionWarning, ...] = ()
    failure: Failure | None = None

    def result(self, fallback: date) -> StageResult:
        """Build the immutable result this record describes.

        Args:
            fallback: The date to use for a stage that never ran.

        Returns:
            One result covering every tick the stage ran on. A stage that ran
            on several ticks gets one result spanning them, because a run may
            not hold two results for one stage (PADR-012) - which is exactly
            why a stage result carries two dates.
        """
        return StageResult(
            stage_id=self.stage_id,
            status=self.status,
            start_date=self.first_date or fallback,
            end_date=self.last_date or self.first_date or fallback,
            rows_by_dataset=dict(self.rows),
            failure=self.failure,
            warnings=self.warnings,
        )


class _Records:
    """The per-stage records of one execution, in the plan's order."""

    def __init__(self, stages: tuple[PlannedStage, ...]) -> None:
        """Start a record for every planned stage.

        Args:
            stages: The planned stages, in execution order.
        """
        self._records = {stage.stage_id: _StageRecord(stage.stage_id) for stage in stages}

    def complete(
        self,
        stage_id: str,
        when: date,
        rows: dict[str, int],
        warnings: tuple[ExecutionWarning, ...],
    ) -> None:
        """Record that a stage finished a tick successfully.

        Args:
            stage_id: The stage.
            when: The simulated date of the tick.
            rows: Rows produced on this tick, added to any earlier ticks'.
            warnings: Warnings reported on this tick.
        """
        record = self._records[stage_id]
        record.status = ExecutionStatus.COMPLETED
        record.first_date = record.first_date or when
        record.last_date = when
        for dataset, count in rows.items():
            record.rows[dataset] = record.rows.get(dataset, 0) + count
        record.warnings += warnings

    def fail(self, stage_id: str, when: date, failure: Failure) -> None:
        """Record that a stage failed.

        Args:
            stage_id: The stage.
            when: The simulated date it failed on.
            failure: Why.
        """
        record = self._records[stage_id]
        record.status = ExecutionStatus.FAILED
        record.first_date = record.first_date or when
        record.last_date = when
        record.failure = failure
        record.rows.clear()

    def skip_all(self) -> None:
        """Record every stage as deliberately not run.

        Used by a dry run. ``SKIPPED`` also forbids rows, so the contracts
        themselves enforce that a rehearsal produced nothing (PADR-012).
        """
        for record in self._records.values():
            record.status = ExecutionStatus.SKIPPED

    def cancel_outstanding(self) -> None:
        """Record every stage that never started as cancelled.

        A run that stopped early leaves stages behind. Recording them keeps
        the result total, so a consumer asking what happened to any planned
        stage gets an answer rather than a ``KeyError``. ``PENDING`` to
        ``CANCELLED`` is the transition the status model declares for exactly
        this (PADR-012).
        """
        for record in self._records.values():
            if record.status is ExecutionStatus.PENDING:
                record.status = ExecutionStatus.CANCELLED

    def completed_names(self) -> set[str]:
        """Return the identifiers of the stages that have completed."""
        return {
            stage_id
            for stage_id, record in self._records.items()
            if record.status is ExecutionStatus.COMPLETED
        }

    def results(self, fallback: date) -> tuple[StageResult, ...]:
        """Build every stage's result, in the plan's order.

        Args:
            fallback: The date to use for stages that never ran.

        Returns:
            One result per planned stage.
        """
        return tuple(record.result(fallback) for record in self._records.values())


class _Completed:
    """The set of stages a project records as completed, kept in order."""

    def __init__(self, known: tuple[str, ...]) -> None:
        """Start from what the project already recorded.

        Args:
            known: Stage identifiers already recorded as completed.
        """
        self._ordered = list(known)
        self._seen = set(known)

    def record(self, stage_id: str) -> None:
        """Record a stage as completed, at most once.

        A stage that runs on many ticks completes many times, but the project's
        record answers "has this ever completed", which is what a resume needs
        - and P003 refuses a stage recorded twice.

        Args:
            stage_id: The stage.
        """
        if stage_id not in self._seen:
            self._seen.add(stage_id)
            self._ordered.append(stage_id)

    @property
    def ordered(self) -> tuple[str, ...]:
        """Return the completed stages, in the order they first completed."""
        return tuple(self._ordered)


class _Recorder:
    """The event stream of one execution, numbered as it is built."""

    def __init__(self, run_id: str) -> None:
        """Start an empty stream.

        Args:
            run_id: The run every event will belong to.
        """
        self._run_id = run_id
        self._events: list[ExecutionEvent] = []
        self._warnings: list[ExecutionWarning] = []
        self._sequence = 0

    def next(self) -> int:
        """Return the next sequence number.

        Deterministic because execution is sequential: the same run with the
        same executor produces the same numbers, on every machine.
        """
        current = self._sequence
        self._sequence += 1
        return current

    def add(self, item: ExecutionEvent | ExecutionWarning) -> None:
        """Record an event, or a run-level warning.

        Args:
            item: What to record.
        """
        if isinstance(item, ExecutionWarning):
            self._warnings.append(item)
        else:
            self._events.append(item)

    @property
    def events(self) -> tuple[ExecutionEvent, ...]:
        """Return the stream, in emission order - already sequence order."""
        return tuple(self._events)

    @property
    def warnings(self) -> tuple[ExecutionWarning, ...]:
        """Return the run-level warnings."""
        return tuple(self._warnings)


# --------------------------------------------------------------------------
# Assembling the report
# --------------------------------------------------------------------------


def _completed_so_far(run: SimulationRun) -> _Completed:
    """Read what the project already records as completed.

    Args:
        run: The run being executed.

    Returns:
        The record, ready to be added to.
    """
    return _Completed(run.read_state().completed_stages)


def _refused(run: SimulationRun, events: _Recorder, issues: Sequence[object]) -> ExecutionReport:
    """Return the report for a run whose parts do not agree.

    No ``RunStarted`` is emitted, because nothing started. A stream beginning
    with ``RunFailed`` is unusual to read and is the truth: the alternative -
    announcing a start that did not happen so that the stream looks tidy -
    would make the first event a false one.

    Args:
        run: The run that was refused.
        events: The (empty) stream.
        issues: What disagreed.

    Returns:
        A failed report.
    """
    failure = Failure(
        failure_type=FailureType.CONFIGURATION,
        message=f"the run is not executable: {'; '.join(str(issue) for issue in issues)}",
    )
    when = run.clock.current_date
    events.add(RunFailed(events.next(), run.run_id, when, failure))
    result = RunResult(
        run_id=run.run_id,
        project_id=run.project.project_id,
        status=ExecutionStatus.FAILED,
        start_date=when,
        end_date=when,
        started_tick=run.clock.ticks_elapsed,
        finished_tick=run.clock.ticks_elapsed,
        failure=failure,
    )
    return ExecutionReport(result=result, events=events.events, progress=Progress())


def _report(
    run: SimulationRun,
    events: _Recorder,
    records: _Records,
    clock: SimulationClock,
    started_tick: int,
    passes: int,
    failure: Failure | None,
) -> ExecutionReport:
    """Build the immutable report from everything that accumulated.

    Args:
        run: The run that was executed.
        events: The stream.
        records: The per-stage records.
        clock: Where the clock finished.
        started_tick: Where it began.
        passes: How many ticks were executed.
        failure: What stopped the run, if anything.

    Returns:
        The report.
    """
    status = ExecutionStatus.FAILED if failure else ExecutionStatus.COMPLETED
    when = clock.current_date
    if failure:
        events.add(RunFailed(events.next(), run.run_id, when, failure))
    else:
        events.add(RunCompleted(events.next(), run.run_id, when, len(records.completed_names())))

    stages = records.results(run.clock.current_date)
    done = sum(1 for stage in stages if stage.is_successful)
    result = RunResult(
        run_id=run.run_id,
        project_id=run.project.project_id,
        status=status,
        start_date=run.clock.current_date,
        end_date=when,
        started_tick=started_tick,
        finished_tick=clock.ticks_elapsed,
        stages=stages,
        failure=failure,
        warnings=events.warnings,
    )
    progress = Progress(
        completed_stages=done,
        total_stages=len(stages),
        completed_ticks=passes,
        total_ticks=_expected_ticks(run, clock),
    )
    return ExecutionReport(result=result, events=events.events, progress=progress)


def _expected_ticks(run: SimulationRun, clock: SimulationClock) -> int | None:
    """Return how many ticks the run expected to execute, if that is knowable.

    ``None`` rather than a guess whenever it is not: an open-ended period has
    no total, and a run stopping on a stage stops when it stops. A progress bar
    with no denominator is a caller's problem to render; a fabricated
    denominator is everybody's problem (PADR-012).

    Args:
        run: The run being executed.
        clock: The clock, for its tick and period.

    Returns:
        The expected number of ticks, or ``None``.
    """
    if run.is_dry_run:
        return 1
    match run.stop_condition:
        case AfterTicks(count):
            return count
        case EndOfPeriod() if clock.end is not None:
            return clock.tick.elapsed(clock.start, clock.end, clock.calendar) + 1
        case _:
            return None
