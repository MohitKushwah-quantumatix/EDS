# PADR-016: Data Is Domain State

**Status:** Accepted. **This record documents behaviour already implemented and
introduces no functionality.** It records a principle that was discovered by
executing a domain over simulated time rather than designed in advance.

**Builds on:** PADR-002 (platform-independent domains), PADR-004 (the platform
owns lifecycle), PADR-009 (the project owns identity and state), PADR-010
(simulated time is a value the platform owns), PADR-012 (runtime contracts are
deterministic facts), PADR-015 (the runner is the runtime integration boundary).

**Relationship to ADR-013.** ADR-013 (`docs/architecture/`) records this as a
*Retail* rule, with Retail's mechanics: how a day is generated, how identifiers
continue, how a day joins a history. PADR-016 keeps only what is not about
retail and makes it binding on **every** domain, including the ones not yet
written. Where the two overlap, ADR-013 is the worked example and this is the
rule.

> **A note on the phase label.** The phase that produced this principle is
> recorded as **Retail Temporal Evolution** in this repository's roadmap and as
> **P007A** in the architecture review notes. They are the same phase.

## 1. Problem

A domain is asked to do a unit of work. Before it can do any, it has to answer
one question: **what has already happened?**

Everything else turns on that answer. Is this enterprise being founded, or
continued? Which identifiers have been issued, so that new ones do not collide?
What does the business look like *now*, as distinct from what it looked like when
it started? A domain that cannot answer reliably cannot be resumed, replayed or
trusted.

There are six places the answer could come from.

| Candidate | What it is |
| --- | --- |
| **Runtime memory** | The domain remembers, within one process |
| **A first-run marker** | A flag recording that founding has happened |
| **A tick counter** | A number recording how many units of work have run |
| **Execution flags** | Per-stage or per-phase completion records |
| **Project metadata** | The platform's own record of a run's position |
| **Persisted business history** | The generated data itself |

They fall into three families, and the first two are variations on one mistake.

**Runtime memory** is the least defensible and the easiest to reach for. It dies
with the process, which means a simulation cannot be stopped, cannot be
distributed, and cannot be resumed on a different machine. It also makes the
domain's behaviour depend on the *order calls arrive in* rather than on what is
true, which is untestable in any useful sense.

**Everything in the middle — markers, counters, flags, metadata — is execution
state.** It survives the process, which makes it look like a solution. It is
not, because it describes *the run* rather than *the enterprise*, and those two
things diverge the moment anything interesting happens.

The divergence is not hypothetical. Four ordinary capabilities each break it:

**Replay.** If a domain's behaviour depends on a counter that advances, then
asking for the same period twice produces two different answers. Determinism
stops being a property of a run's *inputs* and becomes a property of the run's
history — which is the opposite of what determinism is for. A dataset that
cannot be regenerated from its inputs cannot be verified, only trusted.

**Resume.** Execution state gives an enterprise two records of where it stands:
the bookkeeping, and the data. Two records can disagree, and a process that
stops between writing one and writing the other guarantees they will. Nothing
can then say which is right — and the code that would reconcile them needs to
understand both, which puts business meaning into the bookkeeping or bookkeeping
into the business. Both are the coupling the layering exists to prevent
(PADR-002, PADR-015).

**Deterministic execution.** Seeding from, or branching on, a position makes
output a function of *how* a run reached a moment rather than *which* moment it
reached. The consequence is severe and easy to miss: dividing one long run into
several shorter ones changes the data. So does a failure and a retry. So does
running the second half on a different machine. Every one of those is something
an operator will do without thinking it is a semantic change.

**Migration.** Data is what people move. A directory gets copied, a workspace
gets shared, a bucket gets synchronised — and the sidecar bookkeeping is what
gets left behind, or arrives stale. Any design where the data alone is
insufficient is a design that fails on the most ordinary operational act there
is.

There is a quieter cost underneath all four. The number of states that must be
reasoned about is the *product* of the data's states and the execution record's
states, and almost all of that product is representable but unreachable —
"founded according to the flag, empty according to the data", and its mirror.
Unreachable-but-representable states are where defects live, and every piece of
execution state a domain keeps multiplies them.

## 2. Decision

**Persisted business data is the authoritative representation of domain state. A
domain derives its current business state exclusively from persisted business
history, and stores no execution state of its own.**

Two vocabularies, two owners, no overlap:

* **Execution metadata describes an execution.** Which stages completed, where a
  clock stood, whether a run failed, how long it took. It answers *"what did
  this run do?"* It belongs to the platform (PADR-009, PADR-012).
* **Business data describes an enterprise.** Who exists, what they did, what
  they own, what it is worth. It answers *"what is true of this business?"* It
  belongs to the domain.

The first is a record of a *process*. The second is a record of a *world*. The
decision is that a domain reads only the second, and that no value from the
first may change what a domain generates.

Business history alone is sufficient to determine all of:

* **Founding.** A domain that has produced nothing has nothing to continue. The
  *absence of data is the founding condition* — not a flag that says so. This
  also settles the awkward case a flag cannot express: a partially built
  enterprise, where some of what a domain produces exists and some does not,
  founds what is missing and continues what is not, with no state to consult and
  no reconciliation to get wrong.
* **Continuation.** What exists is what is continued from.
* **Identity allocation.** New identifiers continue past those already issued,
  which the issued ones themselves record.
* **Historical reconstruction.** A history is a history; it does not need a
  second account of itself.
* **Replay.** A unit of work is addressed by its **business moment, not its
  position in a sequence.** Given the same inputs and the same history, it
  produces the same result — whichever run asks, in whatever order, on whatever
  machine.
* **Recomputation.** Any derived quantity is a function of history, so it can
  always be recomputed rather than remembered. Where a derived value must not
  move backwards, the rule that guarantees it is expressed over history rather
  than over a previous value, so recomputing twice cannot compound.

**The platform does not participate in any of these decisions.** It supplies a
business moment and asks for work. It cannot tell a founding unit of work from a
continuing one, has no way to find out, and must not be told — the moment it
could, it would be reasoning about a business, which is the thing it exists not
to do (PADR-001, PADR-002).

### Architectural invariant

Execution state is not business state. The two answer different questions, are
owned by different layers, and may not be substituted for one another. A domain
that reads execution metadata to decide what to generate has taken a dependency
on how it happens to be run; a platform that reads business data to decide what
to schedule has taken a dependency on what a business means. Either direction is
a layering violation, and both are invisible in a passing test suite until
something is replayed, resumed or moved.

## 3. Responsibilities

### The Platform owns

* **Execution** — running a unit of work, and reporting what happened.
* **Scheduling** — what runs, in what order, and whether it runs at all.
* **Simulated time** — what a unit of work is worth, which calendar applies,
  and when the moment advances (PADR-010).
* **Persistence mechanics** — where state and data are durable, and when a
  record is written (PADR-009).
* **Replay mechanics** — being able to ask for the same period again. *Not* what
  the answer is.

The platform's record of an execution is legitimate and necessary. What this
decision constrains is its *scope*: it describes the run, and a domain may not
consult it.

### The Runner owns

* **Translation** between the platform's vocabulary and the domain's.
* **Integration** — invoking the domain, and reporting the outcome in terms the
  platform understands.
* **Dependency wiring** — configuration, readers, writers, adapters.

The boundary is the one place where both vocabularies are in scope (PADR-015),
which makes it the one place where this decision could be quietly broken. It
translates a business moment; it does not translate a *position*, a *count* or a
*phase*, because there is nothing on the domain's side for those to become.

### The Domain owns

* **Interpreting business history** — reading what exists and understanding what
  it means.
* **Business evolution** — what a passing moment does to an enterprise.
* **Deciding whether an enterprise is being founded or continued** — from the
  data, and from nothing else.
* **Deriving current business state** — every "as of now" quantity, computed
  from history rather than remembered.

### The diagnostic

When it is unclear which side something belongs on, the question to ask is:
**would this value, if changed, change the generated data?**

If yes, it is business state and belongs to the domain, derived from history. If
it would change only *what runs, when, or whether* — not what the data says —
it is execution state and belongs to the platform. A value that appears to do
both has not been decomposed yet.

## 4. The separation

```
     BUSINESS                                    EXECUTION
     the world                                   the process
     ─────────                                   ───────────

  Persisted business history                Execution metadata
  (the authoritative record)                (stages, position, outcomes)
             │                                        │
             ▼                                        ▼
     Domain derives state                    Platform executes
   founding or continuation,                 orders work, advances the
   identities, current values                moment, records what happened
             │                                        │
             ▼                                        ▼
     Business decisions                      Execution decisions
   what happens to the enterprise            what runs, when, whether

             │                                        │
             └──────────────┐        ┌────────────────┘
                            ▼        ▼
                    ╔══════════════════════╗
                    ║   a business moment  ║   ◀── the only thing that crosses
                    ╚══════════════════════╝
```

Read the gap in the middle as the point. **The two columns never read each
other.** The platform does not consult business history to decide what to
schedule; the domain does not consult execution metadata to decide what to
generate. The single value that crosses is a business moment — and it crosses
*downward*, as an input, never as an answer.

Which is why the two columns can be reasoned about, tested and replaced
separately. It is also why a business history is portable on its own: everything
needed to continue an enterprise is in the left column.

## 5. Alternatives considered

### A first-run flag

Rejected because it creates a second source of truth for a question the data
already answers, and the two can disagree. When they do, the flag wins over the
evidence — a record *about* the data overriding the data — which is the wrong
way round in every case and unrecoverable in most.

It is also less expressive than what it replaces. A flag is one bit, so it
cannot describe an enterprise that is partly built; the data can, simply by
existing in some places and not others. The flag therefore needs a companion
rule for the partial case, and that rule needs its own state, and the recursion
does not terminate anywhere good.

Deeper still: a flag records a *fact about an execution* ("founding happened")
in order to answer a *question about a business* ("does this enterprise exist").
Those are the two vocabularies §2 separates, joined in a single value.

### A mutable tick counter

Rejected because it makes output a function of a run's path rather than its
inputs. If a counter is what a unit of work is identified by — or seeded from —
then the same period produces different data depending on how a run arrived at
it. Dividing a long run, retrying a failure, or finishing on a second machine
all become semantic changes, silently.

There is a second objection that stands even where determinism is not at stake.
A counter encodes a *position*; business events have *moments*. The moment is
strictly more informative, is already recorded on every row, and is the thing
every business question is actually asked in terms of. The counter is a lossy
re-encoding of information the data already carries, kept in a place where it
can go stale.

### An execution checkpoint inside the domain

Rejected because it inverts ownership. Lifecycle is the platform's (PADR-004);
a domain holding a checkpoint has taken on a lifecycle responsibility, and to
maintain it honestly would have to be told when a run starts, stops, fails and
resumes. That is the platform's vocabulary crossing into the domain — the thing
the integration boundary exists to prevent (PADR-015) — and it would arrive not
as a single import but as a widening trickle of parameters.

It also makes a domain unusable without the machinery that happens to run it
today, which is the property that keeps a domain independently testable and
independently useful.

### Cached domain state

Rejected **as an authority**, and permitted as an optimisation — the distinction
is the whole of it.

Rejected as authority for the same reason as the flag: a cache that may be
believed over the data is a second source of truth, and the cost of a wrong one
is silent corruption of a history rather than a visible failure.

Permitted as an optimisation because reconstructing state from history has a
real cost, and that cost is a legitimate engineering problem to solve. What is
not legitimate is solving it by promotion. The rule is stated as an invariant in
§6 precisely because this is the alternative most likely to be reintroduced
accidentally, by somebody optimising rather than by somebody deciding.

## 6. Consequences

### Advantages

**Deterministic replay.** The same inputs and the same history produce the same
result. Determinism becomes a property that can be *tested* — by generating a
period twice and comparing bytes — rather than a property that has to be
believed.

**Resumable execution.** Because there is one record of where an enterprise
stands, there is nothing to reconcile and nothing that can disagree. A stopped
run leaves a coherent enterprise, not an ambiguous one, and a run divided into
pieces produces what one run would have.

**Immutable history.** Once the data is the authority, rewriting it is
self-evidently wrong rather than merely discouraged, and appending becomes the
natural operation. That in turn makes the strongest checks available: the
existing prefix of a history can be compared byte for byte after later work.

**Migration between machines.** Copy the data and the enterprise moves. Nothing
has to be exported, and nothing can be forgotten, because there is no second
artefact.

**Recomputation.** Any derived quantity can be rebuilt from history, which means
a derivation can be corrected retrospectively without a migration and without
the old value contaminating the new one.

**Simpler domain state.** The clearest gain and the hardest to notice, because
what it removes is code that was never written. A domain with no execution state
has no state machine, no invalidation, no versioning of its own bookkeeping, and
no reachability argument to make about states that combine badly.

### Tradeoffs

**Reconstruction can cost more than remembering.** Deriving "as of now" from a
long history is work that a mutable value would have avoided, and the cost grows
with the history. This is the real price and it should be stated plainly rather
than argued away.

**Historical consistency becomes critical.** When the data is the authority, a
corrupt or contradictory history is not a data-quality problem but a *state*
problem: the domain will read it and act on it. Validating a history — not only
each unit of work in isolation — stops being optional, and the rules that hold
across a whole history need to be stated as explicitly as the ones that hold
within a moment.

**Some derived values are recomputed repeatedly.** The same quantity may be
derived on many successive units of work. That is wasted effort by any local
measure, and accepting it is a deliberate trade of throughput for the
correctness properties above.

**Validation cost grows with history.** Checks that are naturally expressed over
a whole history cannot be narrowed to a single moment's output without changing
what they mean, so verification gets slower as an enterprise gets older. Worth
knowing before it is discovered in a long run.

### Architectural invariant

**A domain may cache business history for performance, but persisted business
history remains the single authoritative source of domain state.**

The distinction is not stylistic. A cache is *derived* — discardable at any
moment, rebuildable from the history alone, and never consulted in preference to
it. A record that must be trusted because the history can no longer produce it
has stopped being a cache and become a second source of truth, whatever it is
called. The test is one question: **if this were deleted, could it be rebuilt
from the persisted business data?** If yes, it is a cache and it is permitted.
If no, this decision has been broken.

### Long-term implications

**This is what a new domain must satisfy.** Healthcare, Banking and
Manufacturing are bound by it before their first line is written, and the
obligation is short: derive from what you have persisted, keep no record of
having run, and let absence mean founding. A domain that meets those three is
resumable and replayable without doing anything further about either.

**It constrains what the platform may offer a domain.** Any future facility that
would hand a domain a position, a phase, an attempt number or a run identity to
generate from is precluded by this decision, however convenient. The platform
may know all of those things; it may not make a domain's output depend on them.

**A domain becoming continuable does not make a platform able to continue it.**
The two are separate readinesses, and this decision only delivers the first.
Where a platform's own bookkeeping requires a run to stand exactly where the
last one stopped, an enterprise that is perfectly able to be carried forward
still cannot be, and closing that gap is a platform change (see the roadmap's
open questions on resuming and continuing). The lesson generalises: this
decision removes the *domain's* obstacles to replay and resume, which makes the
platform's the only ones left — and therefore the visible ones.

## 7. What this decision does not permit

* A domain may not read execution metadata to decide what to generate — not a
  completion record, not a position, not a run identity, not an attempt count.
* A domain may not keep a record of having run. Absence of data is the founding
  condition, and it is the only one.
* A unit of work may not be identified by, or seeded from, its position in a
  sequence. It is identified by its business moment.
* A derived value may not be trusted in preference to the history it derives
  from, and may not be retained in a form the history could not rebuild.
* The platform may not read business data to make an execution decision. The
  separation is symmetrical, and a violation in that direction is the harder one
  to see.
