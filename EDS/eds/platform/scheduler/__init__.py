"""The runtime scheduler.

This package answers **"run it"**. It is the first thing in the platform that
does anything at all.

Everything before it declared: the execution model plans (PADR-008), the
project stores (PADR-009), the time model defines (PADR-010), the run binds and
validates (PADR-011) and the runtime contracts describe (PADR-012). The
scheduler is where those five meet, and its job is to call them in order.

**One input, one output.** It takes a
:class:`~eds.platform.run.run.SimulationRun` - already validated, so there is
nothing to assemble and nothing to check twice - and returns an
:class:`~eds.platform.scheduler.report.ExecutionReport` holding P005.1's
contracts unchanged.

**It cannot run a stage itself.** The platform deliberately has no way to
execute a domain (PADR-006), so a
:class:`~eds.platform.scheduler.executor.StageExecutor` is supplied by the
caller. That is what keeps the scheduler free of every domain, and it is how
every behaviour here is tested without generating a row.

Sequential, deterministic, and small. No threads, no queues, no observers, no
retries (PADR-013).
"""

from eds.platform.scheduler.executor import (
    StageExecutionError,
    StageExecutor,
    StageOutput,
    StageRequest,
)
from eds.platform.scheduler.report import ExecutionReport
from eds.platform.scheduler.scheduler import execute

__all__ = [
    "ExecutionReport",
    "StageExecutionError",
    "StageExecutor",
    "StageOutput",
    "StageRequest",
    "execute",
]
