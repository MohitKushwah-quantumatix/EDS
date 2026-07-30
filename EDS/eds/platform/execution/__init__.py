"""The platform execution model.

This package answers **"what should run?"**. It does not answer "run it".

It reads the stage declarations a registered domain exposes, derives the
dependency graph implied by their data flow, validates it, and produces an
ordered :class:`~eds.platform.execution.plan.ExecutionPlan`. The plan is inert
data: names, positions and levels. It holds no callable, opens no connection,
creates no state and knows no business domain or storage format.

Nothing here executes a generator, writes a dataset, reads Parquet, or touches
an adapter. A later component executes a plan; this one only decides what a
valid plan is (PADR-008).
"""

from eds.platform.execution.errors import (
    PlanningError,
    PlanningIssue,
    PlanValidationError,
)
from eds.platform.execution.graph import DependencyGraph
from eds.platform.execution.plan import ExecutionPlan, PlannedStage, stage_id
from eds.platform.execution.planner import build_execution_plan, plan_domain
from eds.platform.execution.validation import assert_plannable, validate_stages

__all__ = [
    "DependencyGraph",
    "ExecutionPlan",
    "PlanValidationError",
    "PlannedStage",
    "PlanningError",
    "PlanningIssue",
    "assert_plannable",
    "build_execution_plan",
    "plan_domain",
    "stage_id",
    "validate_stages",
]
