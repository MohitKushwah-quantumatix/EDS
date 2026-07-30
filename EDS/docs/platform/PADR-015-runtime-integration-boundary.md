# PADR-015: The Runner Is the Runtime Integration Boundary

**Status:** Accepted. **This record documents an existing architecture and
introduces no behaviour.** Every rule below is already true of the code and
already enforced by tests; what was missing was a decision saying it is
permanent.

**Builds on:** PADR-002 (platform-independent domains), PADR-003 (adapter
isolation), PADR-006 (the domain protocol describes, it does not execute),
PADR-013 (the executor arrives as an argument), PADR-014 (the runner is a third
party to the platform and the domain).

**Relationship to PADR-014.** PADR-014 recorded the *discovery*, made while
wiring Retail into the scheduler: the code that teaches a scheduler how to run a
domain has nowhere to live in four layers, so a fifth location was created.
PADR-015 promotes that from an implementation finding to a **standing boundary
rule** — what the layer is, what may cross it, what it owns and what it may
never acquire. PADR-014 remains the origin story and the Retail-specific
detail; neither supersedes the other.

> **A note on the phase label.** The phase that produced `eds/runners/` is
> recorded as **P006.1** throughout this repository and appears as **P006.5** in
> the architecture review notes. They are the same phase.

## 1. Problem

Two rules were settled long before there was anything to run.

**The platform may not import a domain** (PADR-002). Its whole claim is that a
Healthcare or Banking domain can be added without editing a line of platform
code, and one `import eds.domains.retail` refutes that claim permanently.

**A domain may not import the platform.** A domain must be usable without a
scheduler, a project or a clock — which is what makes `eds generate` possible,
and what stops the platform from becoming a framework that owns business logic
(PADR-001).

Both rules held comfortably while nothing executed. Then PADR-006 removed
`generate()` from the domain protocol on evidence, and PADR-013 made the
executor a scheduler argument — which left a question neither answered: **who
translates?**

Running a domain means holding two vocabularies at once. On one side there is a
`StageRequest`, a `PlannedStage`, a simulated date, a project's seed, a data
directory, a `FailureType`, a `StageOutput`. On the other there is a business
date, a set of frames, a generator that raises `KeyError` when an upstream
dataset is missing, and a validator that returns issues. Nothing in either
vocabulary can name anything in the other, and something has to.

Concretely, the translations are:

| Platform says | Domain hears |
| --- | --- |
| `StageRequest.simulation_date` | `BusinessContext.business_date` |
| `StageRequest.seed` (the project's) | the enterprise seed every stream derives from |
| `StageRequest.stage.requires` | which frames to hand the generators |
| `StageRequest.data_directory` | where an adapter is pointed |
| `StageOutput.rows_by_dataset` | what the writer reported |
| `FailureType.GENERATION` | a generator raised `ValueError` |

Six translations, none of which either side is allowed to know about.

## 2. Decision

**`eds/runners/` is the Runtime Integration Boundary: the single package
permitted to import both `eds.platform.*` and `eds.domains.*`.**

It is not a platform layer and it is not a domain layer. Being the only place
where both vocabularies are in scope is its entire definition, and everything it
is allowed to do follows from that: **if a piece of work needs both vocabularies,
it belongs here; if it needs only one, it belongs on that side.** That is the
test to apply to any future addition.

It is an **anti-corruption layer** in the strict sense. Its purpose is not
convenience or code reuse — it is to stop each side's vocabulary leaking into
the other. Without it, one of two things happens, and both have been seen in
codebases this one is trying not to become: a platform grows a `retail` branch,
or a domain grows a dependency on how it happens to be scheduled today.

One package per domain: `eds/runners/retail/`, `eds/runners/healthcare/`. There
is no shared base class, no `Runner` protocol and no registry, because nothing
needs to find a runner by name (see §5).

The boundary is enforced in both directions by test, not by convention:

* `test_the_platform_does_not_know_retail_exists` walks every module under
  `eds/platform/` and asserts no import begins with `eds.domains` or
  `eds.runners`.
* `test_the_retail_domain_does_not_know_the_runner_exists` does the same for
  `eds/domains/retail/`.
* `test_retail_never_learns_what_ran_it` goes further and asserts that nothing
  under `eds/domains/retail/` imports the platform's `run`, `scheduler`,
  `runtime`, `time` or `project` packages at any depth.
* `test_the_runner_opens_no_files_itself` asserts the boundary touches storage
  only through `DatasetReader` and `DatasetWriter`.

### Architectural invariant

The Runner exists to translate between architectural boundaries. If business
rules begin accumulating in the Runner, responsibilities have leaked from the
Domain. If orchestration begins accumulating in the Runner, responsibilities
have leaked from the Platform. Growth of the Runner should therefore be treated
as an architectural signal requiring review rather than a normal evolution of
the layer.

## 3. Responsibilities

### The Runner owns

**Translating the business context.** `StageRequest.simulation_date` becomes
`BusinessContext.business_date`, and the project's seed becomes the enterprise
seed. This is the whole of what the domain learns about time: a date and a seed.
The runner performs the translation and forms no opinion about what a date means
to a business — that is the domain's, and it is why the domain's own value
object is what gets built rather than the platform's being passed through.

**Invoking the domain.** The runner calls the domain's entry point for one stage
on one date. *It does not sequence the generators itself.* It did once — P006.1
had to, because the domain had no notion of being run — and that changed the day
the domain acquired one (ADR-013). The distinction matters to this decision:
**invoking a domain is translation; deciding the order its features run in is a
business rule**, and a business rule that lives on this side of the boundary is
a leak. The correction is the precedent: work discovered here that turns out to
need only one vocabulary must move to that side.

**Dependency injection.** Configuration, reader and writer arrive as constructor
arguments. The runner is where a caller substitutes a test double, a second
adapter or an alternative configuration, because it is the only place that knows
both what needs injecting and what it will be used for.

**Adapter selection.** Choosing a `ParquetAdapter` on the project's data
directory when no adapter is supplied. The platform cannot choose — it has no
adapters (PADR-003). The domain cannot choose — it has never heard of one. Only
the boundary can, and it does so through the protocols, never by opening a file.

**Failure classification.** Only this layer can tell a generator that raised
from data that failed validation from a disk that would not accept a write. It
raises `StageExecutionError` with the `FailureType` that names it, and the
scheduler records what it is told. All five types are reachable from here and
four are covered by tests against real failures.

**Reading the past.** A stage that continues a history has to be shown that
history, and no execution plan can say so: `PlannedStage.requires` is derived
from data flow and *subtracts* what the stage produces, and a plan that declared
it would be describing a cycle (ADR-013). So the domain declares what it needs
to read and the runner reads it. This is translation of exactly the kind this
boundary exists for — a domain fact the platform has no vocabulary for.

### The Runner never owns

**Business rules.** Not what a day does to an enterprise, not what a valid
dataset looks like, not what order a domain's features run in, not what a date
means. Every one of those belongs to the domain, and the one time generation sat
here it was a symptom of a gap on the domain's side rather than a decision.

**Orchestration.** It does not decide which stage runs next, whether a stage
runs at all, or what happens after one fails. Its whole surface is one method
that runs one stage once.

**Persistence.** It holds a `DatasetWriter` and hands frames to it. It does not
decide where data is durable, when state is written, or what a resume may trust
— the project owns state and the scheduler owns when it is recorded (PADR-009,
PADR-013).

**Scheduling.** It has no loop, no clock and no tick. It cannot advance time and
cannot ask what time it is; it is told a date.

**Execution planning.** It never builds a plan, orders stages or resolves a
dependency. P002 already decided, and the runner reads that decision rather than
recomputing it.

## 4. Allowed dependencies

```
        ┌──────────────────────────┐
        │      eds.platform        │   plan, project, time, run,
        │                          │   runtime contracts, scheduler
        └──────────────────────────┘
                     ▲
                     │  imports
                     │
        ┌──────────────────────────┐
        │       eds.runners        │   ◀── the Runtime Integration Boundary
        │   (one package per       │       the ONLY package with both
        │    domain)               │       vocabularies in scope
        └──────────────────────────┘
                     │
                     │  imports
                     ▼
        ┌──────────────────────────┐
        │      eds.domains         │   entities, generators, validators,
        │                          │   temporal evolution
        └──────────────────────────┘

           eds.adapters ◀── imported by eds.runners only
           eds.core     ◀── imported by all of the above
```

Read the arrows strictly. **Every dependency involving the boundary points
outward from it**, and there is no arrow between the platform and a domain in
either direction. The platform does not know a domain exists; a domain does not
know it is being run; neither knows the boundary is there.

`eds.core` is beneath all of it and depends on nothing inside `eds`.
`eds.adapters` is reached only from the boundary, through the protocols in
`eds.adapters.base` (PADR-003).

## 5. Alternatives considered

### The platform imports the domain

Rejected because it is the one thing the platform exists not to do. The moment
`eds/platform/` contains `import eds.domains.retail`, the claim that a second
domain needs no platform change is false, and it is false permanently — the
import will acquire a sibling the first time somebody adds Healthcare, and then
an `if domain == ...` to choose between them. PADR-002 exists to prevent exactly
that sequence, and this alternative is its first step.

### The domain imports the platform

Rejected because it makes a domain unusable without the machinery that happens
to run it today. Retail would need a `SimulationRun` to generate a customer;
`eds generate` could not exist in its present form; and a domain's tests would
have to construct a project, a clock and a plan to test a generator. It also
inverts ownership: a domain would start making decisions about ticks and
persistence, which are lifecycle concerns the platform owns (PADR-004).

The subtler objection is that it does not actually solve the problem. The
translations in §1 would still have to happen — they would simply happen inside
the domain, where the platform's vocabulary would spread through generators that
have no business knowing what a `StageRequest` is.

### A dynamic plugin registry

Rejected as speculative. There is already a registry — `eds.platform.domain` —
and it exists because a domain must be *discoverable* by name without the
platform holding a list (PADR-006). A second registry for runners would answer a
different question: "given a domain name, how do I run it?"

Nothing asks that question. A caller that wants to run Retail imports
`RetailExecutor`, which is one line and is checked by the type system. A
registry replaces that with a string lookup that fails at runtime, and buys
nothing until something genuinely has to run a domain it cannot name at import
time — a CLI taking `--domain` as an argument, most likely. It is a small change
to make then, on evidence, and the boundary is exactly where it would go.

### Runtime reflection

Rejected outright, and it is worth being explicit about why, because reflection
is the tempting answer to "the platform must not import a domain": import it by
string at runtime, and the static dependency disappears.

It disappears from the *import graph* only. The platform would still be coupled
to a domain's shape — the names of its modules, its stage functions, its return
types — with nothing to check any of it. Every test in §2 that enforces this
boundary works by reading imports, and all of them would pass while the
architecture was being violated. The dependency rule would become
unenforceable, which is worse than a rule that is honestly broken, because a
broken rule is visible.

It would also make the platform's failures worse in kind: a missing attribute
found part-way through a long run instead of a name error at import, and no type
checker able to say anything about either. `mypy` currently checks the whole seam
end to end.

### The runner calls the CLI

Rejected in P006.1 and worth recording: Typer commands print and exit processes.
A scheduler needs values.

## 6. Consequences

### Advantages

**The platform's central claim is testable, and tested.** A complete Retail
simulation runs through `SimulationRun → Scheduler → RetailExecutor → domain →
adapter → project → contracts`, and no platform component knows Retail exists.
That is a property of the import graph, which means it can be asserted rather
than argued.

**Each side stays honest about what it is.** The domain can be exercised without
a scheduler and the platform can be exercised with a fake executor — sixty-three
scheduler tests do exactly that. Neither needs the other to be testable.

**The translations are in one file, so they can be read.** Six mappings, one
place. When simulated time finally reached the domain, the change to this layer
was a handful of lines, and it was obvious where they went.

**A second adapter is a constructor argument.** The boundary is where injection
happens, so pointing a run at something other than Parquet does not touch the
platform, the domain or the adapter protocols.

**Failures are classified where the knowledge is.** The scheduler records a
`FailureType` it could not possibly have derived, because the only layer that
can tell the five cases apart is the one that called all of them.

### Disadvantages

**A domain now costs two packages.** Healthcare means
`eds/domains/healthcare/` *and* `eds/runners/healthcare/`. That is the honest
price of forbidding the platform and the domain from knowing about each other,
and it is one package — but it is real, and it is the first thing a newcomer
will ask about.

**There is a layer with no obvious name.** "It is not the platform and not the
domain" is a definition by exclusion, and readers reach for "glue" or
"adapter" — both wrong, the second actively confusing given `eds/adapters/`.
The anti-corruption-layer framing in §2 exists to give it a name that says what
it is for.

**It is where work accumulates if nobody is watching.** Anything that needs
both vocabularies belongs here, and it is easy to convince yourself that
something needs both when it needs one. It has happened once already:
generation sat here for a phase because the domain had no entry point.

### Long-term implications

**The boundary is where the platform's untested claims will be tested.** A
second domain is the real proof, and the measure is precise: if adding
Healthcare requires one new domain package and one new runner package and
changes no platform file, the architecture was right. If any platform file
changes, it was not.

**The CLI's future runs through here.** `eds generate <stage>` should become a
thin caller — open or create a project, build a one-day run, execute it with a
`RetailExecutor`. The byte-identity test written in P006.1 exists to make that
change safe, and when it happens there will be one execution path rather than
two.

**Parallelism will not touch this layer.** The plan already says which stages
may overlap, so executing a level concurrently is a scheduler change
(PADR-013). A runner that started coordinating anything would be taking on the
scheduler's job, which §3 forbids.

**Growth of the boundary is the signal to watch.** A runner that grows a second
public method, a loop, or a decision about what a business does has stopped
being a boundary. The remedy is always the same and always available: work that
needs one vocabulary moves to that side. If it needs to orchestrate, the need
belongs in the scheduler; if it needs to describe or decide, the need belongs in
the domain.

## 7. What this decision does not permit

* No package outside `eds/runners/` may import both `eds.platform.*` and
  `eds.domains.*`. There is no exception for tests of the seam itself, which
  import the boundary rather than reaching around it.
* A runner may not acquire a platform responsibility. Its surface is one method
  per executor; it opens no files; it holds no loop and no clock.
* A runner may not acquire a business rule. If a decision about an enterprise is
  being made in `eds/runners/`, it is in the wrong package.
* Reflection, string-based imports and dynamic attribute lookup may not be used
  to evade the dependency rules. A rule enforced by reading imports is only
  worth having while imports are what the code uses.
