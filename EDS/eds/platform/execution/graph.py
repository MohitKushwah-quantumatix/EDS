"""The stage dependency graph.

**Edges are derived, never declared.** A stage does not say which stages it
follows; it says which datasets it reads and which it writes. Stage ``B``
depends on stage ``A`` exactly when ``B.requires`` intersects ``A.produces``.

That distinction is the whole design. Declared stage-to-stage edges would be a
second statement of something the data flow already says, and two statements of
one fact drift. Deriving them means a stage that starts reading a new dataset
gets a new edge automatically, and a stage that stops producing one loses its
dependants automatically.

A consequence worth stating: the order a domain happens to list its stages in
carries no authority. It is used only to break ties between stages that are
genuinely independent, so that a plan is reproducible rather than arbitrary.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Final

from eds.platform.domain import DomainStage
from eds.platform.execution.errors import PlanningError

__all__ = ["DependencyGraph"]

#: Depth-first search colouring, used to find a concrete cycle. Grey means
#: "on the current path", so reaching a grey node closes a loop.
_WHITE: Final[int] = 0
_GREY: Final[int] = 1
_BLACK: Final[int] = 2


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    """Stages and the dependencies derived from their data flow.

    Construct with :meth:`from_stages`. The graph makes no claim that it is
    valid - it will happily hold a cycle - because reporting *why* a graph is
    unplannable is the validator's job, and it needs a graph to do it.

    Attributes:
        stages: The stages, in the order the domain declared them.
    """

    stages: tuple[DomainStage, ...]
    _order: dict[str, int] = field(repr=False)
    _producers: dict[str, tuple[str, ...]] = field(repr=False)
    _dependencies: dict[str, tuple[str, ...]] = field(repr=False)
    _dependants: dict[str, tuple[str, ...]] = field(repr=False)

    @classmethod
    def from_stages(cls, stages: tuple[DomainStage, ...]) -> DependencyGraph:
        """Derive a graph from a domain's declared stages.

        Args:
            stages: The stages, in declaration order. Duplicate names are kept
                rather than rejected; the validator reports them.

        Returns:
            The derived graph.
        """
        order = {stage.name: index for index, stage in enumerate(stages)}

        producers: dict[str, list[str]] = {}
        for stage in stages:
            for dataset in stage.produces:
                producers.setdefault(dataset, []).append(stage.name)

        dependencies: dict[str, tuple[str, ...]] = {}
        dependants: dict[str, list[str]] = {stage.name: [] for stage in stages}
        for stage in stages:
            upstream: dict[str, None] = {}
            for dataset in stage.requires:
                for producer in producers.get(dataset, ()):
                    # A stage that reads what it writes is a modelling error,
                    # not a self-edge; DomainStage already rejects it.
                    if producer != stage.name:
                        upstream.setdefault(producer, None)
            dependencies[stage.name] = tuple(sorted(upstream, key=lambda n: order.get(n, 0)))
            for producer in dependencies[stage.name]:
                dependants.setdefault(producer, []).append(stage.name)

        return cls(
            stages=stages,
            _order=order,
            _producers={name: tuple(value) for name, value in producers.items()},
            _dependencies=dependencies,
            _dependants={name: tuple(value) for name, value in dependants.items()},
        )

    @property
    def stage_names(self) -> tuple[str, ...]:
        """Return every stage name, in declaration order."""
        return tuple(stage.name for stage in self.stages)

    @property
    def datasets(self) -> tuple[str, ...]:
        """Return every dataset any stage produces, sorted."""
        return tuple(sorted(self._producers))

    def producers_of(self, dataset: str) -> tuple[str, ...]:
        """Return the stages that produce a dataset.

        Args:
            dataset: Dataset name.

        Returns:
            The producing stage names. Empty when nothing produces it, and
            longer than one when the declarations conflict.
        """
        return self._producers.get(dataset, ())

    def dependencies_of(self, stage: str) -> tuple[str, ...]:
        """Return the stages a stage directly depends on.

        Args:
            stage: Stage name.

        Returns:
            The upstream stage names, in declaration order.

        Raises:
            KeyError: If the stage is not in the graph.
        """
        try:
            return self._dependencies[stage]
        except KeyError:
            raise KeyError(f"Unknown stage: {stage!r}. Known stages: {self.stage_names}") from None

    def dependants_of(self, stage: str) -> tuple[str, ...]:
        """Return the stages that directly depend on a stage.

        Args:
            stage: Stage name.

        Returns:
            The downstream stage names, in declaration order.

        Raises:
            KeyError: If the stage is not in the graph.
        """
        try:
            return self._dependants[stage]
        except KeyError:
            raise KeyError(f"Unknown stage: {stage!r}. Known stages: {self.stage_names}") from None

    @property
    def roots(self) -> tuple[str, ...]:
        """Return the stages that depend on nothing, in declaration order."""
        return tuple(name for name in self.stage_names if not self._dependencies[name])

    def unsatisfied_requirements(self) -> tuple[tuple[str, str], ...]:
        """Return every ``(stage, dataset)`` pair nothing in the graph produces.

        Returns:
            The unsatisfiable requirements, in declaration then declared-input
            order.
        """
        return tuple(
            (stage.name, dataset)
            for stage in self.stages
            for dataset in stage.requires
            if dataset not in self._producers
        )

    def find_cycle(self) -> tuple[str, ...]:
        """Return one dependency cycle, if the graph contains any.

        Reporting a concrete path matters: "these six stages could not be
        ordered" sends someone hunting, whereas ``a -> b -> a`` is the answer.

        Returns:
            The cycle as stage names, beginning and ending at the same stage.
            Empty when the graph is acyclic.
        """
        colour = dict.fromkeys(self.stage_names, _WHITE)

        def walk(name: str, path: list[str]) -> tuple[str, ...]:
            colour[name] = _GREY
            path.append(name)
            for nxt in self._dependants.get(name, ()):
                if colour.get(nxt) == _GREY:
                    return (*path[path.index(nxt) :], nxt)
                if colour.get(nxt) == _WHITE and (found := walk(nxt, path)):
                    return found
            path.pop()
            colour[name] = _BLACK
            return ()

        for name in self.stage_names:
            if colour[name] == _WHITE and (found := walk(name, [])):
                return found
        return ()

    def topological_order(self) -> tuple[str, ...]:
        """Return the stage names in a deterministic execution order.

        Kahn's algorithm, with ties broken by declaration index. Ties are
        common - any two stages that do not feed each other are tied - so the
        tie-break is what makes a plan reproducible. Declaration order is used
        rather than alphabetical order because it is the one signal the domain
        author actually gave about preference; alphabetical order would be
        arbitrary and would surprise.

        Returns:
            Every stage name, ordered so that each appears after everything it
            depends on.

        Raises:
            PlanningError: If the graph contains a cycle. Callers should
                validate first; this is a guard, not the reporting path.
        """
        indegree = {name: len(self._dependencies[name]) for name in self.stage_names}
        ready: list[tuple[int, str]] = [
            (self._order[name], name) for name, degree in indegree.items() if degree == 0
        ]
        heapq.heapify(ready)

        ordered: list[str] = []
        while ready:
            _, name = heapq.heappop(ready)
            ordered.append(name)
            for nxt in self._dependants.get(name, ()):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    heapq.heappush(ready, (self._order[nxt], nxt))

        if len(ordered) != len(self.stages):
            cycle = self.find_cycle()
            rendered = " -> ".join(cycle) if cycle else "unknown"
            raise PlanningError(f"stages cannot be ordered; dependency cycle: {rendered}")
        return tuple(ordered)

    def levels(self, ordered: tuple[str, ...]) -> dict[str, int]:
        """Return each stage's depth in the graph.

        A stage's level is one more than the deepest stage it depends on, so
        stages sharing a level have no dependency between them and could run
        concurrently. This is the metadata a scheduler needs; the platform
        computes it but draws no conclusion from it.

        Args:
            ordered: Stage names in topological order.

        Returns:
            Stage name to zero-based level.
        """
        level: dict[str, int] = {}
        for name in ordered:
            upstream = self._dependencies.get(name, ())
            level[name] = 1 + max((level[dep] for dep in upstream), default=-1)
        return level
