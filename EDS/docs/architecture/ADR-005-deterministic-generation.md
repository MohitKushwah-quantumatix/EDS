# ADR-005 - Deterministic Generation

**Status:** Accepted

**Applies from:** F001 (documented retrospectively)

---

## Decision

A run is a pure function of its configuration and its seed. The same
configuration and seed produce byte-identical output, on any machine, on any
day.

---

## How

### Named streams, not one shared generator

Each generator draws from its own stream, seeded by hashing the run seed with
a stream name:

```
sha256(f"{seed}:{stream}")  ->  random.Random
```

Two consequences follow, and both matter:

- **Adding or resizing one dataset does not shift the values of any other.**
  A shared generator would make every downstream value move whenever an
  upstream count changed, so a configuration change would look like a data
  change.
- **`hash()` is never used.** Python salts string hashing per process, so a
  `hash()`-seeded stream would differ between runs of the same command.

### A resolved seed is always reported

`resolve_seed` turns a null configured seed into a concrete one and the run
reports it. A "non-deterministic" run is therefore still reproducible after
the fact: feed the reported seed back in and the output is identical.

### No wall-clock input

Nothing reads the current time. Dates are anchored to a configured
`reference_date`, so a seeded run produces the same data tomorrow as it does
today. This is why `customers.yaml` carries a reference date rather than the
generators calling `date.today()`.

### Ordering is explicit

Iteration order is fixed - dataset registries are ordered tuples, groups are
sorted before they are walked, and rows are sorted before sequence numbers are
assigned. Nothing depends on dictionary insertion order arising by accident.

---

## How it is tested

Every feature asserts determinism at three levels:

| Level | Assertion |
| --- | --- |
| Generator | two calls with the same seed produce equal frames |
| Orchestrator | every dataset in the bundle is equal across two runs |
| CLI | two invocations write byte-identical Parquet files |

Each feature also asserts the negative - a *different* seed produces
*different* data - so a generator that ignores its seed entirely cannot pass.

Batch size is tested as an implementation detail: generating with a tiny
batch size and a huge one must produce identical output.

---

## Consequences

Anything that would break reproducibility is banned by construction:
`hash()`, `date.today()`, `datetime.now()`, unseeded `random`, set iteration
where order matters, and any dependence on file system ordering.

A generator that needs randomness in a helper takes an `rng` parameter rather
than creating one, so the caller controls the stream.
