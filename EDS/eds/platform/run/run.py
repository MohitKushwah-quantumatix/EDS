"""The simulation run: one configured execution of one project.

**Why this type exists.** The platform has three primitives that were built
independently and are provably independent of each other: a plan says *what*
runs, a project says *whose* data it is and what has run already, and a clock
says *when*. Each is valid on its own. What none of them can check is whether
they agree - that this plan is for this project's domain, that this clock sits
where the project's state says it does, that a named target is a stage that
exists. Those are cross-object facts, so they need a place, and this is it.

The consequence is the one the design was chosen for: **a scheduler takes one
argument.** Not six, of which several must be consistent and none of which can
say so. Holding a run built by :func:`create_run` is a guarantee that its parts
agree, in the same way that holding an
:class:`~eds.platform.execution.plan.ExecutionPlan` is a guarantee that its
graph is acyclic (PADR-008).

**Nothing here executes.** The run holds no callable, opens nothing, writes
nothing and advances nothing. It validates and it describes. A scheduler reads
it and does the work; that scheduler does not exist (PADR-011).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from eds.platform.execution.plan import ExecutionPlan, PlannedStage
from eds.platform.execution.planner import build_execution_plan
from eds.platform.project.errors import StateStoreError
from eds.platform.project.project import Project
from eds.platform.project.state import SimulationState
from eds.platform.run.configuration import RunConfiguration
from eds.platform.run.errors import RunIssue, RunValidationError
from eds.platform.run.mode import RunMode
from eds.platform.run.stop import AfterStage, EndOfPeriod, StopCondition
from eds.platform.time.clock import SimulationClock

__all__ = ["SimulationRun", "create_run"]


@dataclass(frozen=True, slots=True)
class SimulationRun:
    """One configured execution of one project, bound but not started.

    Constructing this class directly does *not* validate, deliberately: a
    caller diagnosing a broken run needs to be able to hold one and ask it
    what is wrong. :func:`create_run` validates and is the ordinary way in.

    Attributes:
        run_id: Stable identifier for this run. Two runs of the same project
            with the same configuration are still two runs, and a scheduler
            recording progress needs to tell them apart.
        project: Whose simulation this is, and what it has done so far.
        plan: What runs, and in what order.
        clock: Where in simulated time the run begins.
        configuration: What was asked for - mode, targets, stop condition,
            whether it is a rehearsal.
    """

    run_id: str
    project: Project
    plan: ExecutionPlan
    clock: SimulationClock
    configuration: RunConfiguration = field(default_factory=RunConfiguration)

    def __str__(self) -> str:
        """Render the run for a log line."""
        return (
            f"run {self.run_id} of {self.project.name!r} ({self.domain}): "
            f"{self.configuration}, from {self.clock.current_date.isoformat()}"
        )

    @property
    def domain(self) -> str:
        """Return the domain being simulated, as the plan names it."""
        return self.plan.domain

    @property
    def mode(self) -> RunMode:
        """Return which stages the run is asking for."""
        return self.configuration.mode

    @property
    def targets(self) -> tuple[str, ...]:
        """Return the named target stages, empty unless the run is targeted."""
        return self.configuration.targets

    @property
    def stop_condition(self) -> StopCondition:
        """Return the criterion the run should stop on."""
        return self.configuration.stop_condition

    @property
    def is_dry_run(self) -> bool:
        """Report whether the run is a rehearsal that produces nothing."""
        return self.configuration.dry_run

    @property
    def stages(self) -> tuple[PlannedStage, ...]:
        """Return the planned stages, in execution order."""
        return self.plan.stages

    def read_state(self) -> SimulationState:
        """Read the project's persisted state.

        Offered so that a scheduler holding only a run does not have to reach
        through to the project for the one thing it always needs. It is a read
        every time, not a snapshot: state changes as a run proceeds, and a run
        that cached it would go stale the moment it was used.

        Returns:
            The project's state, empty if nothing has been recorded.

        Raises:
            CorruptDocumentError: If a state document exists but cannot be
                understood.
        """
        return self.project.read_state()

    def remaining_stages(self) -> tuple[PlannedStage, ...]:
        """Return the planned stages the project has not recorded as completed.

        A description, not a decision. It reports what state says regardless of
        mode, because a full run may legitimately redo completed work; whether
        to honour this is the scheduler's judgement, and only a resume is
        obliged to.

        Returns:
            The stages not present in the project's completed set, in
            execution order.

        Raises:
            CorruptDocumentError: If the state document cannot be understood.
        """
        completed = set(self.read_state().completed_stages)
        return tuple(stage for stage in self.plan.stages if stage.stage_id not in completed)

    def validate(self) -> list[RunIssue]:
        """Check that the run's parts describe a coherent execution.

        Every issue is returned rather than the first, because a
        misconfigured run usually has more than one thing wrong with it and
        fixing them one round-trip at a time is how a five-minute problem
        becomes an afternoon.

        Returns:
            Every issue found, in a deterministic order. Empty means the parts
            agree.
        """
        issues: list[RunIssue] = []
        issues.extend(self._project_issues())
        issues.extend(self._plan_issues())
        issues.extend(self._clock_issues())
        issues.extend(self._stop_condition_issues())
        return issues

    def assert_valid(self) -> None:
        """Validate the run and raise if its parts do not agree.

        Raises:
            RunValidationError: If any issue is found.
        """
        if issues := self.validate():
            raise RunValidationError(tuple(issues))

    def _project_issues(self) -> list[RunIssue]:
        """Return issues with the project, and with the plan's fit to it.

        Returns:
            The issues found.
        """
        issues = [
            RunIssue(subject=issue.subject, rule=issue.rule, detail=issue.detail)
            for issue in self.project.validate()
        ]
        if self.plan.domain != self.project.domain_name:
            issues.append(
                RunIssue(
                    subject=self.plan.domain,
                    rule="domain_mismatch",
                    detail=(
                        f"the plan is for domain {self.plan.domain!r} but the project "
                        f"simulates {self.project.domain_name!r}"
                    ),
                )
            )
        return issues

    def _plan_issues(self) -> list[RunIssue]:
        """Return issues with the plan and the stages the run names.

        Returns:
            The issues found.
        """
        issues: list[RunIssue] = []
        if not self.plan.stages:
            issues.append(
                RunIssue(
                    subject="",
                    rule="empty_plan",
                    detail="the plan contains no stages, so the run would do nothing",
                )
            )
        planned = set(self.plan.stage_names)
        for target in self.configuration.targets:
            if target not in planned:
                issues.append(
                    RunIssue(
                        subject=target,
                        rule="unknown_target",
                        detail=(
                            f"no stage named {target!r} is in the plan; "
                            f"planned: {list(self.plan.stage_names)}"
                        ),
                    )
                )
        return issues

    def _clock_issues(self) -> list[RunIssue]:
        """Return issues between the clock and what the project has recorded.

        Returns:
            The issues found.
        """
        try:
            state = self.read_state()
        except StateStoreError as exc:
            return [
                RunIssue(
                    subject="state",
                    rule="unreadable_state",
                    detail=f"the project's state could not be read: {exc}",
                )
            ]

        issues: list[RunIssue] = []
        if state.current_date is not None and self.clock.current_date < state.current_date:
            issues.append(
                RunIssue(
                    subject="clock",
                    rule="clock_state_mismatch",
                    detail=(
                        f"the clock is at {self.clock.current_date.isoformat()} but the "
                        f"project reached {state.current_date.isoformat()}; the clock was "
                        "probably built for an earlier period"
                    ),
                )
            )
        if self.configuration.mode is RunMode.RESUME:
            outstanding = set(self.plan.stage_ids) - set(state.completed_stages)
            if not outstanding:
                issues.append(
                    RunIssue(
                        subject="",
                        rule="nothing_to_resume",
                        detail=(
                            "every stage in the plan is already recorded as completed, "
                            "so a resume would do nothing"
                        ),
                    )
                )
        return issues

    def _stop_condition_issues(self) -> list[RunIssue]:
        """Return issues with a stop condition that could never be reached.

        Returns:
            The issues found.
        """
        condition = self.configuration.stop_condition
        if isinstance(condition, EndOfPeriod) and self.clock.is_open_ended:
            return [
                RunIssue(
                    subject="stop_condition",
                    rule="unreachable_stop_condition",
                    detail=(
                        "the run stops at the end of the simulated period, but the "
                        "clock's period has no end; give it an end, or stop after a "
                        "number of ticks or a stage"
                    ),
                )
            ]
        if isinstance(condition, AfterStage) and condition.stage not in self.plan.stage_names:
            return [
                RunIssue(
                    subject=condition.stage,
                    rule="unknown_stop_stage",
                    detail=(
                        f"the run stops after the {condition.stage!r} stage, which is not "
                        f"in the plan; planned: {list(self.plan.stage_names)}"
                    ),
                )
            ]
        return []

    def to_document(self) -> dict[str, object]:
        """Render the run as a record of what was configured.

        **This does not round-trip.** A run holds a project handle and a
        calendar, neither of which is data, so rebuilding one from a document
        is not possible and no ``from_document`` is offered. What this is for
        is the log line, the audit record and the test fixture - saying
        precisely what a run was, in a form that can be stored and compared.
        :class:`~eds.platform.run.configuration.RunConfiguration` is the part
        that *does* round-trip.

        Returns:
            A plain mapping of primitives.
        """
        return {
            "run_id": self.run_id,
            "project_id": self.project.project_id,
            "domain": self.domain,
            "configuration": self.configuration.to_document(),
            "current_date": self.clock.current_date.isoformat(),
            "tick": self.clock.tick.to_document(),
            "time_range": self.clock.time_range.to_document(),
            "calendar": self.clock.calendar.name,
            "stage_ids": list(self.plan.stage_ids),
        }


def create_run(
    project: Project,
    clock: SimulationClock,
    configuration: RunConfiguration | None = None,
    plan: ExecutionPlan | None = None,
    run_id: str | None = None,
) -> SimulationRun:
    """Bind a project, a plan and a clock into a validated run.

    The plan is derived from the project's domain when it is not supplied,
    narrowed to the configuration's targets. That is what lets a caller hand a
    scheduler one object built from two: a project and a clock.

    Args:
        project: Whose simulation this is.
        clock: Where in simulated time the run begins.
        configuration: What is being asked for. A full run stopping at the end
            of the period, when omitted.
        plan: What runs. Derived from the project's registered domain when
            omitted, which requires that domain to be registered.
        run_id: Stable identifier. Generated when omitted; supplied by a test
            that wants two identical runs.

    Returns:
        The run. Holding one means its parts have been checked against each
        other.

    Raises:
        RunValidationError: If the parts do not agree.
        KeyError: If the plan must be derived and the project's domain is not
            registered.
        PlanValidationError: If the domain's stages cannot form a valid plan.
    """
    settings = configuration if configuration is not None else RunConfiguration()
    resolved = (
        plan
        if plan is not None
        else build_execution_plan(project.domain(), settings.targets or None)
    )
    run = SimulationRun(
        run_id=run_id if run_id is not None else uuid4().hex,
        project=project,
        plan=resolved,
        clock=clock,
        configuration=settings,
    )
    run.assert_valid()
    return run
