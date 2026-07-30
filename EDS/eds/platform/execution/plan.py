"""The execution plan.

A plan is an ordered, immutable answer to "what should run?". It is inert: it
holds no callables, opens nothing, and knows no storage format and no business
domain. Everything in it is a name or a number, which is what lets it be
compared between runs, logged, or handed to a component that does not exist
yet.

The plan is deliberately not a task queue. It has no notion of a stage being
started, finished or failed, because that is execution state and this module
does not execute (PADR-008).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

__all__ = ["ExecutionPlan", "PlannedStage", "stage_id"]


def stage_id(domain: str, stage: str) -> str:
    """Build the stable identifier for a stage.

    The identifier is qualified by domain so that plans from two domains can be
    logged, cached or merged without collision, and it is derived purely from
    names so that it is stable across runs, processes and machines.

    Args:
        domain: Domain name.
        stage: Stage name.

    Returns:
        The identifier, such as ``"retail:customers"``.
    """
    return f"{domain}:{stage}"


@dataclass(frozen=True, slots=True)
class PlannedStage:
    """One stage, placed in an execution plan.

    Attributes:
        stage_id: Stable identifier, ``"<domain>:<stage>"``.
        domain: The domain this stage belongs to.
        name: The stage's own name, matching its declaration.
        position: Zero-based index in the plan's execution order.
        level: Zero-based dependency depth. Stages sharing a level have no
            dependency between them.
        requires: Dataset names the stage reads.
        produces: Dataset names the stage writes.
        depends_on: Identifiers of the stages this one directly depends on.
    """

    stage_id: str
    domain: str
    name: str
    position: int
    level: int
    requires: tuple[str, ...]
    produces: tuple[str, ...]
    depends_on: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """An ordered, validated set of stages to run.

    A plan is only ever produced by
    :func:`~eds.platform.execution.planner.build_execution_plan`, which
    validates before constructing. Holding one is therefore a guarantee that
    its dependencies are complete, acyclic and satisfiable.

    Attributes:
        domain: The domain the plan was built from.
        stages: The stages in execution order.
    """

    domain: str
    stages: tuple[PlannedStage, ...]

    def __len__(self) -> int:
        """Return how many stages the plan contains."""
        return len(self.stages)

    def __iter__(self) -> Iterator[PlannedStage]:
        """Iterate the stages in execution order."""
        return iter(self.stages)

    def __getitem__(self, name: str) -> PlannedStage:
        """Return one planned stage by its own name.

        Args:
            name: Stage name, unqualified.

        Returns:
            The planned stage.

        Raises:
            KeyError: If the plan does not contain that stage.
        """
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise KeyError(f"Stage {name!r} is not in the plan. Planned: {self.stage_names}")

    @property
    def stage_names(self) -> tuple[str, ...]:
        """Return the stage names in execution order."""
        return tuple(stage.name for stage in self.stages)

    @property
    def stage_ids(self) -> tuple[str, ...]:
        """Return the stable stage identifiers in execution order."""
        return tuple(stage.stage_id for stage in self.stages)

    @property
    def datasets(self) -> tuple[str, ...]:
        """Return every dataset the plan produces, in execution order."""
        return tuple(dataset for stage in self.stages for dataset in stage.produces)

    @property
    def depth(self) -> int:
        """Return how many dependency levels the plan has."""
        return 1 + max((stage.level for stage in self.stages), default=-1)

    def levels(self) -> tuple[tuple[PlannedStage, ...], ...]:
        """Group the stages by dependency level.

        Everything in one group is independent of everything else in that
        group, so a scheduler may run a group concurrently. The platform
        computes this and stops there - whether to actually parallelise is the
        scheduler's decision, not the planner's.

        Returns:
            One tuple per level, in order, each in execution order.
        """
        grouped: list[list[PlannedStage]] = [[] for _ in range(self.depth)]
        for stage in self.stages:
            grouped[stage.level].append(stage)
        return tuple(tuple(group) for group in grouped)
