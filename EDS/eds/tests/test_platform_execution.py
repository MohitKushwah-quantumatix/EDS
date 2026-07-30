"""Tests for the platform execution model.

The planner decides *what should run*. These tests cover the graph derivation,
every validation rule, ordering determinism, and the one invariant that keeps
the model honest: the order the planner derives from data flow alone is the
order the CLI actually runs its commands in.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

import eds
import eds.domains.retail  # noqa: F401  - registers the domain
from eds.platform.domain import DomainStage, get_domain
from eds.platform.execution import (
    DependencyGraph,
    ExecutionPlan,
    PlannedStage,
    PlanningError,
    PlanningIssue,
    PlanValidationError,
    assert_plannable,
    build_execution_plan,
    plan_domain,
    stage_id,
    validate_stages,
)

EXECUTION_ROOT = Path(eds.__file__).parent / "platform" / "execution"

#: The four commands `eds generate` exposes, in the order they must run.
CLI_COMMAND_ORDER = ("master-data", "customers", "journey", "commerce")


def stage(name: str, requires: tuple[str, ...], produces: tuple[str, ...]) -> DomainStage:
    """Build a stage for a fixture graph.

    Args:
        name: Stage name.
        requires: Dataset names read.
        produces: Dataset names written.

    Returns:
        The stage.
    """
    return DomainStage(name=name, requires=requires, produces=produces)


class _Domain:
    """A domain built from explicit stages, for exercising the planner."""

    def __init__(self, name: str, stages: tuple[DomainStage, ...]) -> None:
        """Build the stub.

        Args:
            name: Domain name.
            stages: The stages, in declaration order.
        """
        self._name = name
        self._stages = stages

    @property
    def name(self) -> str:
        """Return the domain name."""
        return self._name

    @property
    def stages(self) -> tuple[DomainStage, ...]:
        """Return the declared stages."""
        return self._stages

    @property
    def dataset_names(self) -> tuple[str, ...]:
        """Return every dataset the domain produces."""
        return tuple(name for stage in self._stages for name in stage.produces)


#: a -> {b, c} -> d. The smallest graph with a genuine ordering choice.
DIAMOND: tuple[DomainStage, ...] = (
    stage("a", (), ("A",)),
    stage("b", ("A",), ("B",)),
    stage("c", ("A",), ("C",)),
    stage("d", ("B", "C"), ("D",)),
)

#: The same diamond, declared with the two independent stages swapped.
DIAMOND_SWAPPED: tuple[DomainStage, ...] = (
    DIAMOND[0],
    DIAMOND[2],
    DIAMOND[1],
    DIAMOND[3],
)

CHAIN: tuple[DomainStage, ...] = (
    stage("one", (), ("X",)),
    stage("two", ("X",), ("Y",)),
    stage("three", ("Y",), ("Z",)),
)

TWO_CYCLE: tuple[DomainStage, ...] = (
    stage("x", ("Y",), ("X",)),
    stage("y", ("X",), ("Y",)),
)

THREE_CYCLE: tuple[DomainStage, ...] = (
    stage("p", ("R",), ("P",)),
    stage("q", ("P",), ("Q",)),
    stage("r", ("Q",), ("R",)),
)


# --------------------------------------------------------------------------
# Dependency graph
# --------------------------------------------------------------------------


def test_edges_are_derived_from_data_flow_not_declaration_order() -> None:
    """A stage depends on whoever produces what it reads."""
    graph = DependencyGraph.from_stages(DIAMOND)

    assert graph.dependencies_of("a") == ()
    assert graph.dependencies_of("b") == ("a",)
    assert graph.dependencies_of("c") == ("a",)
    assert graph.dependencies_of("d") == ("b", "c")


def test_dependants_are_the_inverse_of_dependencies() -> None:
    """The graph can be walked in either direction."""
    graph = DependencyGraph.from_stages(DIAMOND)

    assert graph.dependants_of("a") == ("b", "c")
    assert graph.dependants_of("d") == ()


def test_producers_are_recorded_per_dataset() -> None:
    """The graph knows which stage writes each dataset."""
    graph = DependencyGraph.from_stages(DIAMOND)

    assert graph.producers_of("A") == ("a",)
    assert graph.producers_of("nothing-produces-this") == ()


def test_roots_are_the_stages_that_depend_on_nothing() -> None:
    """A plan starts at its roots."""
    assert DependencyGraph.from_stages(DIAMOND).roots == ("a",)
    assert DependencyGraph.from_stages(CHAIN).roots == ("one",)


def test_the_graph_lists_every_dataset_it_produces() -> None:
    """Datasets are reported sorted, so the listing is stable."""
    assert DependencyGraph.from_stages(DIAMOND).datasets == ("A", "B", "C", "D")


def test_an_unknown_stage_lookup_raises() -> None:
    """Asking about a stage the graph does not hold fails clearly."""
    graph = DependencyGraph.from_stages(CHAIN)

    with pytest.raises(KeyError, match="Unknown stage"):
        graph.dependencies_of("absent")


def test_unsatisfied_requirements_are_reported_with_their_stage() -> None:
    """The graph can say which stage wanted what."""
    graph = DependencyGraph.from_stages((stage("a", ("ghost",), ("A",)),))

    assert graph.unsatisfied_requirements() == (("a", "ghost"),)


# --------------------------------------------------------------------------
# Cycle detection
# --------------------------------------------------------------------------


def test_an_acyclic_graph_reports_no_cycle() -> None:
    """The detector does not invent cycles."""
    assert DependencyGraph.from_stages(DIAMOND).find_cycle() == ()


@pytest.mark.parametrize(("stages", "size"), [(TWO_CYCLE, 2), (THREE_CYCLE, 3)])
def test_a_cycle_is_found_and_named(stages: tuple[DomainStage, ...], size: int) -> None:
    """A concrete path is reported, not just the fact of a cycle."""
    cycle = DependencyGraph.from_stages(stages).find_cycle()

    assert cycle, "a cycle should have been found"
    assert cycle[0] == cycle[-1], "a reported cycle should close"
    assert len(set(cycle)) == size


def test_ordering_a_cyclic_graph_raises_with_the_path() -> None:
    """The guard on the sort names the cycle rather than failing silently."""
    graph = DependencyGraph.from_stages(TWO_CYCLE)

    with pytest.raises(PlanningError, match="cycle"):
        graph.topological_order()


def test_a_cycle_downstream_of_valid_work_is_still_found() -> None:
    """A partly orderable graph is still unplannable."""
    stages = (
        stage("root", (), ("R",)),
        stage("x", ("R", "Y"), ("X",)),
        stage("y", ("X",), ("Y",)),
    )

    assert DependencyGraph.from_stages(stages).find_cycle()


# --------------------------------------------------------------------------
# Ordering and determinism
# --------------------------------------------------------------------------


def test_order_respects_dependencies() -> None:
    """Everything appears after what it depends on."""
    ordered = DependencyGraph.from_stages(DIAMOND).topological_order()

    assert ordered.index("a") < ordered.index("b")
    assert ordered.index("a") < ordered.index("c")
    assert ordered.index("b") < ordered.index("d")
    assert ordered.index("c") < ordered.index("d")


def test_ties_are_broken_by_declaration_order() -> None:
    """Independent stages keep the order the domain listed them in."""
    assert DependencyGraph.from_stages(DIAMOND).topological_order() == ("a", "b", "c", "d")
    assert DependencyGraph.from_stages(DIAMOND_SWAPPED).topological_order() == (
        "a",
        "c",
        "b",
        "d",
    )


def test_ordering_is_repeatable() -> None:
    """The same declarations always order the same way."""
    orders = {DependencyGraph.from_stages(DIAMOND).topological_order() for _ in range(25)}

    assert len(orders) == 1


def test_levels_group_independent_stages() -> None:
    """Stages at one level have no dependency between them."""
    graph = DependencyGraph.from_stages(DIAMOND)
    levels = graph.levels(graph.topological_order())

    assert levels == {"a": 0, "b": 1, "c": 1, "d": 2}


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def rules(issues: list[PlanningIssue]) -> set[str]:
    """Return the rule identifiers present in a list of issues.

    Args:
        issues: Issues to summarise.

    Returns:
        The set of rule names.
    """
    return {issue.rule for issue in issues}


def test_a_valid_stage_set_produces_no_issues() -> None:
    """A well-formed graph validates cleanly."""
    assert validate_stages(DIAMOND) == []


def test_an_empty_stage_set_is_rejected() -> None:
    """A domain with no stages has nothing to plan."""
    assert "empty_graph" in rules(validate_stages(()))


def test_a_duplicate_stage_name_is_rejected() -> None:
    """Stage names identify a stage, so they must be unique."""
    stages = (stage("a", (), ("A",)), stage("a", (), ("B",)))

    assert "duplicate_stage" in rules(validate_stages(stages))


def test_duplicate_names_suppress_the_structural_checks() -> None:
    """An ambiguous graph would report noise, so the real fault is reported alone."""
    stages = (stage("a", ("ghost",), ("A",)), stage("a", (), ("B",)))

    assert rules(validate_stages(stages)) == {"duplicate_stage"}


def test_two_stages_producing_one_dataset_are_rejected() -> None:
    """Two writers of one dataset is a race however it is executed."""
    stages = (stage("a", (), ("A",)), stage("b", (), ("A",)))

    assert "duplicate_producer" in rules(validate_stages(stages))


def test_an_unsatisfiable_requirement_is_rejected() -> None:
    """A stage cannot read what nothing writes."""
    issues = validate_stages((stage("a", ("ghost",), ("A",)),))

    assert "unknown_dependency" in rules(issues)
    assert "ghost" in issues[0].detail


def test_a_cycle_is_rejected_with_a_readable_path() -> None:
    """The error tells the reader where the loop is."""
    issues = validate_stages(TWO_CYCLE)

    assert "circular_dependency" in rules(issues)
    assert "->" in issues[0].detail


def test_an_unknown_target_is_rejected() -> None:
    """Planning for a stage the domain does not declare is an error."""
    issues = validate_stages(DIAMOND, targets=["absent"])

    assert "missing_stage" in rules(issues)


def test_assert_plannable_passes_a_valid_graph() -> None:
    """The assertion helper does not raise for a good graph."""
    assert_plannable(DIAMOND)


def test_assert_plannable_raises_carrying_every_issue() -> None:
    """A malformed pipeline usually has more than one thing wrong with it."""
    stages = (
        stage("a", ("ghost",), ("A",)),
        stage("b", ("also-missing",), ("B",)),
    )

    with pytest.raises(PlanValidationError) as caught:
        assert_plannable(stages)

    assert len(caught.value.issues) == 2
    assert "ghost" in str(caught.value)


def test_a_planning_issue_renders_readably() -> None:
    """Issues appear in error messages, so they must read well."""
    issue = PlanningIssue(stage="a", rule="unknown_dependency", detail="requires 'x'")

    assert str(issue) == "[a] unknown_dependency: requires 'x'"


def test_a_graph_wide_issue_renders_without_a_stage() -> None:
    """An issue about the whole plan has no stage to name."""
    assert str(PlanningIssue(stage="", rule="empty_graph", detail="nothing")).startswith("[<plan>]")


def test_an_error_without_issues_is_a_bug() -> None:
    """Raising a validation error with nothing to report is rejected."""
    with pytest.raises(ValueError, match="at least one issue"):
        PlanValidationError(())


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


def test_a_plan_orders_and_positions_its_stages() -> None:
    """Position is the index in execution order."""
    plan = build_execution_plan(_Domain("demo", DIAMOND))

    assert plan.stage_names == ("a", "b", "c", "d")
    assert [planned.position for planned in plan] == [0, 1, 2, 3]


def test_stage_identifiers_are_stable_and_domain_qualified() -> None:
    """Two domains may share a stage name without colliding."""
    plan = build_execution_plan(_Domain("demo", CHAIN))

    assert plan.stage_ids == ("demo:one", "demo:two", "demo:three")
    assert stage_id("other", "one") == "other:one"


def test_a_plan_records_direct_dependencies_as_identifiers() -> None:
    """Dependencies are expressed in the plan's own identifier space."""
    plan = build_execution_plan(_Domain("demo", DIAMOND))

    assert plan["d"].depends_on == ("demo:b", "demo:c")
    assert plan["a"].depends_on == ()


def test_a_plan_exposes_its_levels() -> None:
    """Level grouping is the metadata a scheduler needs."""
    plan = build_execution_plan(_Domain("demo", DIAMOND))

    assert plan.depth == 3
    assert [[planned.name for planned in group] for group in plan.levels()] == [
        ["a"],
        ["b", "c"],
        ["d"],
    ]


def test_a_plan_lists_every_dataset_in_execution_order() -> None:
    """The plan can say what the run will produce, and when."""
    plan = build_execution_plan(_Domain("demo", DIAMOND))

    assert plan.datasets == ("A", "B", "C", "D")


def test_a_plan_supports_lookup_and_iteration() -> None:
    """The plan is a sequence of stages, addressable by name."""
    plan = build_execution_plan(_Domain("demo", CHAIN))

    assert len(plan) == 3
    assert [planned.name for planned in plan] == ["one", "two", "three"]
    assert plan["two"].level == 1


def test_looking_up_a_stage_outside_the_plan_raises() -> None:
    """A narrowed plan does not silently answer for stages it excluded."""
    plan = build_execution_plan(_Domain("demo", CHAIN))

    with pytest.raises(KeyError, match="not in the plan"):
        plan["absent"]


def test_a_plan_is_immutable() -> None:
    """A plan is a decision, not a working buffer."""
    plan = build_execution_plan(_Domain("demo", CHAIN))

    with pytest.raises(AttributeError):
        plan.domain = "other"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        plan.stages[0].position = 5  # type: ignore[misc]


# --------------------------------------------------------------------------
# Planner behaviour
# --------------------------------------------------------------------------


def test_planning_is_deterministic() -> None:
    """The same declarations always produce the same plan."""
    domain = _Domain("demo", DIAMOND)

    first = build_execution_plan(domain)
    second = build_execution_plan(domain)

    assert first == second


def test_planning_is_a_pure_function_of_the_declarations() -> None:
    """Two equal domains plan identically, without sharing objects."""
    first = build_execution_plan(_Domain("demo", DIAMOND))
    second = build_execution_plan(_Domain("demo", tuple(DIAMOND)))

    assert first.stages == second.stages


def test_planning_an_invalid_domain_raises_rather_than_returning_a_broken_plan() -> None:
    """There is no such thing as a partially valid plan."""
    with pytest.raises(PlanValidationError):
        build_execution_plan(_Domain("demo", TWO_CYCLE))


def test_planning_an_empty_domain_raises() -> None:
    """A domain with no stages cannot be planned."""
    with pytest.raises(PlanValidationError, match="empty_graph"):
        build_execution_plan(_Domain("demo", ()))


def test_targets_narrow_the_plan_to_what_is_needed() -> None:
    """Planning for a target includes its transitive dependencies and no more."""
    plan = build_execution_plan(_Domain("demo", DIAMOND), targets=["b"])

    assert plan.stage_names == ("a", "b")


def test_targets_pull_in_every_branch_they_need() -> None:
    """A target with two upstream branches gets both."""
    plan = build_execution_plan(_Domain("demo", DIAMOND), targets=["d"])

    assert plan.stage_names == ("a", "b", "c", "d")


def test_several_targets_are_unioned() -> None:
    """Planning for two targets covers both closures once each."""
    plan = build_execution_plan(_Domain("demo", DIAMOND), targets=["b", "c"])

    assert plan.stage_names == ("a", "b", "c")


def test_a_narrowed_plan_renumbers_positions() -> None:
    """Position describes the plan, not the domain it came from."""
    plan = build_execution_plan(_Domain("demo", DIAMOND), targets=["c"])

    assert [planned.position for planned in plan] == [0, 1]
    assert plan["c"].level == 1, "level describes the graph and is not renumbered"


def test_an_unknown_target_raises() -> None:
    """A typo in a target name is reported, not ignored."""
    with pytest.raises(PlanValidationError, match="missing_stage"):
        build_execution_plan(_Domain("demo", DIAMOND), targets=["typo"])


# --------------------------------------------------------------------------
# Registry integration
# --------------------------------------------------------------------------


def test_a_registered_domain_can_be_planned_by_name() -> None:
    """The planner loads a domain through the registry, not by import."""
    plan = plan_domain("retail")

    assert isinstance(plan, ExecutionPlan)
    assert plan.domain == "retail"


def test_planning_an_unregistered_domain_raises() -> None:
    """An unknown domain fails at lookup with the registry's message."""
    with pytest.raises(KeyError, match="Unknown domain"):
        plan_domain("healthcare")


def test_the_retail_plan_matches_the_cli_command_order() -> None:
    """The derived order is the order the CLI actually runs.

    This is the invariant that keeps a second source of truth from appearing:
    the planner reaches this order from data flow alone, knowing nothing about
    the CLI, so agreement is evidence rather than coincidence.
    """
    assert plan_domain("retail").stage_names == CLI_COMMAND_ORDER


def test_the_cli_exposes_exactly_the_planned_stages() -> None:
    """Every planned stage is a real command, and there are no others."""
    from eds.cli.generate import generate_app

    registered = {command.name for command in generate_app.registered_commands}

    assert registered == set(CLI_COMMAND_ORDER)


def test_the_retail_plan_covers_every_dataset_once() -> None:
    """A plan of the whole domain accounts for the whole domain."""
    plan = plan_domain("retail")

    assert len(plan.datasets) == 39
    assert len(set(plan.datasets)) == 39
    assert plan.datasets == get_domain("retail").dataset_names


def test_the_retail_plan_is_a_chain_of_levels() -> None:
    """Each Retail command depends on the one before it, so none may overlap."""
    plan = plan_domain("retail")

    assert plan.depth == 4
    assert all(len(group) == 1 for group in plan.levels())


def test_planning_retail_for_a_target_stops_early() -> None:
    """Narrowing works against the real domain, not only fixtures."""
    plan = plan_domain("retail", targets=["customers"])

    assert plan.stage_names == ("master-data", "customers")


def test_planning_retail_is_deterministic() -> None:
    """The real domain plans identically every time."""
    assert plan_domain("retail") == plan_domain("retail")


# --------------------------------------------------------------------------
# Architectural constraints
# --------------------------------------------------------------------------


def test_the_execution_model_is_inert() -> None:
    """The planner decides what should run; it must be unable to run it.

    A plan that could hold a callable or a frame would be one refactor away
    from becoming an executor. Keeping the package free of polars and of every
    other layer is what makes that impossible rather than merely discouraged.
    """
    banned = ("polars", "eds.domains", "eds.adapters", "eds.core")
    for source in EXECUTION_ROOT.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(banned), f"{source.name} imports {node.module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(banned), f"{source.name} imports {alias.name}"


def test_no_planned_stage_carries_anything_executable() -> None:
    """Every field of a plan is a name or a number."""
    for planned in plan_domain("retail"):
        for value in vars(PlannedStage).get("__slots__", ()):
            attribute = getattr(planned, value)
            assert isinstance(attribute, (str, int, tuple)), f"{value} is {type(attribute)}"


@pytest.mark.parametrize(
    "name",
    [
        "eds.platform.execution",
        "eds.platform.execution.errors",
        "eds.platform.execution.graph",
        "eds.platform.execution.plan",
        "eds.platform.execution.planner",
        "eds.platform.execution.validation",
    ],
)
def test_execution_modules_are_importable_and_documented(name: str) -> None:
    """Every module in the package imports cleanly and states its purpose."""
    module = importlib.import_module(name)

    assert module.__doc__ is not None
    assert module.__doc__.strip()
