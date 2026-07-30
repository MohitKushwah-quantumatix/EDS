"""Turning declared stages into a validated execution plan.

The planner answers "what should run, and in what order?". It never answers
"run it" - it holds no callable, touches no adapter and creates no state
(PADR-008).

Implemented as functions rather than an ``ExecutionPlanner`` class, matching
the rest of the repository: a class with no state is a namespace with extra
steps. If planning ever acquires policy - a strictness setting, a parallelism
budget - that policy is what would justify an object, and it can be introduced
then without changing what callers pass.
"""

from __future__ import annotations

from collections.abc import Iterable

from eds.platform.domain import SimulationDomain, get_domain
from eds.platform.execution.graph import DependencyGraph
from eds.platform.execution.plan import ExecutionPlan, PlannedStage, stage_id
from eds.platform.execution.validation import assert_plannable

__all__ = ["build_execution_plan", "plan_domain"]


def _required_closure(graph: DependencyGraph, targets: tuple[str, ...]) -> set[str]:
    """Return the targets plus everything they transitively depend on.

    Args:
        graph: The derived graph.
        targets: The requested stage names.

    Returns:
        Every stage name that must run for the targets to be satisfiable.
    """
    needed: set[str] = set()
    pending = list(targets)
    while pending:
        name = pending.pop()
        if name in needed:
            continue
        needed.add(name)
        pending.extend(graph.dependencies_of(name))
    return needed


def build_execution_plan(
    domain: SimulationDomain, targets: Iterable[str] | None = None
) -> ExecutionPlan:
    """Build a validated execution plan for a domain.

    The plan is a pure function of the domain's declarations: the same
    declarations always produce the same plan, stage for stage and level for
    level.

    Args:
        domain: The domain to plan. Only its ``name`` and ``stages`` are read.
        targets: Stage names to plan for. When given, the plan contains those
            stages and everything they transitively depend on, and nothing
            else. When ``None``, every stage is planned.

    Returns:
        The ordered plan.

    Raises:
        PlanValidationError: If the stages cannot form a valid plan - a
            duplicate stage, an unsatisfiable requirement, a contested
            dataset, a cycle, an unknown target, or no stages at all.
    """
    stages = tuple(domain.stages)
    requested = tuple(targets) if targets is not None else None

    assert_plannable(stages, requested)

    graph = DependencyGraph.from_stages(stages)
    ordered = graph.topological_order()
    levels = graph.levels(ordered)

    if requested is not None:
        included = _required_closure(graph, requested)
        ordered = tuple(name for name in ordered if name in included)

    by_name = {stage.name: stage for stage in stages}
    planned = tuple(
        PlannedStage(
            stage_id=stage_id(domain.name, name),
            domain=domain.name,
            name=name,
            position=position,
            level=levels[name],
            requires=by_name[name].requires,
            produces=by_name[name].produces,
            depends_on=tuple(
                stage_id(domain.name, dependency) for dependency in graph.dependencies_of(name)
            ),
        )
        for position, name in enumerate(ordered)
    )
    return ExecutionPlan(domain=domain.name, stages=planned)


def plan_domain(name: str, targets: Iterable[str] | None = None) -> ExecutionPlan:
    """Build an execution plan for a registered domain, by name.

    Args:
        name: Registered domain name, such as ``"retail"``.
        targets: Stage names to plan for, or ``None`` for the whole domain.

    Returns:
        The ordered plan.

    Raises:
        KeyError: If no domain is registered under that name.
        PlanValidationError: If the domain's stages cannot form a valid plan.
    """
    return build_execution_plan(get_domain(name), targets)
