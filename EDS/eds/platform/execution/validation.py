"""Validation of a stage set before it becomes a plan.

Implemented as functions returning issues, plus an assertion helper that
raises - the same shape every validator in this repository already has
(``validate_order_data`` / ``assert_valid_order_data``). A stateless
``ExecutionValidator`` class would be a namespace with extra steps, and would
be the only validator here shaped that way.

Every check answers a question a scheduler would otherwise discover the hard
way, at the point where half the pipeline has already run.
"""

from __future__ import annotations

from collections.abc import Iterable

from eds.platform.domain import DomainStage
from eds.platform.execution.errors import PlanningIssue, PlanValidationError
from eds.platform.execution.graph import DependencyGraph

__all__ = ["assert_plannable", "validate_stages"]


def _duplicate_stages(stages: tuple[DomainStage, ...]) -> list[PlanningIssue]:
    """Report stage names declared more than once.

    Args:
        stages: The declared stages.

    Returns:
        One issue per repeated name.
    """
    counts: dict[str, int] = {}
    for stage in stages:
        counts[stage.name] = counts.get(stage.name, 0) + 1
    return [
        PlanningIssue(
            stage=name,
            rule="duplicate_stage",
            detail=f"declared {count} times; stage names identify a stage and must be unique",
        )
        for name, count in counts.items()
        if count > 1
    ]


def _duplicate_producers(graph: DependencyGraph) -> list[PlanningIssue]:
    """Report datasets produced by more than one stage.

    Two stages writing one dataset is a race whichever way it is executed, and
    it makes the dependency edges ambiguous: a consumer would depend on both.

    Args:
        graph: The derived graph.

    Returns:
        One issue per contested dataset.
    """
    return [
        PlanningIssue(
            stage=", ".join(producers),
            rule="duplicate_producer",
            detail=f"dataset {dataset!r} is produced by {len(producers)} stages: {list(producers)}",
        )
        for dataset in graph.datasets
        if len(producers := graph.producers_of(dataset)) > 1
    ]


def _unknown_dependencies(graph: DependencyGraph) -> list[PlanningIssue]:
    """Report requirements nothing in the graph produces.

    Args:
        graph: The derived graph.

    Returns:
        One issue per unsatisfiable requirement.
    """
    return [
        PlanningIssue(
            stage=stage,
            rule="unknown_dependency",
            detail=f"requires dataset {dataset!r}, which no stage produces",
        )
        for stage, dataset in graph.unsatisfied_requirements()
    ]


def _cycles(graph: DependencyGraph) -> list[PlanningIssue]:
    """Report a dependency cycle, if one exists.

    Args:
        graph: The derived graph.

    Returns:
        A single issue naming one concrete cycle, or nothing.
    """
    cycle = graph.find_cycle()
    if not cycle:
        return []
    return [
        PlanningIssue(
            stage=cycle[0],
            rule="circular_dependency",
            detail="stages depend on each other in a cycle: " + " -> ".join(cycle),
        )
    ]


def _missing_targets(
    stages: tuple[DomainStage, ...], targets: Iterable[str] | None
) -> list[PlanningIssue]:
    """Report requested target stages the domain does not declare.

    Args:
        stages: The declared stages.
        targets: Requested target stage names, or ``None`` for all of them.

    Returns:
        One issue per unknown target.
    """
    if targets is None:
        return []
    known = {stage.name for stage in stages}
    return [
        PlanningIssue(
            stage=target,
            rule="missing_stage",
            detail=f"requested as a plan target but the domain declares no such stage; "
            f"declared: {sorted(known)}",
        )
        for target in targets
        if target not in known
    ]


def validate_stages(
    stages: tuple[DomainStage, ...], targets: Iterable[str] | None = None
) -> list[PlanningIssue]:
    """Check that a set of stages can form an execution plan.

    Args:
        stages: The declared stages, in declaration order.
        targets: Stage names the plan is being narrowed to, if any.

    Returns:
        Every issue found, in a deterministic order. Empty means the stages are
        plannable.
    """
    if not stages:
        return [
            PlanningIssue(
                stage="",
                rule="empty_graph",
                detail="the domain declares no stages, so there is nothing to plan",
            )
        ]

    issues = _duplicate_stages(stages)
    issues += _missing_targets(stages, targets)

    # A graph derived from duplicate names is ambiguous - two stages answer to
    # one key - so the structural checks below would report noise rather than
    # the real fault. Report the duplicates and stop.
    if any(issue.rule == "duplicate_stage" for issue in issues):
        return issues

    graph = DependencyGraph.from_stages(stages)
    issues += _duplicate_producers(graph)
    issues += _unknown_dependencies(graph)
    issues += _cycles(graph)
    return issues


def assert_plannable(stages: tuple[DomainStage, ...], targets: Iterable[str] | None = None) -> None:
    """Validate a set of stages and raise if it cannot be planned.

    Args:
        stages: The declared stages, in declaration order.
        targets: Stage names the plan is being narrowed to, if any.

    Raises:
        PlanValidationError: If any issue is found. The error carries all of
            them, not only the first.
    """
    if issues := validate_stages(stages, targets):
        raise PlanValidationError(tuple(issues))
