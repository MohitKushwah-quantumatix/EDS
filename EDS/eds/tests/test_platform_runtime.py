"""Architecture tests for the runtime contracts (P005.1).

These describe a vocabulary, not a behaviour. Nothing here executes a stage,
advances a clock or schedules anything - if a test in this module needed a
scheduler, the contracts would have grown a responsibility they were denied.

Three properties get the most attention. That a contract cannot contradict
itself: a failed result always carries its failure, a completed run never holds
a failed stage, no stage appears twice. That every contract round-trips through
a document unchanged, since a result nobody can store is a result nobody can
compare. And that no contract carries wall-clock time, which is what makes two
runs of one simulation produce equal results.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from eds.platform.runtime import (
    EXECUTION_EVENT_KINDS,
    STATUS_TRANSITIONS,
    TERMINAL_STATUSES,
    ExecutionEvent,
    ExecutionStatus,
    ExecutionWarning,
    Failure,
    FailureType,
    InvalidStatusTransitionError,
    Progress,
    RunCompleted,
    RunFailed,
    RunResult,
    RunStarted,
    RuntimeContractError,
    StageCompleted,
    StageFailed,
    StageResult,
    StageStarted,
    execution_event_from_document,
    in_sequence,
    is_valid_transition,
    require_valid_transition,
)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_ROOT = PACKAGE_ROOT / "platform" / "runtime"

DAY_ONE = date(2024, 1, 1)
DAY_TWO = date(2024, 1, 2)


@pytest.fixture
def failure() -> Failure:
    """Return a validation failure attached to a stage."""
    return Failure(
        failure_type=FailureType.VALIDATION,
        message="orders failed referential integrity",
        stage="retail:commerce",
        cause="ValidationError('12 orphan references')",
    )


@pytest.fixture
def completed_stage() -> StageResult:
    """Return a stage that produced two datasets."""
    return StageResult(
        stage_id="retail:master-data",
        status=ExecutionStatus.COMPLETED,
        start_date=DAY_ONE,
        end_date=DAY_ONE,
        rows_by_dataset={"products": 500, "brands": 20},
    )


@pytest.fixture
def failed_stage(failure: Failure) -> StageResult:
    """Return a stage that failed."""
    return StageResult(
        stage_id="retail:commerce",
        status=ExecutionStatus.FAILED,
        start_date=DAY_ONE,
        end_date=DAY_TWO,
        failure=failure,
    )


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
# Status model
# --------------------------------------------------------------------------


def test_one_status_vocabulary_covers_runs_and_stages() -> None:
    """Two enums differing by one member would be a name without a distinction."""
    assert [status.value for status in ExecutionStatus] == [
        "pending",
        "running",
        "completed",
        "failed",
        "skipped",
        "cancelled",
    ]


def test_only_four_statuses_are_terminal() -> None:
    """Pending and running describe work in flight, so no result may hold them."""
    assert set(TERMINAL_STATUSES) == {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.SKIPPED,
        ExecutionStatus.CANCELLED,
    }
    assert not ExecutionStatus.PENDING.is_terminal
    assert not ExecutionStatus.RUNNING.is_terminal


def test_a_skipped_stage_counts_as_successful() -> None:
    """A resume passing over completed work has not gone wrong."""
    assert ExecutionStatus.COMPLETED.is_successful
    assert ExecutionStatus.SKIPPED.is_successful
    assert not ExecutionStatus.FAILED.is_successful
    assert not ExecutionStatus.CANCELLED.is_successful


@pytest.mark.parametrize(
    ("current", "following"),
    [
        (ExecutionStatus.PENDING, ExecutionStatus.RUNNING),
        (ExecutionStatus.PENDING, ExecutionStatus.SKIPPED),
        (ExecutionStatus.PENDING, ExecutionStatus.CANCELLED),
        (ExecutionStatus.RUNNING, ExecutionStatus.COMPLETED),
        (ExecutionStatus.RUNNING, ExecutionStatus.FAILED),
        (ExecutionStatus.RUNNING, ExecutionStatus.CANCELLED),
    ],
)
def test_the_legal_transitions(current: ExecutionStatus, following: ExecutionStatus) -> None:
    """A resume skips a pending stage; a cancellation can arrive at any point."""
    assert is_valid_transition(current, following)
    require_valid_transition(current, following)


@pytest.mark.parametrize(
    ("current", "following"),
    [
        (ExecutionStatus.PENDING, ExecutionStatus.COMPLETED),
        (ExecutionStatus.RUNNING, ExecutionStatus.PENDING),
        (ExecutionStatus.RUNNING, ExecutionStatus.SKIPPED),
        (ExecutionStatus.COMPLETED, ExecutionStatus.RUNNING),
    ],
)
def test_the_illegal_transitions(current: ExecutionStatus, following: ExecutionStatus) -> None:
    """A stage cannot complete without running, nor be skipped once started."""
    assert not is_valid_transition(current, following)
    with pytest.raises(InvalidStatusTransitionError):
        require_valid_transition(current, following)


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
def test_nothing_follows_a_terminal_status(status: ExecutionStatus) -> None:
    """The message says so rather than listing an empty set of alternatives."""
    assert STATUS_TRANSITIONS[status] == frozenset()
    with pytest.raises(InvalidStatusTransitionError, match="is terminal"):
        require_valid_transition(status, ExecutionStatus.RUNNING)


def test_an_illegal_transition_says_what_would_have_worked() -> None:
    """A caller whose lifecycle model is wrong needs to be told the right one."""
    with pytest.raises(
        InvalidStatusTransitionError, match=r"allowed: \['cancelled', 'completed', 'failed'\]"
    ):
        require_valid_transition(ExecutionStatus.RUNNING, ExecutionStatus.PENDING)


def test_every_status_appears_in_the_transition_table() -> None:
    """A status with no declared row would raise KeyError rather than answer."""
    assert set(STATUS_TRANSITIONS) == set(ExecutionStatus)


def test_a_transition_error_is_a_contract_error() -> None:
    """One base class, and it is a ValueError like the rest of the platform."""
    assert issubclass(InvalidStatusTransitionError, RuntimeContractError)
    assert issubclass(RuntimeContractError, ValueError)


# --------------------------------------------------------------------------
# Failures and warnings
# --------------------------------------------------------------------------


def test_the_failure_taxonomy_follows_a_stage_s_phases() -> None:
    """Derived from this architecture rather than from a generic severity model."""
    assert [member.value for member in FailureType] == [
        "configuration",
        "generation",
        "validation",
        "persistence",
        "dependency",
        "internal",
    ]


def test_a_failure_holds_text_not_an_exception(failure: Failure) -> None:
    """A traceback survives neither a document nor another machine."""
    assert isinstance(failure.cause, str)
    assert not any(
        isinstance(getattr(failure, name.name), BaseException)
        for name in dataclasses.fields(failure)
    )


def test_a_failure_may_be_about_the_run_rather_than_a_stage() -> None:
    """A configuration failure happens before any stage exists."""
    run_level = Failure(FailureType.CONFIGURATION, "the domain is not registered")

    assert run_level.stage is None
    assert str(run_level) == "[<run>] configuration: the domain is not registered"


def test_a_failure_that_explains_nothing_is_rejected() -> None:
    """A failure whose whole content is its type cannot be acted on."""
    with pytest.raises(RuntimeContractError, match="must carry a message"):
        Failure(FailureType.INTERNAL, "   ")


def test_a_blank_stage_on_a_failure_is_rejected() -> None:
    """Absent means run-level; blank means somebody passed the wrong thing."""
    with pytest.raises(RuntimeContractError, match="or None, not blank"):
        Failure(FailureType.GENERATION, "boom", stage="  ")


def test_a_failure_reads_readably(failure: Failure) -> None:
    """Failures appear in log lines and in error messages."""
    assert str(failure) == (
        "[retail:commerce] validation: orders failed referential integrity "
        "(caused by ValidationError('12 orphan references'))"
    )


def test_a_failure_round_trips(failure: Failure) -> None:
    """A stored result is only as good as the failure inside it."""
    assert Failure.from_document(failure.to_document()) == failure


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"failure_type": "catastrophe", "message": "x"}, "is not one of"),
        ({"message": "x"}, "is not one of"),
        ({"failure_type": "internal"}, "must be a string"),
        ({"failure_type": "internal", "message": "x", "stage": 7}, "must be a string or null"),
        ({"failure_type": "internal", "message": "x", "cause": []}, "must be a string or null"),
    ],
)
def test_a_corrupt_failure_document_is_rejected(document: dict[str, Any], message: str) -> None:
    """A stored document can hold anything, so each field is checked."""
    with pytest.raises(RuntimeContractError, match=message):
        Failure.from_document(document)


def test_a_warning_uses_the_platform_s_issue_shape() -> None:
    """The same subject/rule/detail as every other issue type in the platform."""
    warning = ExecutionWarning("shipments", "empty_dataset", "no rows were produced")

    assert str(warning) == "[shipments] empty_dataset: no rows were produced"
    assert ExecutionWarning.from_document(warning.to_document()) == warning


def test_a_warning_about_the_whole_run_still_renders() -> None:
    """An empty subject reads as the run rather than as a blank."""
    assert str(ExecutionWarning("", "slow", "took a while")) == "[<run>] slow: took a while"


@pytest.mark.parametrize("blank", ["rule", "detail"])
def test_a_warning_that_cannot_be_counted_is_rejected(blank: str) -> None:
    """A machine-readable rule is what lets a consumer filter without parsing English."""
    fields = {"subject": "x", "rule": "r", "detail": "d"} | {blank: "  "}

    with pytest.raises(RuntimeContractError, match="must carry"):
        ExecutionWarning(**fields)


# --------------------------------------------------------------------------
# Stage results
# --------------------------------------------------------------------------


def test_a_stage_result_aggregates_its_rows(completed_stage: StageResult) -> None:
    """What a consumer asks a stage result for."""
    assert completed_stage.total_rows == 520
    assert completed_stage.datasets == ("brands", "products")
    assert completed_stage.is_successful


def test_a_single_day_stage_covers_one_day(completed_stage: StageResult) -> None:
    """Both ends included, so a stage that began and ended today covers a day."""
    assert completed_stage.duration_days == 1


def test_a_multi_day_stage_counts_both_ends(failed_stage: StageResult) -> None:
    """1 January to 2 January is two days, not one."""
    assert failed_stage.duration_days == 2


@pytest.mark.parametrize("status", [ExecutionStatus.PENDING, ExecutionStatus.RUNNING])
def test_a_result_refuses_an_in_flight_status(status: ExecutionStatus) -> None:
    """A result records something that finished; the rest is a scheduler's business."""
    with pytest.raises(RuntimeContractError, match="records something that finished"):
        StageResult("retail:journey", status, DAY_ONE, DAY_ONE)


def test_a_failed_stage_must_say_why() -> None:
    """A status without its reason loses the only thing worth reporting."""
    with pytest.raises(RuntimeContractError, match="must carry the failure"):
        StageResult("retail:journey", ExecutionStatus.FAILED, DAY_ONE, DAY_ONE)


def test_a_stage_that_did_not_fail_may_not_carry_a_failure(failure: Failure) -> None:
    """The other direction, so the record cannot tell two stories."""
    with pytest.raises(RuntimeContractError, match="must not carry a failure"):
        StageResult("retail:journey", ExecutionStatus.COMPLETED, DAY_ONE, DAY_ONE, failure=failure)


def test_a_stage_result_must_name_its_stage() -> None:
    """An unnamed result cannot be matched to anything."""
    with pytest.raises(RuntimeContractError, match="must name its stage"):
        StageResult("  ", ExecutionStatus.COMPLETED, DAY_ONE, DAY_ONE)


def test_a_stage_that_ends_before_it_starts_is_rejected() -> None:
    """Almost always the two dates the wrong way round."""
    with pytest.raises(RuntimeContractError, match="before it starts"):
        StageResult("retail:journey", ExecutionStatus.COMPLETED, DAY_TWO, DAY_ONE)


@pytest.mark.parametrize("status", [ExecutionStatus.SKIPPED, ExecutionStatus.CANCELLED])
def test_a_stage_that_never_ran_produced_nothing(status: ExecutionStatus) -> None:
    """Rows on a skipped stage mean the producer is recording two different things."""
    with pytest.raises(RuntimeContractError, match="cannot have produced rows"):
        StageResult("retail:journey", status, DAY_ONE, DAY_ONE, {"sessions": 10})


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ({"orders": -1}, "cannot be negative"),
        ({"  ": 5}, "must name the dataset"),
        ({"orders": "5"}, "must be an integer"),
        ({"orders": True}, "must be an integer"),
    ],
)
def test_impossible_row_counts_are_rejected(rows: dict[str, Any], message: str) -> None:
    """Including ``True``, which is an integer only by accident of history."""
    with pytest.raises(RuntimeContractError, match=message):
        StageResult("retail:journey", ExecutionStatus.COMPLETED, DAY_ONE, DAY_ONE, rows)


def test_a_stage_result_round_trips(failed_stage: StageResult) -> None:
    """Including its failure, which is the part most worth keeping."""
    assert StageResult.from_document(failed_stage.to_document()) == failed_stage


def test_a_stage_result_document_is_stable(completed_stage: StageResult) -> None:
    """Datasets are sorted, so dict order cannot reach a stored document."""
    document = completed_stage.to_document()

    assert document == completed_stage.to_document()
    assert list(document["rows_by_dataset"]) == ["brands", "products"]


# --------------------------------------------------------------------------
# Run results
# --------------------------------------------------------------------------


def test_a_run_result_aggregates_its_stages(
    completed_stage: StageResult, failed_stage: StageResult, failure: Failure
) -> None:
    """The reason a run result exists rather than a bare list of stages."""
    result = RunResult(
        run_id="r1",
        project_id="p1",
        status=ExecutionStatus.FAILED,
        start_date=DAY_ONE,
        end_date=DAY_TWO,
        started_tick=0,
        finished_tick=1,
        stages=(completed_stage, failed_stage),
        failure=failure,
    )

    assert result.completed_stages == ("retail:master-data",)
    assert result.failed_stages == ("retail:commerce",)
    assert result.failed_stage == "retail:commerce"
    assert result.total_rows == 520
    assert result.rows_by_dataset == {"brands": 20, "products": 500}
    assert result.ticks_elapsed == 1
    assert result.duration_days == 2
    assert not result.is_successful


def test_rows_are_summed_across_stages_not_replaced() -> None:
    """Two stages may write to one dataset; the total is what a consumer means."""
    stages = tuple(
        StageResult(
            f"retail:s{index}",
            ExecutionStatus.COMPLETED,
            DAY_ONE,
            DAY_ONE,
            {"orders": 100},
        )
        for index in range(3)
    )
    result = RunResult("r1", "p1", ExecutionStatus.COMPLETED, DAY_ONE, DAY_ONE, stages=stages)

    assert result.rows_by_dataset == {"orders": 300}


def test_a_run_reports_stages_by_status(completed_stage: StageResult) -> None:
    """Every terminal status gets its own accessor, so nobody filters by hand."""
    skipped = StageResult("retail:customers", ExecutionStatus.SKIPPED, DAY_ONE, DAY_ONE)
    cancelled = StageResult("retail:journey", ExecutionStatus.CANCELLED, DAY_ONE, DAY_ONE)
    result = RunResult(
        "r1",
        "p1",
        ExecutionStatus.CANCELLED,
        DAY_ONE,
        DAY_ONE,
        stages=(completed_stage, skipped, cancelled),
    )

    assert result.completed_stages == ("retail:master-data",)
    assert result.skipped_stages == ("retail:customers",)
    assert result.cancelled_stages == ("retail:journey",)
    assert result.failed_stage is None


def test_a_run_result_finds_one_stage(completed_stage: StageResult) -> None:
    """Lookup by identifier, and a message when there is nothing to find."""
    result = RunResult(
        "r1", "p1", ExecutionStatus.COMPLETED, DAY_ONE, DAY_ONE, stages=(completed_stage,)
    )

    assert result.stage("retail:master-data") is completed_stage
    with pytest.raises(KeyError, match="no result for stage"):
        result.stage("retail:journey")


def test_warnings_from_every_level_are_reachable_together() -> None:
    """A consumer asking "what should I read?" should not have to walk the stages."""
    stage = StageResult(
        "retail:journey",
        ExecutionStatus.COMPLETED,
        DAY_ONE,
        DAY_ONE,
        warnings=(ExecutionWarning("sessions", "low_volume", "fewer than expected"),),
    )
    result = RunResult(
        "r1",
        "p1",
        ExecutionStatus.COMPLETED,
        DAY_ONE,
        DAY_ONE,
        stages=(stage,),
        warnings=(ExecutionWarning("", "narrow_period", "one day only"),),
    )

    assert [warning.rule for warning in result.all_warnings] == ["narrow_period", "low_volume"]


def test_warnings_do_not_make_a_run_unsuccessful() -> None:
    """Otherwise nobody could tell "it worked" from "it worked, and read this"."""
    result = RunResult(
        "r1",
        "p1",
        ExecutionStatus.COMPLETED,
        DAY_ONE,
        DAY_ONE,
        warnings=(ExecutionWarning("", "slow", "took a while"),),
    )

    assert result.is_successful


def test_a_run_is_never_skipped() -> None:
    """A stage may be passed over; a run cannot be."""
    with pytest.raises(RuntimeContractError, match="a run is never skipped"):
        RunResult("r1", "p1", ExecutionStatus.SKIPPED, DAY_ONE, DAY_ONE)


def test_a_completed_run_cannot_hold_a_failed_stage(failed_stage: StageResult) -> None:
    """The cross-check no single stage result could make."""
    with pytest.raises(RuntimeContractError, match="claims to have completed"):
        RunResult("r1", "p1", ExecutionStatus.COMPLETED, DAY_ONE, DAY_TWO, stages=(failed_stage,))


def test_a_stage_cannot_have_two_results(completed_stage: StageResult) -> None:
    """A duplicate means a lost write or a scheduler bug, and hides both."""
    with pytest.raises(RuntimeContractError, match="more than one result"):
        RunResult(
            "r1",
            "p1",
            ExecutionStatus.COMPLETED,
            DAY_ONE,
            DAY_ONE,
            stages=(completed_stage, completed_stage),
        )


@pytest.mark.parametrize(("run_id", "project_id"), [("", "p1"), ("r1", "   ")])
def test_a_run_result_must_carry_its_identifiers(run_id: str, project_id: str) -> None:
    """A result nobody can attribute is a result nobody can use."""
    with pytest.raises(RuntimeContractError, match="must carry a"):
        RunResult(run_id, project_id, ExecutionStatus.COMPLETED, DAY_ONE, DAY_ONE)


def test_ticks_that_run_backwards_are_rejected() -> None:
    """Finishing before it started means the producer counted two clocks."""
    with pytest.raises(RuntimeContractError, match="before the tick"):
        RunResult("r1", "p1", ExecutionStatus.COMPLETED, DAY_ONE, DAY_ONE, 10, 4)


def test_a_negative_starting_tick_is_rejected() -> None:
    """A resume starts at a positive tick; nothing starts at a negative one."""
    with pytest.raises(RuntimeContractError, match="started_tick cannot be negative"):
        RunResult("r1", "p1", ExecutionStatus.COMPLETED, DAY_ONE, DAY_ONE, -1, 0)


def test_a_run_that_ends_before_it_starts_is_rejected() -> None:
    """The same rule as a stage, at run level."""
    with pytest.raises(RuntimeContractError, match="before it starts"):
        RunResult("r1", "p1", ExecutionStatus.COMPLETED, DAY_TWO, DAY_ONE)


def test_a_resume_starts_at_a_non_zero_tick() -> None:
    """The case started_tick exists for."""
    result = RunResult("r1", "p1", ExecutionStatus.COMPLETED, DAY_ONE, DAY_TWO, 40, 41)

    assert result.ticks_elapsed == 1


def test_a_run_result_round_trips(
    completed_stage: StageResult, failed_stage: StageResult, failure: Failure
) -> None:
    """Unlike a SimulationRun, a result holds no handles, so it round-trips whole."""
    result = RunResult(
        "r1",
        "p1",
        ExecutionStatus.FAILED,
        DAY_ONE,
        DAY_TWO,
        0,
        1,
        (completed_stage, failed_stage),
        failure,
        (ExecutionWarning("", "narrow_period", "one day only"),),
    )

    assert RunResult.from_document(result.to_document()) == result


def test_two_results_of_the_same_run_are_equal(completed_stage: StageResult) -> None:
    """The property that makes a result worth storing, and that a timestamp would destroy."""
    first = RunResult(
        "r1", "p1", ExecutionStatus.COMPLETED, DAY_ONE, DAY_ONE, stages=(completed_stage,)
    )
    second = RunResult(
        "r1", "p1", ExecutionStatus.COMPLETED, DAY_ONE, DAY_ONE, stages=(completed_stage,)
    )

    assert first == second
    assert first.to_document() == second.to_document()


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"run_id": "r1"}, "must be a string"),
        ({"run_id": "r1", "project_id": "p1", "status": "elapsed"}, "is not one of"),
        (
            {"run_id": "r1", "project_id": "p1", "status": "completed", "start_date": "nope"},
            "ISO 8601",
        ),
        (
            {
                "run_id": "r1",
                "project_id": "p1",
                "status": "completed",
                "start_date": "2024-01-01",
                "end_date": "2024-01-01",
                "started_tick": 0,
                "finished_tick": 0,
                "stages": ["not an object"],
            },
            "must be an object",
        ),
        (
            {
                "run_id": "r1",
                "project_id": "p1",
                "status": "completed",
                "start_date": "2024-01-01",
                "end_date": "2024-01-01",
                "started_tick": 0,
                "finished_tick": 0,
                "failure": "boom",
            },
            "must be an object or null",
        ),
    ],
)
def test_a_corrupt_run_result_document_is_rejected(document: dict[str, Any], message: str) -> None:
    """Validation applies to what was read, not only to what was constructed."""
    with pytest.raises(RuntimeContractError, match=message):
        RunResult.from_document(document)


def test_a_run_result_reads_readably(
    completed_stage: StageResult, failed_stage: StageResult, failure: Failure
) -> None:
    """Results appear in log lines."""
    result = RunResult(
        "r1",
        "p1",
        ExecutionStatus.FAILED,
        DAY_ONE,
        DAY_TWO,
        0,
        1,
        (completed_stage, failed_stage),
        failure,
    )

    assert str(result) == "run r1 failed: 1/2 stages, 520 rows, 1 tick(s)"


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


def test_the_events_are_a_closed_set() -> None:
    """A consumer matches on every kind, so producers may not add any."""
    assert EXECUTION_EVENT_KINDS == (
        "run_started",
        "stage_started",
        "stage_completed",
        "stage_failed",
        "run_completed",
        "run_failed",
    )


def test_no_event_carries_wall_clock_time(failure: Failure) -> None:
    """The property that makes an event stream a fact rather than a recording."""
    events = _every_event(failure)

    for event in events:
        fields = {name.name for name in dataclasses.fields(event)}
        assert "timestamp" not in fields and "started_at" not in fields
        assert "simulation_date" in fields
        assert isinstance(event.simulation_date, date)


def test_events_order_by_sequence_not_arrival(failure: Failure) -> None:
    """Concurrent stages at one level finish when they finish."""
    events = _every_event(failure)
    shuffled = (events[3], events[0], events[5], events[1], events[4], events[2])

    assert in_sequence(shuffled) == events


def test_ordering_is_stable_for_a_shared_sequence() -> None:
    """Events given the same number keep the order they were given in."""
    first = StageStarted(1, "r1", DAY_ONE, "retail:a")
    second = StageStarted(1, "r1", DAY_ONE, "retail:b")

    assert in_sequence((first, second)) == (first, second)


def test_an_unfinished_stage_has_an_event_and_no_result() -> None:
    """The case a result cannot express, and the reason events exist beside results.

    A stage that started and never finished leaves a ``StageStarted`` with
    nothing after it. There is no ``StageResult`` for it at all, because a
    result records something that finished.
    """
    stream: tuple[ExecutionEvent, ...] = (
        RunStarted(0, "r1", DAY_ONE, stage_count=2),
        StageStarted(1, "r1", DAY_ONE, "retail:master-data"),
    )
    started = {event.stage_id for event in stream if isinstance(event, StageStarted)}
    completed = {event.stage_id for event in stream if isinstance(event, StageCompleted)}

    assert started - completed == {"retail:master-data"}


@pytest.mark.parametrize("sequence", [-1, -100])
def test_an_event_outside_a_stream_is_rejected(sequence: int) -> None:
    """A negative position cannot be ordered against anything."""
    with pytest.raises(RuntimeContractError, match="sequence cannot be negative"):
        RunStarted(sequence, "r1", DAY_ONE)


def test_an_event_must_name_its_run() -> None:
    """Two streams read together would otherwise be indistinguishable."""
    with pytest.raises(RuntimeContractError, match="must name the run"):
        RunStarted(0, "  ", DAY_ONE)


def test_a_stage_event_must_name_its_stage() -> None:
    """Same reasoning, one level down."""
    with pytest.raises(RuntimeContractError, match="must name its stage"):
        StageStarted(1, "r1", DAY_ONE, "   ")


def test_a_completion_event_cannot_report_negative_rows() -> None:
    """A count that could not have been produced."""
    with pytest.raises(RuntimeContractError, match="row count cannot be negative"):
        StageCompleted(2, "r1", DAY_ONE, "retail:journey", rows=-1)


def test_a_negative_stage_count_is_rejected() -> None:
    """A plan cannot hold fewer than no stages."""
    with pytest.raises(RuntimeContractError, match="stage_count cannot be negative"):
        RunCompleted(9, "r1", DAY_ONE, stage_count=-2)


def test_every_event_round_trips(failure: Failure) -> None:
    """The closed set is closed under serialisation too."""
    for event in _every_event(failure):
        assert execution_event_from_document(event.to_document()) == event, event.kind


def test_every_event_reads_readably(failure: Failure) -> None:
    """Events appear in log lines, one per line, so each must stand alone."""
    rendered = [str(event) for event in _every_event(failure)]

    assert rendered == [
        "#0 run r1 started with 2 stage(s)",
        "#1 stage retail:master-data started",
        "#2 stage retail:master-data completed with 520 row(s)",
        "#3 stage retail:commerce failed: orders failed referential integrity",
        "#4 run r1 completed 1 stage(s)",
        "#5 run r1 failed: orders failed referential integrity",
    ]


def test_an_unknown_event_kind_is_rejected_with_the_known_ones() -> None:
    """The message says what would have worked."""
    with pytest.raises(RuntimeContractError, match="is not one of"):
        execution_event_from_document(
            {"kind": "stage_paused", "sequence": 0, "run_id": "r1", "simulation_date": "2024-01-01"}
        )


def test_a_failure_event_must_carry_its_failure() -> None:
    """An event saying a stage failed without saying why looks like information."""
    with pytest.raises(RuntimeContractError, match="must carry a failure"):
        execution_event_from_document(
            {
                "kind": "run_failed",
                "sequence": 0,
                "run_id": "r1",
                "simulation_date": "2024-01-01",
            }
        )


# --------------------------------------------------------------------------
# Progress
# --------------------------------------------------------------------------


def test_progress_reports_what_is_left() -> None:
    """Four numbers, and everything else derived from them."""
    progress = Progress(completed_stages=1, total_stages=4, completed_ticks=30, total_ticks=366)

    assert progress.remaining_stages == 3
    assert progress.remaining_ticks == 336
    assert progress.stage_percentage == 25.0
    assert round(progress.tick_percentage or 0, 2) == 8.2
    assert not progress.is_complete


def test_progress_on_an_open_ended_run_has_no_tick_percentage() -> None:
    """None rather than zero: there is no denominator, and zero would be a lie."""
    progress = Progress(completed_stages=2, total_stages=4, completed_ticks=900)

    assert progress.total_ticks is None
    assert progress.remaining_ticks is None
    assert progress.tick_percentage is None
    assert progress.stage_percentage == 50.0


def test_progress_over_an_empty_plan_has_no_stage_percentage() -> None:
    """Nought out of nought is not nought per cent."""
    assert Progress().stage_percentage is None
    assert not Progress().is_complete


def test_progress_reports_completion() -> None:
    """The check a consumer makes to stop rendering a bar."""
    assert Progress(completed_stages=4, total_stages=4).is_complete


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"completed_stages": -1}, "cannot be negative"),
        ({"total_stages": -1}, "cannot be negative"),
        ({"completed_ticks": -1}, "cannot be negative"),
        ({"total_ticks": -1}, "cannot be negative"),
        ({"completed_stages": 5, "total_stages": 4}, "out of 4"),
        ({"completed_ticks": 10, "total_ticks": 5}, "out of 5"),
    ],
)
def test_impossible_progress_is_rejected(kwargs: dict[str, int], message: str) -> None:
    """Progress past 100% means the producer is counting two different things."""
    with pytest.raises(RuntimeContractError, match=message):
        Progress(**kwargs)


def test_progress_round_trips() -> None:
    """Derived percentages are deliberately not stored."""
    progress = Progress(1, 4, 30, 366)

    document = progress.to_document()

    assert set(document) == {
        "completed_stages",
        "total_stages",
        "completed_ticks",
        "total_ticks",
    }
    assert Progress.from_document(document) == progress


def test_open_ended_progress_round_trips() -> None:
    """The null total must survive, not become a zero."""
    progress = Progress(0, 4, 12, None)

    assert Progress.from_document(progress.to_document()) == progress


def test_a_corrupt_progress_document_is_rejected() -> None:
    """A stored document can hold anything."""
    with pytest.raises(RuntimeContractError, match="must be an integer or null"):
        Progress.from_document(
            {
                "completed_stages": 0,
                "total_stages": 0,
                "completed_ticks": 0,
                "total_ticks": "many",
            }
        )


def test_progress_reads_readably() -> None:
    """Progress appears in a status line."""
    assert str(Progress(1, 4, 30, 366)) == "1/4 stages, 30/366 ticks"
    assert str(Progress(1, 4, 30)) == "1/4 stages, 30 ticks"


# --------------------------------------------------------------------------
# Immutability and equality
# --------------------------------------------------------------------------


def test_every_contract_is_frozen(failure: Failure, completed_stage: StageResult) -> None:
    """Contracts contain facts, and a fact that can be edited is not one."""
    values: list[Any] = [
        failure,
        ExecutionWarning("x", "y", "z"),
        completed_stage,
        RunResult("r1", "p1", ExecutionStatus.COMPLETED, DAY_ONE, DAY_ONE),
        Progress(),
        *_every_event(failure),
    ]

    for value in values:
        first = dataclasses.fields(value)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, first, None)


def test_a_contract_can_be_varied_by_replacement(completed_stage: StageResult) -> None:
    """The ordinary way to derive one: replace, never mutate."""
    cancelled = dataclasses.replace(
        completed_stage, status=ExecutionStatus.CANCELLED, rows_by_dataset={}
    )

    assert cancelled.status is ExecutionStatus.CANCELLED
    assert completed_stage.status is ExecutionStatus.COMPLETED


def test_replacement_still_validates(completed_stage: StageResult) -> None:
    """An invariant that could be bypassed by replace would not be an invariant."""
    with pytest.raises(RuntimeContractError, match="cannot have produced rows"):
        dataclasses.replace(completed_stage, status=ExecutionStatus.SKIPPED)


def test_equality_is_by_value(failure: Failure) -> None:
    """Two contracts describing the same fact are the same contract."""
    assert (
        Failure(
            FailureType.VALIDATION,
            "orders failed referential integrity",
            "retail:commerce",
            "ValidationError('12 orphan references')",
        )
        == failure
    )
    assert StageStarted(1, "r1", DAY_ONE, "retail:a") == StageStarted(1, "r1", DAY_ONE, "retail:a")


# --------------------------------------------------------------------------
# Architectural constraints
# --------------------------------------------------------------------------


def test_the_contracts_contain_no_behaviour() -> None:
    """P005.1 defines a vocabulary; it does not run, schedule, retry or dispatch."""
    # Note the trailing dot on the run package: without it the prefix would
    # also match this package's own modules, and the test would pass by
    # accident on a name collision rather than by checking anything.
    banned = (
        "polars",
        "eds.domains",
        "eds.adapters",
        "eds.platform.execution",
        "eds.platform.project",
        "eds.platform.run.",
        "threading",
        "asyncio",
        "logging",
    )
    for source in RUNTIME_ROOT.rglob("*.py"):
        for imported in _imported_modules(source):
            assert imported != "eds.platform.run", f"{source.name} imports the run model"
            assert not imported.startswith(banned), f"{source.name} imports {imported}"


def test_the_only_platform_dependency_is_the_date_vocabulary() -> None:
    """A stored result must be readable where no plan, project or clock exists."""
    allowed = {"eds.platform.time.dates"}
    for source in RUNTIME_ROOT.rglob("*.py"):
        for imported in _imported_modules(source):
            if imported.startswith("eds.") and not imported.startswith("eds.platform.runtime"):
                assert imported in allowed, f"{source.name} imports {imported}"


def test_the_contracts_never_read_the_wall_clock() -> None:
    """One ``datetime.now()`` would make two runs of one simulation incomparable."""
    banned = ("now", "today", "utcnow", "sleep", "monotonic", "perf_counter")
    for source in RUNTIME_ROOT.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in banned, f"{source.name} calls {node.func.attr}()"


@pytest.mark.parametrize("package", ["project", "execution", "time", "run"])
def test_no_earlier_module_depends_on_the_contracts(package: str) -> None:
    """P002 to P005 are frozen and unchanged; only a scheduler will join them."""
    for source in (PACKAGE_ROOT / "platform" / package).rglob("*.py"):
        for imported in _imported_modules(source):
            assert not imported.startswith("eds.platform.runtime"), (
                f"{source.name} imports {imported}"
            )


def test_no_domain_knows_that_runtime_contracts_exist() -> None:
    """A domain declares what it generates; being executed is not its business."""
    for source in (PACKAGE_ROOT / "domains").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "eds.platform.runtime" not in text, f"{source.name} reaches into the contracts"


@pytest.mark.parametrize(
    "name",
    [
        "eds.platform.runtime",
        "eds.platform.runtime.documents",
        "eds.platform.runtime.errors",
        "eds.platform.runtime.events",
        "eds.platform.runtime.failure",
        "eds.platform.runtime.progress",
        "eds.platform.runtime.results",
        "eds.platform.runtime.status",
    ],
)
def test_runtime_modules_are_importable_and_documented(name: str) -> None:
    """Every module in the package imports cleanly and states its purpose."""
    module = importlib.import_module(name)

    assert module.__doc__ is not None
    assert module.__doc__.strip()


def _every_event(failure: Failure) -> tuple[Any, ...]:
    """Return one of each event kind, in sequence order.

    Args:
        failure: The failure the two failure events carry.

    Returns:
        Six events, numbered zero to five.
    """
    return (
        RunStarted(0, "r1", DAY_ONE, stage_count=2),
        StageStarted(1, "r1", DAY_ONE, "retail:master-data"),
        StageCompleted(2, "r1", DAY_ONE, "retail:master-data", rows=520),
        StageFailed(3, "r1", DAY_TWO, "retail:commerce", failure),
        RunCompleted(4, "r1", DAY_TWO, stage_count=1),
        RunFailed(5, "r1", DAY_TWO, failure),
    )
