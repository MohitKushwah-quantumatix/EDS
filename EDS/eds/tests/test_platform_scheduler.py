"""Behavioural tests for the runtime scheduler (P006).

The first tests in the platform that actually execute something. Every one of
them runs a real scheduler over a real plan, a real project and a real clock,
with a **fake executor** - which is the point of the executor being an
argument. Nothing here generates a row, and the scheduler cannot tell.

The behaviours that get the most attention are the ones a scheduler is easy to
get subtly wrong: that state is written only after a stage succeeds and never
after one fails, that the clock advances between ticks and never within one,
that the event stream is deterministic, and that a dry run touches nothing.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

import eds.domains.retail  # noqa: F401  - registers the domain the tests plan against
from eds.platform.execution import plan_domain
from eds.platform.project import Project, SimulationState, create_project
from eds.platform.run import (
    AfterStage,
    AfterTicks,
    RunConfiguration,
    RunMode,
    SimulationRun,
    create_run,
)
from eds.platform.runtime import (
    ExecutionStatus,
    ExecutionWarning,
    FailureType,
    RunCompleted,
    RunFailed,
    RunStarted,
    StageCompleted,
    StageFailed,
    StageStarted,
    in_sequence,
)
from eds.platform.scheduler import (
    ExecutionReport,
    StageExecutionError,
    StageExecutor,
    StageOutput,
    StageRequest,
    execute,
)
from eds.platform.time import MONTHLY, SimulationClock, create_clock, state_with_clock

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SCHEDULER_ROOT = PACKAGE_ROOT / "platform" / "scheduler"

START = date(2024, 1, 1)
END = date(2024, 12, 31)
RETAIL_STAGES = ("retail:master-data", "retail:customers", "retail:journey", "retail:commerce")


@dataclass
class RecordingExecutor:
    """A fake executor that reports ten rows per dataset and remembers its calls.

    Satisfies :class:`~eds.platform.scheduler.executor.StageExecutor`.

    Attributes:
        rows: How many rows to report for each dataset a stage produces.
        calls: Every request received, in order.
        warnings: Warnings to attach to each stage's output.
    """

    rows: int = 10
    calls: list[StageRequest] = field(default_factory=list)
    warnings: tuple[ExecutionWarning, ...] = ()

    def execute(self, request: StageRequest) -> StageOutput:
        """Record the request and report rows for every dataset the stage produces.

        Args:
            request: What to run.

        Returns:
            The reported rows.
        """
        self.calls.append(request)
        return StageOutput(
            rows_by_dataset=dict.fromkeys(request.stage.produces, self.rows),
            warnings=self.warnings,
        )

    @property
    def stage_ids(self) -> list[str]:
        """Return the identifiers of the stages executed, in order."""
        return [call.stage_id for call in self.calls]

    @property
    def dates(self) -> list[date]:
        """Return the simulated date of each call, in order."""
        return [call.simulation_date for call in self.calls]


@dataclass
class FailingExecutor:
    """A fake executor that fails on a named stage.

    Attributes:
        fails_on: The unqualified stage name to fail on.
        failure_type: What kind of failure to report.
        raises: An arbitrary exception to raise instead of a
            :class:`StageExecutionError`, for the unclassifiable case.
        calls: Every request received, in order.
    """

    fails_on: str
    failure_type: FailureType = FailureType.GENERATION
    raises: Exception | None = None
    calls: list[StageRequest] = field(default_factory=list)

    def execute(self, request: StageRequest) -> StageOutput:
        """Fail on the named stage, otherwise report ten rows per dataset.

        Args:
            request: What to run.

        Returns:
            The reported rows, when it does not fail.

        Raises:
            StageExecutionError: On the named stage.
            Exception: Whatever ``raises`` holds, on the named stage.
        """
        self.calls.append(request)
        if request.stage.name == self.fails_on:
            if self.raises is not None:
                raise self.raises
            raise StageExecutionError(
                f"{request.stage.name} could not be generated",
                self.failure_type,
                cause="ValueError('bad row')",
            )
        return StageOutput(rows_by_dataset=dict.fromkeys(request.stage.produces, 10))

    @property
    def stage_ids(self) -> list[str]:
        """Return the identifiers of the stages executed, in order."""
        return [call.stage_id for call in self.calls]


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """Return a freshly created retail project."""
    return create_project(tmp_path / "shop", name="Shop", domain="retail", seed=42)


@pytest.fixture
def clock() -> SimulationClock:
    """Return a daily clock over 2024."""
    return create_clock(START, end=END)


@pytest.fixture
def one_tick() -> RunConfiguration:
    """Return a configuration that executes exactly one tick."""
    return RunConfiguration(stop_condition=AfterTicks(1))


@pytest.fixture
def run(project: Project, clock: SimulationClock, one_tick: RunConfiguration) -> SimulationRun:
    """Return a validated single-tick full run."""
    return create_run(project, clock, one_tick, run_id="r1")


def _kinds(report: ExecutionReport) -> list[str]:
    """Return the kind of each event in a report, in order.

    Args:
        report: The report.

    Returns:
        The event kinds.
    """
    return [event.kind for event in report.events]


def _imported_modules(source: Path) -> list[str]:
    """Return every module name a source file imports.

    Args:
        source: The file to read.

    Returns:
        The imported module names, from both import forms.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    return names


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------


def test_a_run_executes_every_stage_in_the_plan_s_order(run: SimulationRun) -> None:
    """P002 already decided the order; the scheduler never reorders."""
    executor = RecordingExecutor()

    report = execute(run, executor)

    assert executor.stage_ids == list(RETAIL_STAGES)
    assert report.result.stage_ids == RETAIL_STAGES
    assert report.succeeded


def test_the_result_records_every_stage(run: SimulationRun) -> None:
    """One result per planned stage, whatever happened to it."""
    report = execute(run, RecordingExecutor())

    assert report.result.completed_stages == RETAIL_STAGES
    assert report.result.status is ExecutionStatus.COMPLETED
    assert report.result.failure is None


def test_rows_are_aggregated_from_what_the_executor_reported(run: SimulationRun) -> None:
    """The scheduler counts nothing itself; it records what it was told."""
    report = execute(run, RecordingExecutor(rows=7))

    master = report.result.stage("retail:master-data")

    assert set(master.rows_by_dataset) == set(run.plan["master-data"].produces)
    assert all(count == 7 for count in master.rows_by_dataset.values())


def test_an_executor_s_warnings_reach_the_result(run: SimulationRun) -> None:
    """A stage's warnings belong to that stage, and are reachable from the run."""
    warning = ExecutionWarning("products", "low_volume", "fewer than expected")

    report = execute(run, RecordingExecutor(warnings=(warning,)))

    assert report.result.stage("retail:journey").warnings == (warning,)
    assert report.result.all_warnings.count(warning) == len(RETAIL_STAGES)


def test_the_executor_is_told_what_it_needs(run: SimulationRun, project: Project) -> None:
    """Six facts, all of them from the run the scheduler was handed."""
    executor = RecordingExecutor()

    execute(run, executor)

    first = executor.calls[0]
    assert first.stage.name == "master-data"
    assert first.simulation_date == START
    assert first.run_id == "r1"
    assert first.project_id == project.project_id
    assert first.seed == 42
    assert first.data_directory == project.workspace.data_directory


def test_the_report_carries_progress(run: SimulationRun) -> None:
    """A caller wanting a proportion rather than a narrative."""
    report = execute(run, RecordingExecutor())

    assert report.progress.completed_stages == 4
    assert report.progress.total_stages == 4
    assert report.progress.completed_ticks == 1
    assert report.progress.total_ticks == 1
    assert report.progress.is_complete


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_two_executions_of_one_run_are_identical(run: SimulationRun) -> None:
    """The property everything else rests on."""
    first = execute(run, RecordingExecutor())
    second = execute(run, RecordingExecutor())

    assert first.result == second.result
    assert first.events == second.events
    assert first.result.to_document() == second.result.to_document()


def test_sequence_numbers_are_contiguous_from_zero(run: SimulationRun) -> None:
    """Assigned as events are emitted, and execution is sequential."""
    report = execute(run, RecordingExecutor())

    assert [event.sequence for event in report.events] == list(range(len(report.events)))


def test_the_stream_is_already_in_sequence_order(run: SimulationRun) -> None:
    """Nothing arrives late, because nothing runs concurrently."""
    report = execute(run, RecordingExecutor())

    assert in_sequence(report.events) == report.events


def test_no_result_carries_wall_clock_time(run: SimulationRun) -> None:
    """Two executions a second apart produce equal documents."""
    first = execute(run, RecordingExecutor()).result.to_document()
    second = execute(run, RecordingExecutor()).result.to_document()

    assert first == second


# --------------------------------------------------------------------------
# Event ordering
# --------------------------------------------------------------------------


def test_the_event_stream_brackets_every_stage(run: SimulationRun) -> None:
    """Started and completed, in that order, around each stage."""
    report = execute(run, RecordingExecutor())

    assert _kinds(report) == (
        ["run_started"]
        + ["stage_started", "stage_completed"] * len(RETAIL_STAGES)
        + ["run_completed"]
    )


def test_a_stage_s_events_name_the_stage_and_its_rows(run: SimulationRun) -> None:
    """Events are readable on their own, without the result beside them."""
    report = execute(run, RecordingExecutor(rows=5))

    started = [e for e in report.events if isinstance(e, StageStarted)]
    completed = [e for e in report.events if isinstance(e, StageCompleted)]

    assert [event.stage_id for event in started] == list(RETAIL_STAGES)
    assert [event.stage_id for event in completed] == list(RETAIL_STAGES)
    assert all(event.rows > 0 for event in completed)


def test_the_run_events_bracket_everything(run: SimulationRun) -> None:
    """A stream begins with a start and ends with an outcome."""
    report = execute(run, RecordingExecutor())

    assert isinstance(report.events[0], RunStarted)
    assert isinstance(report.events[-1], RunCompleted)
    assert report.events[0].stage_count == 4


def test_events_carry_the_tick_s_simulated_date(project: Project) -> None:
    """Every event in one tick shares a date; the clock does not move within one."""
    clock = create_clock(START, end=END, tick=MONTHLY)
    run = create_run(project, clock, RunConfiguration(stop_condition=AfterTicks(2)), run_id="r1")

    report = execute(run, RecordingExecutor())

    first_tick = [e for e in report.events if e.simulation_date == date(2024, 1, 1)]
    second_tick = [e for e in report.events if e.simulation_date == date(2024, 2, 1)]

    assert len(first_tick) == 9  # run_started plus four bracketed stages
    assert len(second_tick) == 9  # four bracketed stages plus run_completed


# --------------------------------------------------------------------------
# Clock advancement
# --------------------------------------------------------------------------


def test_the_clock_advances_between_ticks_and_not_within_one(project: Project) -> None:
    """A tick is one moment: every stage in it sees the same date."""
    clock = create_clock(START, end=END, tick=MONTHLY)
    run = create_run(project, clock, RunConfiguration(stop_condition=AfterTicks(3)), run_id="r1")
    executor = RecordingExecutor()

    execute(run, executor)

    assert executor.dates == (
        [date(2024, 1, 1)] * 4 + [date(2024, 2, 1)] * 4 + [date(2024, 3, 1)] * 4
    )


def test_the_run_s_own_clock_is_never_mutated(run: SimulationRun) -> None:
    """Advancing rebinds; the run stays where it was (PADR-010)."""
    execute(run, RecordingExecutor())

    assert run.clock.current_date == START


def test_the_clock_does_not_advance_past_the_last_executed_tick(project: Project) -> None:
    """So the last state written carries the date the work was done on."""
    clock = create_clock(START, end=date(2024, 1, 3))
    run = create_run(project, clock, run_id="r1")

    report = execute(run, RecordingExecutor())

    assert report.result.end_date == date(2024, 1, 3)
    assert project.read_state().current_date == date(2024, 1, 3)


def test_a_period_that_ends_stops_the_run(project: Project) -> None:
    """The default stop condition, honoured without an explicit tick count."""
    clock = create_clock(START, end=date(2024, 1, 4))
    run = create_run(project, clock, run_id="r1")
    executor = RecordingExecutor()

    report = execute(run, executor)

    assert report.progress.completed_ticks == 4
    assert report.progress.total_ticks == 4
    assert len(executor.calls) == 16


def test_a_fixed_tick_count_stops_the_run(project: Project, clock: SimulationClock) -> None:
    """Three passes of the plan, on three consecutive simulated days."""
    run = create_run(project, clock, RunConfiguration(stop_condition=AfterTicks(3)), run_id="r1")

    report = execute(run, RecordingExecutor())

    assert report.progress.completed_ticks == 3
    assert report.result.end_date == date(2024, 1, 3)


def test_stopping_after_a_stage_stops_part_way_through_a_tick(
    project: Project, clock: SimulationClock
) -> None:
    """Naming an early stage is only useful if the rest do not run."""
    configuration = RunConfiguration(stop_condition=AfterStage("customers"))
    run = create_run(project, clock, configuration, run_id="r1")
    executor = RecordingExecutor()

    report = execute(run, executor)

    assert executor.stage_ids == ["retail:master-data", "retail:customers"]
    assert report.result.completed_stages == ("retail:master-data", "retail:customers")
    assert report.result.cancelled_stages == ("retail:journey", "retail:commerce")
    assert report.succeeded


def test_a_multi_tick_stage_gets_one_result_spanning_the_ticks(project: Project) -> None:
    """A run may not hold two results for one stage, which is why it has two dates."""
    clock = create_clock(START, end=END, tick=MONTHLY)
    run = create_run(project, clock, RunConfiguration(stop_condition=AfterTicks(3)), run_id="r1")

    report = execute(run, RecordingExecutor(rows=10))

    master = report.result.stage("retail:master-data")

    assert master.start_date == date(2024, 1, 1)
    assert master.end_date == date(2024, 3, 1)
    assert master.duration_days == 61
    assert all(count == 30 for count in master.rows_by_dataset.values())


# --------------------------------------------------------------------------
# Persistence timing
# --------------------------------------------------------------------------


def test_state_is_written_after_each_successful_stage(
    project: Project, clock: SimulationClock, one_tick: RunConfiguration
) -> None:
    """Progress survives an interruption at any point."""
    seen: list[tuple[str, ...]] = []

    class Watching:
        """Records what state says at the moment each stage begins."""

        def execute(self, request: StageRequest) -> StageOutput:
            del request
            seen.append(project.read_state().completed_stages)
            return StageOutput()

    execute(create_run(project, clock, one_tick, run_id="r1"), Watching())

    assert seen == [
        (),
        ("retail:master-data",),
        ("retail:master-data", "retail:customers"),
        ("retail:master-data", "retail:customers", "retail:journey"),
    ]


def test_a_failed_stage_is_never_recorded_as_completed(
    project: Project, clock: SimulationClock, one_tick: RunConfiguration
) -> None:
    """Recording it would make a resume skip work that never finished."""
    run = create_run(project, clock, one_tick, run_id="r1")

    execute(run, FailingExecutor(fails_on="journey"))

    assert project.read_state().completed_stages == ("retail:master-data", "retail:customers")


def test_the_simulated_date_is_persisted_with_the_progress(
    project: Project, clock: SimulationClock
) -> None:
    """A resume needs both: which stages, and when."""
    run = create_run(project, clock, RunConfiguration(stop_condition=AfterTicks(5)), run_id="r1")

    execute(run, RecordingExecutor())

    assert project.read_state().current_date == date(2024, 1, 5)


def test_a_stage_running_on_many_ticks_is_recorded_once(project: Project) -> None:
    """P003 refuses a stage recorded twice; the record answers 'has it ever completed'."""
    clock = create_clock(START, end=END, tick=MONTHLY)
    run = create_run(project, clock, RunConfiguration(stop_condition=AfterTicks(4)), run_id="r1")

    execute(run, RecordingExecutor())

    assert project.read_state().completed_stages == RETAIL_STAGES


def test_the_scheduler_writes_state_through_the_project(
    project: Project, clock: SimulationClock, one_tick: RunConfiguration
) -> None:
    """It never touches a store and never serialises anything (PADR-009)."""
    run = create_run(project, clock, one_tick, run_id="r1")

    execute(run, RecordingExecutor())

    assert project.store.exists("state")
    assert project.read_state().completed_stages == RETAIL_STAGES


# --------------------------------------------------------------------------
# Failure
# --------------------------------------------------------------------------


def test_a_failure_stops_execution(run: SimulationRun) -> None:
    """Nothing after the failed stage runs."""
    executor = FailingExecutor(fails_on="journey")

    report = execute(run, executor)

    assert executor.stage_ids == ["retail:master-data", "retail:customers", "retail:journey"]
    assert not report.succeeded


def test_a_failure_is_reported_on_the_stage_and_on_the_run(run: SimulationRun) -> None:
    """A consumer reading only the run learns the reason without walking the stages."""
    report = execute(run, FailingExecutor(fails_on="journey", failure_type=FailureType.VALIDATION))

    assert report.result.status is ExecutionStatus.FAILED
    assert report.result.failed_stage == "retail:journey"
    assert report.result.failure is not None
    assert report.result.failure.failure_type is FailureType.VALIDATION
    assert report.result.failure.stage == "retail:journey"
    assert report.result.failure.cause == "ValueError('bad row')"


def test_the_stream_ends_with_a_stage_failure_and_a_run_failure(run: SimulationRun) -> None:
    """Both, because a consumer may be watching either level."""
    report = execute(run, FailingExecutor(fails_on="customers"))

    assert _kinds(report) == [
        "run_started",
        "stage_started",
        "stage_completed",
        "stage_started",
        "stage_failed",
        "run_failed",
    ]
    assert isinstance(report.events[-2], StageFailed)
    assert isinstance(report.events[-1], RunFailed)


def test_stages_that_never_ran_are_recorded_as_cancelled(run: SimulationRun) -> None:
    """So asking what happened to any planned stage gets an answer."""
    report = execute(run, FailingExecutor(fails_on="customers"))

    assert report.result.completed_stages == ("retail:master-data",)
    assert report.result.failed_stages == ("retail:customers",)
    assert report.result.cancelled_stages == ("retail:journey", "retail:commerce")


def test_a_cancelled_stage_emits_no_events(run: SimulationRun) -> None:
    """It never started, so nothing may say it did."""
    report = execute(run, FailingExecutor(fails_on="customers"))

    started = {e.stage_id for e in report.events if isinstance(e, StageStarted)}

    assert "retail:journey" not in started


def test_an_unclassifiable_error_is_reported_as_internal(run: SimulationRun) -> None:
    """An exception the platform cannot name is a defect, not a condition."""
    report = execute(run, FailingExecutor(fails_on="journey", raises=RuntimeError("boom")))

    assert report.result.failure is not None
    assert report.result.failure.failure_type is FailureType.INTERNAL
    assert report.result.failure.cause == "RuntimeError('boom')"


def test_a_failed_run_still_reports_what_succeeded(run: SimulationRun) -> None:
    """Work that finished is work that exists."""
    report = execute(run, FailingExecutor(fails_on="journey", failure_type=FailureType.PERSISTENCE))

    assert report.result.total_rows > 0
    assert report.progress.completed_stages == 2
    assert report.progress.total_stages == 4


def test_a_failure_does_not_raise(run: SimulationRun) -> None:
    """A failed run is an outcome; two ways to ask one question is one too many."""
    report = execute(run, FailingExecutor(fails_on="master-data"))

    assert isinstance(report, ExecutionReport)
    assert report.result.status is ExecutionStatus.FAILED


def test_a_failure_stops_the_tick_loop(project: Project, clock: SimulationClock) -> None:
    """No retries, no recovery, no next tick."""
    run = create_run(project, clock, RunConfiguration(stop_condition=AfterTicks(10)), run_id="r1")
    executor = FailingExecutor(fails_on="customers")

    report = execute(run, executor)

    assert len(executor.calls) == 2
    assert report.progress.completed_ticks == 1


# --------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------


def test_a_dry_run_calls_no_executor(project: Project, clock: SimulationClock) -> None:
    """The guarantee is structural. Delegating it to an executor would not be one."""
    run = create_run(project, clock, RunConfiguration(dry_run=True), run_id="r1")
    executor = RecordingExecutor()

    report = execute(run, executor)

    assert executor.calls == []
    assert report.succeeded


def test_a_dry_run_writes_no_state(project: Project, clock: SimulationClock) -> None:
    """Nothing happened, so nothing is recorded as having happened."""
    run = create_run(project, clock, RunConfiguration(dry_run=True), run_id="r1")

    execute(run, RecordingExecutor())

    assert not project.has_state()


def test_a_dry_run_records_every_stage_as_skipped(project: Project, clock: SimulationClock) -> None:
    """And the contracts then forbid it from claiming any rows (PADR-012)."""
    run = create_run(project, clock, RunConfiguration(dry_run=True), run_id="r1")

    report = execute(run, RecordingExecutor())

    assert report.result.skipped_stages == RETAIL_STAGES
    assert report.result.total_rows == 0
    assert report.result.status is ExecutionStatus.COMPLETED


def test_a_dry_run_emits_no_stage_events(project: Project, clock: SimulationClock) -> None:
    """A StageCompleted is what change capture reads as a change boundary.

    Emitting one for work that did not happen would put a change boundary
    where nothing changed, which is a concrete harm rather than a tidiness
    question.
    """
    run = create_run(project, clock, RunConfiguration(dry_run=True), run_id="r1")

    report = execute(run, RecordingExecutor())

    assert _kinds(report) == ["run_started", "run_completed"]


def test_a_dry_run_is_marked_as_one_in_the_result(project: Project, clock: SimulationClock) -> None:
    """Otherwise a rehearsal and a fully-resumed run look identical."""
    run = create_run(project, clock, RunConfiguration(dry_run=True), run_id="r1")

    report = execute(run, RecordingExecutor())

    assert [warning.rule for warning in report.result.warnings] == ["dry_run"]


def test_a_dry_run_makes_one_pass_however_long_the_period(
    project: Project, clock: SimulationClock
) -> None:
    """The answer to "what would run" is the same on every tick."""
    run = create_run(project, clock, RunConfiguration(dry_run=True), run_id="r1")

    report = execute(run, RecordingExecutor())

    assert report.progress.completed_ticks == 1
    assert report.progress.total_ticks == 1


def test_any_mode_can_be_rehearsed(project: Project, clock: SimulationClock) -> None:
    """The combination a fourth run mode would have made inexpressible (PADR-011)."""
    project.write_state(SimulationState(completed_stages=("retail:master-data",)))
    configuration = RunConfiguration(mode=RunMode.RESUME, dry_run=True)

    report = execute(create_run(project, clock, configuration, run_id="r1"), RecordingExecutor())

    assert report.succeeded
    assert report.result.skipped_stages == RETAIL_STAGES


# --------------------------------------------------------------------------
# Resume
# --------------------------------------------------------------------------


def test_a_resume_runs_only_what_is_outstanding(project: Project, clock: SimulationClock) -> None:
    """Deciding what is outstanding belongs to P005; the scheduler asks."""
    project.write_state(
        SimulationState(completed_stages=("retail:master-data", "retail:customers"))
    )
    configuration = RunConfiguration(mode=RunMode.RESUME, stop_condition=AfterTicks(1))
    executor = RecordingExecutor()

    execute(create_run(project, clock, configuration, run_id="r1"), executor)

    assert executor.stage_ids == ["retail:journey", "retail:commerce"]


def test_a_resume_leaves_earlier_progress_recorded(
    project: Project, clock: SimulationClock
) -> None:
    """It adds to the record; it does not replace it."""
    project.write_state(SimulationState(completed_stages=("retail:master-data",)))
    configuration = RunConfiguration(mode=RunMode.RESUME, stop_condition=AfterTicks(1))

    execute(create_run(project, clock, configuration, run_id="r1"), RecordingExecutor())

    assert project.read_state().completed_stages == RETAIL_STAGES


def test_a_resume_only_honours_the_record_on_its_first_tick(project: Project) -> None:
    """Resuming means picking up where it stopped, then carrying on normally."""
    project.write_state(
        SimulationState(
            completed_stages=("retail:master-data", "retail:customers", "retail:journey")
        )
    )
    clock = create_clock(START, end=END, tick=MONTHLY)
    configuration = RunConfiguration(mode=RunMode.RESUME, stop_condition=AfterTicks(2))
    executor = RecordingExecutor()

    execute(create_run(project, clock, configuration, run_id="r1"), executor)

    assert executor.stage_ids == ["retail:commerce", *RETAIL_STAGES]


def test_a_resumed_run_starts_at_the_recorded_tick(project: Project) -> None:
    """started_tick is a clock position, and a resume does not begin at zero."""
    reached = create_clock(START, end=END, tick=MONTHLY).advance(4)
    project.write_state(state_with_clock(project.read_state(), reached))
    configuration = RunConfiguration(stop_condition=AfterTicks(1))

    report = execute(create_run(project, reached, configuration, run_id="r1"), RecordingExecutor())

    assert report.result.started_tick == 4
    assert report.result.start_date == date(2024, 5, 1)


def test_an_interrupted_run_can_be_finished_by_a_resume(
    project: Project, clock: SimulationClock, one_tick: RunConfiguration
) -> None:
    """The lifecycle the whole persistence design exists for."""
    first = execute(
        create_run(project, clock, one_tick, run_id="r1"), FailingExecutor(fails_on="journey")
    )

    assert first.result.failed_stage == "retail:journey"

    resumed = RunConfiguration(mode=RunMode.RESUME, stop_condition=AfterTicks(1))
    executor = RecordingExecutor()
    second = execute(create_run(project, clock, resumed, run_id="r2"), executor)

    assert executor.stage_ids == ["retail:journey", "retail:commerce"]
    assert second.succeeded
    assert project.read_state().completed_stages == RETAIL_STAGES


# --------------------------------------------------------------------------
# Targeted execution
# --------------------------------------------------------------------------


def test_a_targeted_run_executes_the_narrowed_plan(
    project: Project, clock: SimulationClock
) -> None:
    """Narrowing belongs to P002; the scheduler runs whatever plan it is given."""
    configuration = RunConfiguration(
        mode=RunMode.TARGETED, targets=("journey",), stop_condition=AfterTicks(1)
    )
    executor = RecordingExecutor()

    report = execute(create_run(project, clock, configuration, run_id="r1"), executor)

    assert executor.stage_ids == ["retail:master-data", "retail:customers", "retail:journey"]
    assert report.result.stage_ids == (
        "retail:master-data",
        "retail:customers",
        "retail:journey",
    )


def test_a_supplied_plan_is_executed_as_given(
    project: Project, clock: SimulationClock, one_tick: RunConfiguration
) -> None:
    """The plan is consumed exactly as P002 produced it, never inferred."""
    plan = plan_domain("retail", targets=["customers"])
    run = create_run(project, clock, one_tick, plan=plan, run_id="r1")
    executor = RecordingExecutor()

    execute(run, executor)

    assert executor.stage_ids == ["retail:master-data", "retail:customers"]


# --------------------------------------------------------------------------
# Refusing a run
# --------------------------------------------------------------------------


def test_an_incoherent_run_is_refused_before_anything_starts(
    tmp_path: Path, clock: SimulationClock
) -> None:
    """RunStarted asserts a run began; a run that never validated never began."""
    clinic = create_project(tmp_path / "clinic", name="Clinic", domain="healthcare")
    run = SimulationRun(run_id="r1", project=clinic, plan=plan_domain("retail"), clock=clock)
    executor = RecordingExecutor()

    report = execute(run, executor)

    assert executor.calls == []
    assert _kinds(report) == ["run_failed"]
    assert report.result.status is ExecutionStatus.FAILED
    assert report.result.failure is not None
    assert report.result.failure.failure_type is FailureType.CONFIGURATION
    assert "domain_mismatch" in report.result.failure.message


def test_a_refused_run_writes_no_state(tmp_path: Path, clock: SimulationClock) -> None:
    """Nothing ran, so nothing is recorded."""
    clinic = create_project(tmp_path / "clinic", name="Clinic", domain="healthcare")
    run = SimulationRun(run_id="r1", project=clinic, plan=plan_domain("retail"), clock=clock)

    execute(run, RecordingExecutor())

    assert not clinic.has_state()


def test_a_clock_disagreeing_with_state_refuses_the_run(project: Project) -> None:
    """The P005 rule that only a bound object could make, enforced at execution."""
    reached = create_clock(START, end=END).advance(40)
    project.write_state(state_with_clock(project.read_state(), reached))
    run = SimulationRun(
        run_id="r1", project=project, plan=plan_domain("retail"), clock=create_clock(START, end=END)
    )

    report = execute(run, RecordingExecutor())

    assert report.result.failure is not None
    assert "clock_state_mismatch" in report.result.failure.message


def test_every_disagreement_reaches_the_failure_message(
    tmp_path: Path, clock: SimulationClock
) -> None:
    """One round-trip per fix is how a five-minute problem becomes an afternoon."""
    clinic = create_project(tmp_path / "clinic", name="Clinic", domain="healthcare")
    clinic.workspace.data_directory.rmdir()
    run = SimulationRun(run_id="r1", project=clinic, plan=plan_domain("retail"), clock=clock)

    report = execute(run, RecordingExecutor())

    assert report.result.failure is not None
    assert "missing_data_directory" in report.result.failure.message
    assert "unknown_domain" in report.result.failure.message


# --------------------------------------------------------------------------
# Architectural constraints
# --------------------------------------------------------------------------


def test_the_scheduler_knows_no_domain() -> None:
    """The executor is an argument precisely so this stays true."""
    banned = ("polars", "eds.domains", "eds.adapters", "threading", "asyncio", "logging")
    for source in SCHEDULER_ROOT.rglob("*.py"):
        for imported in _imported_modules(source):
            assert not imported.startswith(banned), f"{source.name} imports {imported}"


def test_the_scheduler_never_reads_the_wall_clock() -> None:
    """Simulated time is the only time it knows about."""
    banned = ("now", "today", "utcnow", "sleep", "monotonic", "perf_counter")
    for source in SCHEDULER_ROOT.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in banned, f"{source.name} calls {node.func.attr}()"


@pytest.mark.parametrize("package", ["project", "execution", "time", "run", "runtime"])
def test_no_earlier_module_depends_on_the_scheduler(package: str) -> None:
    """P002 to P005.1 are frozen, and none of them was touched."""
    for source in (PACKAGE_ROOT / "platform" / package).rglob("*.py"):
        for imported in _imported_modules(source):
            assert not imported.startswith("eds.platform.scheduler"), (
                f"{source.name} imports {imported}"
            )


def test_no_domain_knows_that_a_scheduler_exists() -> None:
    """A domain declares what it generates; being scheduled is not its business."""
    for source in (PACKAGE_ROOT / "domains").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "eds.platform.scheduler" not in text, f"{source.name} reaches into the scheduler"


def test_a_fake_executor_satisfies_the_protocol() -> None:
    """The seam is a protocol, so nothing has to be subclassed to be executable."""
    assert isinstance(RecordingExecutor(), StageExecutor)
    assert isinstance(FailingExecutor(fails_on="x"), StageExecutor)


def test_the_scheduler_is_small() -> None:
    """A future reader should be surprised by how little code it contains.

    Asserted rather than hoped for. If orchestration grows past this, the
    growth is almost certainly a responsibility that belongs to another
    module, and this test is where that conversation starts.
    """
    source = (SCHEDULER_ROOT / "scheduler.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    statements = sum(
        1 for node in ast.walk(tree) if isinstance(node, ast.stmt) and not _is_documentation(node)
    )

    assert statements < 220, f"the scheduler has grown to {statements} statements"


def _is_documentation(node: ast.stmt) -> bool:
    """Report whether a statement is a docstring rather than logic.

    Args:
        node: The statement.

    Returns:
        Whether it is a bare string expression.
    """
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
