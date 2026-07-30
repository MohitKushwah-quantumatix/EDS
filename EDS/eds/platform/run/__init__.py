"""The simulation run model.

This package answers **"is this execution coherent?"**. It does not answer
"execute it".

A run binds the platform's three primitives - a project (P003), an execution
plan (P002) and a simulation clock (P004) - with the configuration that says
what is being asked for. Each of those three is valid on its own and none can
check that it agrees with the others; a run is where that check lives.

**This is the first module allowed to depend on all three.** That is its whole
purpose, and it is the reason the dependency runs strictly one way: a test
enforces that no plan, project or clock module imports this package. Their
independence is what makes them reusable; the run's dependence is what makes
them usable together.

The result is a scheduler that takes **one** argument rather than six, several
of which must be consistent and none of which can say so. Holding a run built
by :func:`~eds.platform.run.run.create_run` is a guarantee that its parts
agree.

Nothing here executes, schedules, advances or writes anything (PADR-011).
"""

from eds.platform.run.configuration import RunConfiguration
from eds.platform.run.errors import RunError, RunIssue, RunValidationError
from eds.platform.run.mode import RunMode
from eds.platform.run.run import SimulationRun, create_run
from eds.platform.run.stop import (
    STOP_CONDITION_KINDS,
    AfterStage,
    AfterTicks,
    EndOfPeriod,
    StopCondition,
    stop_condition_from_document,
)

__all__ = [
    "STOP_CONDITION_KINDS",
    "AfterStage",
    "AfterTicks",
    "EndOfPeriod",
    "RunConfiguration",
    "RunError",
    "RunIssue",
    "RunMode",
    "RunValidationError",
    "SimulationRun",
    "StopCondition",
    "create_run",
    "stop_condition_from_document",
]
