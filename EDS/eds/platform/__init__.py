"""The simulation platform.

Owns everything that is about *running* a simulation rather than about any
particular business: project identity and metadata, the domain registry, the
execution model, what time means, the run that binds them, the contracts
execution is reported in, the scheduler that runs it, and - in a later phase -
the growth engine (PADR-004).

All but one of those declare rather than act. The execution model plans
(PADR-008), the project stores (PADR-009), the time model defines (PADR-010),
the run binds and validates (PADR-011) and the runtime contracts describe
(PADR-012). :mod:`eds.platform.scheduler` is the one component that executes:
it takes one :class:`~eds.platform.run.run.SimulationRun`, calls the other five
in order, and returns their contracts unchanged (PADR-013). It cannot run a
domain by itself - nothing in the platform can, by design - so it is given a
:class:`~eds.platform.scheduler.executor.StageExecutor`.

:mod:`eds.platform.state` remains a declared placeholder. It carries no
implementation and is not wired into any run.
"""
