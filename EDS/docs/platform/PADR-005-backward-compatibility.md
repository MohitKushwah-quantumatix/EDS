# PADR-005: Backward Compatibility

**Status:** Accepted (P001)

## Context

P001 moved roughly a hundred modules. A refactor of that size that quietly
changes one generated value is worse than no refactor: the simulator's entire
proposition is that the same seed produces the same data.

"The tests still pass" is too weak a claim. Tests assert properties, and a
refactor can preserve every asserted property while changing an unasserted
byte.

## Decision

Backward compatibility is defined as three separate guarantees, each verified
independently.

**1. Byte-identical output.** Running the four commands at seed 42 produces
thirty-nine Parquet files whose SHA-256 digests match, file for file, those
produced before the refactor.

Verified by fingerprinting `output/` before any change and re-comparing after.
Combined digest, unchanged:

```
bd460170ae36c9a10964182745886346e4d9346adbe40ac9a3a2b960fac64e5b
```

**2. Existing tests pass unmodified.** Not one of the 1,700 pre-existing tests
was edited. They still import from the pre-platform paths, which is itself the
compatibility test.

**3. Old import paths resolve to identical objects.** Every pre-platform module
path remains importable and re-exports its new home. The guarantee is object
identity, not mere presence: `eds.generators.commerce.orders.OrderData` **is**
`eds.domains.retail.generators.commerce.orders.OrderData`.

Verified by `test_old_import_path_yields_the_same_objects`, which walks every
public name a new module defines and asserts `is` through the old path.

## Consequences

**Good.** The refactor is provably behaviour-preserving, and the proof is
mechanical rather than a matter of review confidence.

**Cost.** About a hundred shim modules. They are noise in the tree and they
roughly double the number of files ruff and mypy process.

The shims are explicit `from X import Y as Y` rather than `import *`. The first
attempt used `import *` and broke immediately: it re-exports only `__all__`,
and several modules have public functions outside it — `validate_order_data`
among them. Explicit re-export also keeps the surface auditable and visible to
mypy.

**Removal path.** The shims are a deprecation layer with a defined end. See the
[roadmap](03_Roadmap.md).

## What this decision does not permit

It does not permit "compatible enough". A generated value that changes because
a refactor was cleaner that way is a violation, not a trade-off. If a future
phase needs to change output, it does so as a versioned, announced change with
a regenerated baseline — not as a side effect of moving code.
