"""Architecture tests for the simulation run model (P005).

A run's job is to notice that its parts disagree, so most of this module is
about disagreement: a plan for the wrong domain, a clock in the wrong place, a
target that is not a stage, a stop condition that can never fire.

Two properties get the most attention. First, that a run built by
``create_run`` cannot be incoherent - that is the guarantee a scheduler will
rely on when it takes one argument instead of six. Second, that the dependency
runs strictly one way: the run knows about P002, P003 and P004, and none of
them knows about the run.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
from datetime import date
from pathlib import Path

import pytest

import eds.domains.retail  # noqa: F401  - registers the domain the tests plan against
from eds.platform.execution import ExecutionPlan, PlannedStage, plan_domain
from eds.platform.project import Project, SimulationState, create_project
from eds.platform.run import (
    STOP_CONDITION_KINDS,
    AfterStage,
    AfterTicks,
    EndOfPeriod,
    RunConfiguration,
    RunError,
    RunIssue,
    RunMode,
    RunValidationError,
    SimulationRun,
    create_run,
    stop_condition_from_document,
)
from eds.platform.time import (
    MONTHLY,
    BusinessCalendar,
    SimulationClock,
    create_clock,
    state_with_clock,
)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
RUN_ROOT = PACKAGE_ROOT / "platform" / "run"

START = date(2024, 1, 1)
END = date(2024, 12, 31)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """Return a freshly created retail project."""
    return create_project(tmp_path / "shop", name="Shop", domain="retail", seed=42)


@pytest.fixture
def clock() -> SimulationClock:
    """Return a daily clock over 2024."""
    return create_clock(START, end=END)


@pytest.fixture
def run(project: Project, clock: SimulationClock) -> SimulationRun:
    """Return a validated full run of the retail project."""
    return create_run(project, clock)


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
# Run modes
# --------------------------------------------------------------------------


def test_the_modes_answer_which_stages_only() -> None:
    """Three modes, because 'which stages' has three answers.

    Dry run is not among them: it answers whether anything is written, which
    is an independent question, so it is a field rather than a fourth member
    (PADR-011).
    """
    assert [mode.value for mode in RunMode] == ["full", "targeted", "resume"]


def test_only_a_targeted_run_takes_targets() -> None:
    """Naming stages is what makes a run targeted."""
    assert RunMode.TARGETED.accepts_targets
    assert not RunMode.FULL.accepts_targets
    assert not RunMode.RESUME.accepts_targets


def test_any_mode_can_be_rehearsed() -> None:
    """The combination four modes would have made inexpressible."""
    rehearsals = [
        RunConfiguration(mode=RunMode.FULL, dry_run=True),
        RunConfiguration(mode=RunMode.RESUME, dry_run=True),
        RunConfiguration(mode=RunMode.TARGETED, targets=("journey",), dry_run=True),
    ]

    assert all(configuration.dry_run for configuration in rehearsals)


# --------------------------------------------------------------------------
# Stop conditions
# --------------------------------------------------------------------------


def test_the_stop_conditions_are_a_closed_set() -> None:
    """A scheduler must interpret every one, so callers may not add any."""
    assert STOP_CONDITION_KINDS == ("end_of_period", "after_ticks", "after_stage")


@pytest.mark.parametrize(
    ("condition", "rendered"),
    [
        (EndOfPeriod(), "at the end of the simulated period"),
        (AfterTicks(30), "after 30 tick(s)"),
        (AfterStage("commerce"), "after the 'commerce' stage"),
    ],
)
def test_a_stop_condition_reads_readably(condition: object, rendered: str) -> None:
    """Conditions appear in run summaries and error messages."""
    assert str(condition) == rendered


@pytest.mark.parametrize("count", [0, -1])
def test_a_run_that_stops_after_no_ticks_is_rejected(count: int) -> None:
    """A run that stops after zero ticks is a run nobody wanted."""
    with pytest.raises(ValueError, match="at least 1"):
        AfterTicks(count)


def test_a_non_integer_tick_count_is_rejected() -> None:
    """Including ``True``, which is an integer only by accident of history."""
    with pytest.raises(ValueError, match="must be an integer"):
        AfterTicks(True)


def test_a_stop_condition_naming_no_stage_is_rejected() -> None:
    """A blank stage name cannot be matched against a plan."""
    with pytest.raises(ValueError, match="requires a stage name"):
        AfterStage("   ")


@pytest.mark.parametrize(
    "condition",
    [EndOfPeriod(), AfterTicks(12), AfterStage("commerce")],
)
def test_every_stop_condition_round_trips(condition: object) -> None:
    """The closed set is closed under serialisation too."""
    document = condition.to_document()  # type: ignore[attr-defined]

    assert stop_condition_from_document(document) == condition


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"kind": "eventually"}, "is not one of"),
        ({}, "is not one of"),
        ({"kind": "after_ticks", "count": "12"}, "must be an integer"),
        ({"kind": "after_stage", "stage": None}, "must be a string"),
    ],
)
def test_a_corrupt_stop_condition_document_is_rejected(
    document: dict[str, object], message: str
) -> None:
    """A stored document can hold anything, so each field is checked."""
    with pytest.raises(ValueError, match=message):
        stop_condition_from_document(document)


# --------------------------------------------------------------------------
# Run configuration
# --------------------------------------------------------------------------


def test_the_default_configuration_is_a_full_run() -> None:
    """The ordinary case needs no arguments."""
    configuration = RunConfiguration()

    assert configuration.mode is RunMode.FULL
    assert configuration.targets == ()
    assert configuration.stop_condition == EndOfPeriod()
    assert not configuration.dry_run


def test_a_targeted_run_must_name_a_stage() -> None:
    """Otherwise it is a full run wearing the wrong label."""
    with pytest.raises(ValueError, match="must name at least one stage"):
        RunConfiguration(mode=RunMode.TARGETED)


@pytest.mark.parametrize("mode", [RunMode.FULL, RunMode.RESUME])
def test_only_a_targeted_run_may_name_stages(mode: RunMode) -> None:
    """'Everything' and 'these three' contradict each other."""
    with pytest.raises(ValueError, match="cannot name target stages"):
        RunConfiguration(mode=mode, targets=("journey",))


def test_a_blank_target_is_rejected() -> None:
    """A stage name that matches nothing would present as an unknown target."""
    with pytest.raises(ValueError, match="must not be blank"):
        RunConfiguration(mode=RunMode.TARGETED, targets=("  ",))


def test_a_repeated_target_is_rejected() -> None:
    """Naming a stage twice means the caller believes something untrue."""
    with pytest.raises(ValueError, match="named more than once"):
        RunConfiguration(mode=RunMode.TARGETED, targets=("journey", "journey"))


def test_a_configuration_round_trips_through_a_document() -> None:
    """The portable half of a run, which is what makes it a separate type."""
    configuration = RunConfiguration(
        mode=RunMode.TARGETED,
        targets=("customers", "journey"),
        stop_condition=AfterTicks(7),
        dry_run=True,
    )

    document = configuration.to_document()

    assert document == {
        "mode": "targeted",
        "targets": ["customers", "journey"],
        "stop_condition": {"kind": "after_ticks", "count": 7},
        "dry_run": True,
    }
    assert RunConfiguration.from_document(document) == configuration


def test_an_empty_document_reads_as_the_default_configuration() -> None:
    """Every field has a defensible default, so none of them is required."""
    assert RunConfiguration.from_document({}) == RunConfiguration()


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"mode": "partial"}, "is not one of"),
        ({"mode": 7}, "is not one of"),
        ({"targets": "journey"}, "must be a list"),
        ({"targets": [1]}, "must be a list"),
        ({"stop_condition": "end"}, "must be an object"),
        ({"dry_run": "yes"}, "must be true or false"),
        ({"mode": "full", "targets": ["journey"]}, "cannot name target stages"),
    ],
)
def test_a_corrupt_configuration_document_is_rejected(
    document: dict[str, object], message: str
) -> None:
    """Validation applies to what was read, not only to what was constructed."""
    with pytest.raises(ValueError, match=message):
        RunConfiguration.from_document(document)


def test_a_configuration_reads_readably() -> None:
    """Configurations appear in run summaries."""
    configuration = RunConfiguration(
        mode=RunMode.TARGETED, targets=("journey",), stop_condition=AfterTicks(3), dry_run=True
    )

    assert str(configuration) == "targeted run of ['journey'], stopping after 3 tick(s) (dry run)"


# --------------------------------------------------------------------------
# Run construction
# --------------------------------------------------------------------------


def test_a_run_binds_the_three_primitives(run: SimulationRun, clock: SimulationClock) -> None:
    """One object, holding what a scheduler would otherwise take separately."""
    assert isinstance(run.project, Project)
    assert isinstance(run.plan, ExecutionPlan)
    assert run.clock == clock
    assert run.configuration == RunConfiguration()


def test_a_run_derives_its_plan_from_the_project(run: SimulationRun) -> None:
    """Two inputs in, three bound together: that is what makes one argument enough."""
    assert run.domain == "retail"
    assert run.plan.stage_names == ("master-data", "customers", "journey", "commerce")


def test_a_targeted_run_narrows_the_derived_plan(project: Project, clock: SimulationClock) -> None:
    """The plan carries the targets and their dependencies, and nothing else."""
    configuration = RunConfiguration(mode=RunMode.TARGETED, targets=("journey",))

    run = create_run(project, clock, configuration)

    assert run.plan.stage_names == ("master-data", "customers", "journey")
    assert run.targets == ("journey",)


def test_a_supplied_plan_is_used_unchanged(project: Project, clock: SimulationClock) -> None:
    """A caller that already has a plan should not cause it to be rebuilt."""
    plan = plan_domain("retail", targets=["customers"])

    run = create_run(project, clock, plan=plan)

    assert run.plan is plan


def test_each_run_gets_its_own_identity(project: Project, clock: SimulationClock) -> None:
    """Two runs of one project with one configuration are still two runs."""
    first = create_run(project, clock)
    second = create_run(project, clock)

    assert first.run_id != second.run_id
    assert first.configuration == second.configuration


def test_an_identity_can_be_supplied(project: Project, clock: SimulationClock) -> None:
    """So that a test can produce the same run twice."""
    first = create_run(project, clock, run_id="fixed")
    second = create_run(project, clock, run_id="fixed")

    assert first == second


def test_a_run_exposes_what_a_scheduler_reads(run: SimulationRun) -> None:
    """Reaching through to the configuration for every field would read badly."""
    assert run.mode is RunMode.FULL
    assert run.targets == ()
    assert run.stop_condition == EndOfPeriod()
    assert not run.is_dry_run
    assert run.stages == run.plan.stages


def test_a_run_reads_readably(project: Project, clock: SimulationClock) -> None:
    """Runs appear in log lines, which is most of what a run_id is for."""
    run = create_run(project, clock, run_id="abc123")

    assert str(run) == (
        "run abc123 of 'Shop' (retail): full run, stopping at the end of the "
        "simulated period, from 2024-01-01"
    )


# --------------------------------------------------------------------------
# Immutability
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        RunConfiguration(),
        EndOfPeriod(),
        AfterTicks(3),
        AfterStage("commerce"),
        RunIssue("x", "y", "z"),
    ],
)
def test_every_run_value_is_frozen(value: object) -> None:
    """The run model is made of values, like everything else in the platform."""
    fields = dataclasses.fields(value)  # type: ignore[arg-type]
    if not fields:
        return  # EndOfPeriod carries no configuration; frozen-ness is untestable
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, fields[0].name, None)


def test_a_run_cannot_be_mutated(run: SimulationRun) -> None:
    """Binding is not the same as owning: a run configures, it does not evolve."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        run.clock = create_clock(START)  # type: ignore[misc]


def test_advancing_a_run_s_clock_leaves_the_run_alone(run: SimulationRun) -> None:
    """P004's immutability survives being held by something else."""
    later = run.clock.advance(10)

    assert run.clock.current_date == START
    assert later.current_date == date(2024, 1, 11)


def test_a_configuration_can_be_derived_rather_than_edited() -> None:
    """The ordinary way to vary one: replace, never mutate."""
    original = RunConfiguration()

    rehearsal = dataclasses.replace(original, dry_run=True)

    assert rehearsal.dry_run
    assert not original.dry_run


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def test_a_coherent_run_reports_nothing(run: SimulationRun) -> None:
    """The happy path."""
    assert run.validate() == []
    run.assert_valid()


def test_a_plan_for_another_domain_is_rejected(project: Project, clock: SimulationClock) -> None:
    """The check that only a bound object can make."""
    foreign = ExecutionPlan(domain="healthcare", stages=plan_domain("retail").stages)

    with pytest.raises(RunValidationError, match="domain_mismatch"):
        create_run(project, clock, plan=foreign)


def test_an_empty_plan_is_rejected(project: Project, clock: SimulationClock) -> None:
    """A run that would do nothing is a configuration mistake."""
    with pytest.raises(RunValidationError, match="empty_plan"):
        create_run(project, clock, plan=ExecutionPlan(domain="retail", stages=()))


def test_a_target_that_is_not_in_the_plan_is_rejected(
    project: Project, clock: SimulationClock
) -> None:
    """Caught against the plan, which the configuration alone cannot see."""
    configuration = RunConfiguration(mode=RunMode.TARGETED, targets=("commerce",))
    narrow = plan_domain("retail", targets=["customers"])

    with pytest.raises(RunValidationError, match="unknown_target"):
        create_run(project, clock, configuration, plan=narrow)


def test_a_project_whose_domain_is_not_installed_is_rejected(
    tmp_path: Path, clock: SimulationClock
) -> None:
    """The project's own issues are the run's issues too."""
    clinic = create_project(tmp_path / "clinic", name="Clinic", domain="healthcare")
    run = SimulationRun(run_id="r", project=clinic, plan=plan_domain("retail"), clock=clock)

    assert {issue.rule for issue in run.validate()} == {"unknown_domain", "domain_mismatch"}


def test_a_broken_workspace_is_reported(run: SimulationRun) -> None:
    """Forwarded from P003 rather than restated, so the rules stay in one place."""
    run.project.workspace.data_directory.rmdir()

    assert "missing_data_directory" in {issue.rule for issue in run.validate()}


def test_a_clock_disagreeing_with_persisted_state_is_rejected(
    project: Project, clock: SimulationClock
) -> None:
    """The check that catches a clock built for the wrong period.

    Nothing else in the platform can catch it: the clock is valid, the state
    is valid, and only a run sees both.
    """
    reached = create_clock(START, end=END).advance(40)
    project.write_state(state_with_clock(project.read_state(), reached))

    with pytest.raises(RunValidationError, match="clock_state_mismatch"):
        create_run(project, clock)


def test_a_clock_agreeing_with_persisted_state_is_accepted(project: Project) -> None:
    """Resuming where the project left off is the ordinary case."""
    reached = create_clock(START, end=END).advance(40)
    project.write_state(state_with_clock(project.read_state(), reached))

    run = create_run(project, reached, RunConfiguration(mode=RunMode.RESUME))

    assert run.clock.current_date == date(2024, 2, 10)


def test_a_resume_with_nothing_outstanding_is_rejected(
    project: Project, clock: SimulationClock
) -> None:
    """Resuming a finished project would do nothing, quietly."""
    plan = plan_domain("retail")
    project.write_state(SimulationState(completed_stages=plan.stage_ids))

    with pytest.raises(RunValidationError, match="nothing_to_resume"):
        create_run(project, clock, RunConfiguration(mode=RunMode.RESUME))


def test_a_full_run_over_a_finished_project_is_allowed(
    project: Project, clock: SimulationClock
) -> None:
    """Only a resume is obliged to have something outstanding."""
    project.write_state(SimulationState(completed_stages=plan_domain("retail").stage_ids))

    assert create_run(project, clock).validate() == []


def test_an_endless_run_with_no_end_is_rejected(project: Project) -> None:
    """Stopping at the end of a period that has no end can never happen."""
    with pytest.raises(RunValidationError, match="unreachable_stop_condition"):
        create_run(project, create_clock(START))


def test_an_open_ended_clock_is_fine_with_another_stop_condition(
    project: Project,
) -> None:
    """The period needs an end only because the default condition needs one."""
    configuration = RunConfiguration(stop_condition=AfterTicks(365))

    assert create_run(project, create_clock(START), configuration).validate() == []


def test_stopping_after_a_stage_that_will_not_run_is_rejected(
    project: Project, clock: SimulationClock
) -> None:
    """A condition naming a stage outside the plan would never fire."""
    configuration = RunConfiguration(stop_condition=AfterStage("commerce"))
    narrow = plan_domain("retail", targets=["customers"])

    with pytest.raises(RunValidationError, match="unknown_stop_stage"):
        create_run(project, clock, configuration, plan=narrow)


def test_unreadable_state_is_reported_not_raised(project: Project, clock: SimulationClock) -> None:
    """Validation is meant to explain a broken run, not fail while doing it."""
    (project.workspace.root / "state.json").write_text("{not json", encoding="utf-8")
    run = SimulationRun(run_id="r", project=project, plan=plan_domain("retail"), clock=clock)

    assert {issue.rule for issue in run.validate()} == {"unreadable_state"}


def test_every_disagreement_is_reported_at_once(tmp_path: Path) -> None:
    """One round-trip per fix is how a five-minute problem becomes an afternoon."""
    clinic = create_project(tmp_path / "clinic", name="Clinic", domain="healthcare")
    clinic.workspace.data_directory.rmdir()
    run = SimulationRun(
        run_id="r",
        project=clinic,
        plan=plan_domain("retail"),
        clock=create_clock(START),
        configuration=RunConfiguration(mode=RunMode.TARGETED, targets=("missing",)),
    )

    rules = {issue.rule for issue in run.validate()}

    assert rules == {
        "missing_data_directory",
        "unknown_domain",
        "domain_mismatch",
        "unknown_target",
        "unreachable_stop_condition",
    }


def test_constructing_a_run_directly_does_not_validate(
    tmp_path: Path, clock: SimulationClock
) -> None:
    """A caller diagnosing a broken run has to be able to hold one."""
    clinic = create_project(tmp_path / "clinic", name="Clinic", domain="healthcare")

    run = SimulationRun(run_id="r", project=clinic, plan=plan_domain("retail"), clock=clock)

    assert run.validate() != []


def test_an_issue_renders_readably() -> None:
    """Issues appear in error messages, so they must read well."""
    assert str(RunIssue("journey", "unknown_target", "not planned")) == (
        "[journey] unknown_target: not planned"
    )


def test_an_issue_about_the_whole_run_still_renders() -> None:
    """An empty subject reads as the run itself rather than as a blank."""
    assert str(RunIssue("", "empty_plan", "no stages")) == "[<run>] empty_plan: no stages"


def test_a_validation_error_without_issues_is_a_bug() -> None:
    """Raising with nothing to report is rejected."""
    with pytest.raises(ValueError, match="at least one issue"):
        RunValidationError(())


def test_the_validation_error_is_a_run_error() -> None:
    """One base class, so a caller can catch every run failure."""
    assert issubclass(RunValidationError, RunError)


# --------------------------------------------------------------------------
# Integration with P002, P003 and P004
# --------------------------------------------------------------------------


def test_a_run_reads_the_project_s_state_rather_than_caching_it(
    run: SimulationRun,
) -> None:
    """State changes as a run proceeds; a cached copy would go stale."""
    assert run.read_state().completed_stages == ()

    run.project.write_state(SimulationState(completed_stages=("retail:master-data",)))

    assert run.read_state().completed_stages == ("retail:master-data",)


def test_a_run_reports_what_is_outstanding(run: SimulationRun) -> None:
    """A description of what state says, not a decision about what to do."""
    run.project.write_state(
        SimulationState(completed_stages=("retail:master-data", "retail:customers"))
    )

    assert [stage.name for stage in run.remaining_stages()] == ["journey", "commerce"]


def test_outstanding_stages_ignore_the_mode(project: Project, clock: SimulationClock) -> None:
    """A full run may legitimately redo completed work; only a resume must not."""
    project.write_state(SimulationState(completed_stages=("retail:master-data",)))

    run = create_run(project, clock)

    assert [stage.name for stage in run.remaining_stages()] == [
        "customers",
        "journey",
        "commerce",
    ]


def test_a_run_carries_the_plan_s_dependency_levels(run: SimulationRun) -> None:
    """What a scheduler needs for concurrency comes through unchanged from P002."""
    assert run.plan.depth == 4
    assert all(isinstance(stage, PlannedStage) for stage in run.stages)


def test_a_run_carries_a_calendar_without_knowing_about_calendars(
    project: Project,
) -> None:
    """Tick policy lives on the clock, and the run does not restate it.

    P004 established that a tick's meaning comes from its unit and its
    calendar. Declaring either of them on the run as well would create two
    records of one fact.
    """
    clock = create_clock(START, end=END, tick=MONTHLY, calendar=BusinessCalendar())

    run = create_run(project, clock)

    assert run.clock.tick == MONTHLY
    assert run.clock.calendar.name == "business"
    assert not hasattr(run.configuration, "tick")


def test_a_run_summary_records_what_was_configured(project: Project) -> None:
    """The audit record. Deliberately one-way: a run cannot be rebuilt from it."""
    clock = create_clock(START, end=END, tick=MONTHLY)
    run = create_run(project, clock, RunConfiguration(dry_run=True), run_id="abc")

    document = run.to_document()

    assert document["run_id"] == "abc"
    assert document["project_id"] == project.project_id
    assert document["domain"] == "retail"
    assert document["current_date"] == "2024-01-01"
    assert document["tick"] == {"size": 1, "unit": "month"}
    assert document["time_range"] == {"start": "2024-01-01", "end": "2024-12-31"}
    assert document["calendar"] == "continuous"
    assert document["stage_ids"] == list(run.plan.stage_ids)
    assert document["configuration"] == run.configuration.to_document()


def test_the_run_model_offers_no_way_to_rebuild_a_run() -> None:
    """Stated as a test because its absence is the design, not an omission.

    A run holds a project handle and a calendar, neither of which is data.
    Offering ``from_document`` would mean inventing a way to resolve them,
    which is exactly the coupling the configuration/run split avoids.
    """
    assert not hasattr(SimulationRun, "from_document")
    assert hasattr(RunConfiguration, "from_document")


def test_the_same_configuration_serves_two_projects(tmp_path: Path) -> None:
    """The portable half is portable, which is why it is a separate type."""
    configuration = RunConfiguration(mode=RunMode.TARGETED, targets=("customers",))
    clock = create_clock(START, end=END)

    first = create_run(
        create_project(tmp_path / "a", name="A", domain="retail"), clock, configuration
    )
    second = create_run(
        create_project(tmp_path / "b", name="B", domain="retail"), clock, configuration
    )

    assert first.configuration is second.configuration
    assert first.project.project_id != second.project.project_id


# --------------------------------------------------------------------------
# Architectural constraints
# --------------------------------------------------------------------------


def test_the_run_model_introduces_no_runtime() -> None:
    """P005 binds and validates; it does not run, write, sleep or thread."""
    banned = ("polars", "eds.domains", "eds.adapters", "threading", "asyncio")
    for source in RUN_ROOT.rglob("*.py"):
        for imported in _imported_modules(source):
            assert not imported.startswith(banned), f"{source.name} imports {imported}"


def test_the_run_model_never_reads_the_wall_clock() -> None:
    """Simulated time is the only time a run knows about."""
    banned = ("now", "today", "utcnow", "sleep", "monotonic", "perf_counter")
    for source in RUN_ROOT.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in banned, f"{source.name} calls {node.func.attr}()"


@pytest.mark.parametrize("package", ["project", "execution", "time"])
def test_the_primitives_do_not_know_the_run_exists(package: str) -> None:
    """The dependency runs one way, which is what keeps the three reusable.

    P002, P003 and P004 are each usable without the others and without this
    package. Only the run depends on all three, and that is its entire job.
    """
    for source in (PACKAGE_ROOT / "platform" / package).rglob("*.py"):
        for imported in _imported_modules(source):
            assert not imported.startswith("eds.platform.run"), f"{source.name} imports {imported}"


def test_no_domain_knows_that_runs_exist() -> None:
    """A domain declares what it generates; being run is not its business."""
    for source in (PACKAGE_ROOT / "domains").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "eds.platform.run" not in text, f"{source.name} reaches into the run model"


def test_the_run_depends_on_all_three_primitives() -> None:
    """The positive half of the constraint: this is the module that binds them."""
    imported = {name for source in RUN_ROOT.rglob("*.py") for name in _imported_modules(source)}

    assert any(name.startswith("eds.platform.execution") for name in imported)
    assert any(name.startswith("eds.platform.project") for name in imported)
    assert any(name.startswith("eds.platform.time") for name in imported)


@pytest.mark.parametrize(
    "name",
    [
        "eds.platform.run",
        "eds.platform.run.configuration",
        "eds.platform.run.errors",
        "eds.platform.run.mode",
        "eds.platform.run.run",
        "eds.platform.run.stop",
    ],
)
def test_run_modules_are_importable_and_documented(name: str) -> None:
    """Every module in the package imports cleanly and states its purpose."""
    module = importlib.import_module(name)

    assert module.__doc__ is not None
    assert module.__doc__.strip()
