# PADR-001: Canonical Business Model

**Status:** Accepted (P001)

## Context

The simulator's value is that it models a business, not that it writes files.
Those two concerns were interleaved: generators lived in `eds/generators/`,
exporters in `eds/exporters/`, and nothing prevented a generator from reaching
for a writer.

## Decision

Business simulation is independent from storage. A generator produces
`polars.DataFrame` objects described by `Dataset` declarations, and stops
there. Deciding where those frames are persisted belongs to an adapter, and
choosing the adapter belongs to the caller.

The shared vocabulary the two sides meet on — `Dataset`, `ForeignKey`,
`ValidationIssue`, the deterministic random streams — lives in `eds.core` and
depends on neither.

## Consequences

**Good.** A domain can be exercised entirely in memory, which is how every one
of the 1,745 tests already works. Adding an output format cannot break a
business rule, because it cannot reach one.

**Cost.** Anything genuinely shared has to be recognised as such and moved to
`core` deliberately. `core` is the one place where a careless import creates
coupling for everybody, which is why `test_core_is_self_contained` exists.

**Not decided here.** What a domain's frames *mean*. That is the domain's own
business, and PADR-002 keeps it that way.
