# Platform Vision

## The problem

The Retail simulator works. It generates thirty-nine referentially consistent
datasets from four commands, reproducibly, and it does so by simulating
business events rather than sampling rows.

But everything about it was retail-shaped. `eds/generators/` meant *retail*
generators. `eds/config.py` held retail settings beside platform ones.
`eds/validation/referential.py` defaulted to the retail master datasets. None
of that was wrong while retail was the only thing being built; all of it would
have to be untangled the first time somebody asked for a second domain.

## The objective

Turn the simulator into a platform: a reusable engine for simulating *any*
business, with retail as its first and reference domain.

The test of success is not that the code looks tidier. It is that a
Healthcare, Banking or Manufacturing domain can be added **without editing a
single line of platform code** — no new `if domain == ...`, no widened base
class, no shared module that grows a healthcare branch.

## What the platform is

Four layers with a strict dependency direction:

```
adapters  ─┐                    ┌─  domains
           ├──▶  core  ◀────────┤
platform  ─┘                    └─  (retail, and later others)
```

* **core** — the shared vocabulary. Dataset declarations, deterministic random
  streams, frame construction, the validation framework, configuration
  loading. Knows about no business and no storage format.
* **platform** — what it means to *run* a simulation. Project identity,
  metadata, the domain registry, the execution model, simulated time, the run
  that binds them, the contracts execution is reported in, the scheduler that
  runs it, and eventually the growth engine.
* **domains** — the businesses being simulated. Entities, generators, business
  rules, domain configuration, and what a passing day does to all of it.
* **adapters** — where the output goes. Parquet today.
* **runners** — the integration layer. One package per domain, and the only
  place allowed to import both a domain and the platform. Not part of either.

## What the platform is not

It is not a framework that owns your business logic. A domain is not required
to subclass anything, and the platform makes no attempt to model "an entity"
or "a transaction" generically. Attempts to generalise business meaning across
retail, healthcare and banking produce abstractions that fit none of them.

The platform generalises the *mechanics* — determinism, schema conformance,
referential integrity, persistence — and leaves meaning entirely to domains.
That is the substance of PADR-001.

The division survived first contact with simulated time, which is where it was
most likely to fail. The platform owns time: it decides what a tick is worth,
which calendar applies and when the date advances. The domain owns business: it
decides what a day does to an enterprise — who joins, who returns, what sells,
what is restocked. Retail is handed a date and a seed, and there is nothing else
in what it is handed. It cannot ask what time it is and cannot advance it
(ADR-013).

## What P001 deliberately did not do

The platform foundation is structural. It added:

* no business feature, and no change to any existing one;
* no simulation clock, scheduler, daily simulation, growth engine or
  snapshots;
* no SCD or CDC;
* no SQL Server, PostgreSQL, MongoDB or Kafka adapter;
* no REST API, Docker or Kubernetes;
* no new CLI command, and no change to an existing one.

`eds/platform/clock.py` and `eds/platform/state.py` existed and were empty by
design. They marked where those concerns would live so that the next phase did
not have to argue about it — and so that nobody bolted them onto Retail in the
meantime. `clock.py` was superseded by `eds/platform/time/` in P004
(PADR-010); `state.py` is still a placeholder.

## The measure of backward compatibility

Not "the tests still pass". The specific claim P001 makes is stronger:

> Running the four commands at seed 42 produces thirty-nine Parquet files whose
> SHA-256 digests are identical, file for file, to those produced before the
> refactor.

That was verified before and after, and the combined digest
`bd460170ae36c9a10964182745886346e4d9346adbe40ac9a3a2b960fac64e5b` is
unchanged. See [PADR-005](PADR-005-backward-compatibility.md).
