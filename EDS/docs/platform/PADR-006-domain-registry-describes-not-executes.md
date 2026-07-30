# PADR-006: The Domain Protocol Describes, It Does Not Execute

**Status:** Accepted (P001.1)

**Supersedes:** the `SimulationDomain.generate()` method declared in P001.

## Context

P001 declared a domain protocol with three members: `name`, `dataset_names`,
and `generate() -> Mapping[str, DataFrame]`. It had no real implementation —
only a test stub — and P001's own roadmap flagged that as a risk: "an
unexercised protocol is a guess".

P001.1 was asked to make it real. Attempting to implement `generate()` for
Retail is what exposed the problem.

## The problem with `generate()`

Retail does not generate in one call. It generates in **four ordered stages** —
the four `eds generate` commands — and each stage reads what earlier stages
wrote *from disk*, because that is how the CLI is designed to work.

A no-argument `generate()` cannot express any of that. Implementing it for
Retail would have required one of:

1. **Duplicating the CLI's orchestration inside `RetailDomain`.** This creates
   a second execution path for generating retail data. One path is covered by
   1,762 tests; the other by none. They drift, and the day they drift is the
   day someone trusts the wrong one.
2. **Collapsing the four stages into one in-memory run.** This changes what
   Retail *is* — the staged, resumable, read-what-came-before design is a
   feature, not an implementation detail — and it would bypass the adapter
   entirely.
3. **Widening the signature to `generate(config, upstream)`.** Closer, but
   still models one stage, so the four-command structure remains
   inexpressible.

All three make the abstraction worse than no abstraction.

## Decision

The protocol **describes** a domain; it does not run one.

```python
class SimulationDomain(Protocol):
    name: str
    stages: tuple[DomainStage, ...]
    dataset_names: tuple[str, ...]


@dataclass(frozen=True)
class DomainStage:
    name: str  # matches the CLI command
    requires: tuple[str, ...]  # dataset names read
    produces: tuple[str, ...]  # dataset names written
```

`generate()` is removed. Execution joins the protocol when there is a caller
for it — which is the scheduler, in P002 or later.

## Why this is a live abstraction, not a decorative one

Two properties make it earn its place today:

**It is derived, so it cannot drift.** `RetailDomain` builds every stage from
the same declarations the generators and CLI already use — the dataset
registries and the `REQUIRED_*` constants. Nothing is restated by hand.

**It is checked.** Tests assert that Retail declares exactly 39 datasets each
appearing once, that the four stage names are the four CLI commands, that
every stage's inputs are produced by an earlier stage, and that stage inputs
equal the generators' own `REQUIRED_*` constants. A feature that adds a dataset
without declaring it, or that reads an undeclared upstream dataset, fails.

**It is what a scheduler needs first.** `requires`/`produces` across ordered
stages *is* the dependency graph. P002 can compute an execution order from this
description without importing a single generator.

## Consequences

**Good.** The protocol has a real implementation, no second execution path
exists, and the description is verified against the implementation rather than
maintained beside it.

**Cost.** The platform cannot yet *run* a domain through the protocol. That is
deliberate: nothing needs to, and the shape of `run` depends on decisions —
clock, state, adapter selection — that have not been made. Declaring it now
would be guessing again.

**Registration is an import side effect.** `import eds.domains.retail`
registers the domain. The alternative — the platform holding a list of built-in
domains — would put a domain name in platform code and break PADR-002, so the
domain announces itself instead. The descriptor defers all generator imports so
that registration stays cheap.

The remaining bootstrap question — *who imports the domain package* — is not
yet a problem, because the CLI does not route through the registry. When it
does, the standard answer is `importlib.metadata` entry points, which needs no
new runtime dependency. That is a P002 decision.

## API naming

P001 shipped `resolve_domain` and `available_domains`. P001.1 adopts
`get_domain` and `list_domains` as canonical — the conventional registry
idiom — and keeps the P001 names as exact aliases so nothing breaks. The
aliases should be deleted at the next major version.
