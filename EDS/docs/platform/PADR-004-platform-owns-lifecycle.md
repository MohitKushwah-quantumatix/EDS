# PADR-004: Platform Owns Lifecycle

**Status:** Accepted (P001)

## Context

The simulator will need a simulation clock, a scheduler, daily simulation,
growth and snapshots. None of them is retail-specific: a healthcare simulation
needs the same notion of "advance one day" that a retail one does.

The path of least resistance would be to add each to Retail as it is needed,
because Retail is where the pressure appears first. That would make the second
domain's first task porting them out.

## Decision

Project initialization, the simulation clock, scheduling, state and growth
belong to `eds.platform`, not to any domain.

P001 establishes the owner and implements only what exists today:

* `Project` — a named domain, seed and destination;
* `PlatformMetadata` — platform name, distribution version, contract version;
* `SimulationDomain` and the domain registry.

`clock.py` and `state.py` are declared and empty. Each carries a docstring
saying it is not implemented, an empty `__all__`, and a test asserting both.

## Consequences

**Good.** When the clock arrives it has an uncontested home. A domain author
reading the tree can see which concerns are not theirs.

**Cost.** Two empty modules that do nothing. That is the intended cost: a
placeholder is a cheap way to make a boundary visible before it is
load-bearing.

**Constraint on what comes next.** Every Retail run is a pure function of
`(configuration, seed, upstream data)`, which is what makes output
reproducible. Simulation state must not break that: state belongs to a
*project*, and a run of the same project at the same seed must still produce
byte-identical output.

**Not wired in.** Retail does not register through `SimulationDomain`, and the
CLI does not route through the registry. Routing the only domain through a
registry would be change without benefit, and PADR-005 forbids change without
benefit.
