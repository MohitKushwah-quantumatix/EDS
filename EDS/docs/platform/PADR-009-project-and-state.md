# PADR-009: The Project Owns Identity and State

**Status:** Accepted (P003)

**Resolves:** the deferred decision recorded in PADR-007 about `Project`'s shape.

**Builds on:** PADR-004 (platform owns lifecycle), PADR-008 (plans are inert).

## Context

P001 declared `Project(name, domain, seed, output_directory)` as a placeholder
with no consumer, and `state.py` as an empty module. PADR-007 noted that
`Project` duplicated `PlatformConfig` on `seed` and `output_directory`, and
deferred the fix on the grounds that "redesigning a placeholder before its first
consumer is how placeholders become wrong in ways that are expensive to undo".

P003 is that consumer. A durable project is what makes a simulation resumable,
and resumability is the thing every later phase — clock, scheduler, growth —
depends on.

## Decision

Five concepts, each with one job.

| Concept | Owns | Mutability |
| --- | --- | --- |
| `ProjectManifest` | Identity: id, name, domain, seed, creation time, versions | Immutable after creation |
| `SimulationState` | Progress: simulated date, completed stages, last identifiers | Replaced, never mutated |
| `Workspace` | Where bulk data lives | Fixed at creation |
| `StateStore` | How documents persist | Protocol; `FileStateStore` today |
| `Project` | The handle binding the three | Immutable |

### Identity and state are separate documents

The split is not filing convenience. Identity is what makes two runs *the same
project*; state is what changes between them. The seed lives in the manifest
for exactly that reason — a seed that could be edited between runs would make
"the same project" meaningless.

### The store's currency is a *document*, not bytes and not a file

The brief said "avoid coupling to JSON or YAML if a cleaner abstraction
exists". It does, and it is the level the interface sits at.

```python
class StateStore(Protocol):
    def exists(self, key: str) -> bool: ...
    def read(self, key: str) -> dict[str, Any]: ...
    def write(self, key: str, document: Document) -> None: ...
```

A `Document` is a plain mapping of primitives — what a JSON object, a YAML
mapping, a database row and an object body can all carry. Keys are logical
names (`"manifest"`, `"state"`), not paths.

JSON is therefore an implementation detail of `FileStateStore`, and replacing
it touches that class and nothing else. A test drives an entire project
lifecycle through an in-memory store that never touches a filesystem, which is
the only real proof the abstraction is at the right level.

### Three versions, owned explicitly

`PLATFORM_CONTRACT_VERSION` versions the domain and adapter *contracts*.
`MANIFEST_VERSION` versions the manifest document's shape. `STATE_VERSION`
versions the state document's shape — and will move far more often than the
manifest as runtime features arrive, which is precisely why it must not share
the manifest's number.

The distribution version is recorded for provenance but is deliberately **not**
a compatibility gate: semantic versioning of a distribution says nothing
reliable about document compatibility.

Compatibility is exact-match, because migration is a non-goal. A newer document
says "upgrade"; an older one says "migration is not implemented". Two different
remedies, so two different messages. Guessing at an older document's missing
fields is how corruption becomes invisible.

### Loadable and usable are different questions

Opening a project reads and checks its manifest. It does **not** resolve the
domain, and it does not read state.

That matters more than it looks. If opening required the domain to be
registered, a project would be unopenable on a machine where its domain is not
installed — which is exactly when you most want to read the manifest, to
discover *what the project needs*. So an unregistered domain is a
`ProjectIssue` from `validate()`, not an exception from `open_project()`.

Likewise, a project that has never run has no state document, and `read_state()`
returns an empty state rather than raising. A caller should not have to
distinguish "nothing has happened yet" from "something is wrong".

### State is stored, never advanced

`SimulationState` is frozen. Updating it means `dataclasses.replace` and a
write. Nothing in this module increments a date or appends a completed stage,
because deciding those things is the clock's and the scheduler's job.

Two invariants are enforced rather than assumed: a stage cannot be recorded as
completed twice (that means a lost write or a scheduler bug, and accepting it
silently would hide both), and an identifier cannot be negative.

`completed_stages` is an ordered tuple rather than a single "last completed
execution". Stages at one dependency level may complete in any order, so a
resumed run needs to know *which* are done, not merely which was last —
`last_completed_stage` is a derived property.

There is no `updated_at`. When a document was written is the store's business,
and a field that changed on every write would mean the same state never
serialises to the same bytes twice.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| **Separate `ProjectMetadata` and `ProjectManifest`** | A manifest *is* metadata plus the version of the document carrying it. Two dataclasses that always travel together add a name without adding a distinction. Merged. |
| **Byte-oriented store** (`read(key) -> bytes`) | Pushes serialisation onto every caller, so every caller must agree on a format and the format leaks everywhere. |
| **Typed store** (`read_manifest() -> ProjectManifest`) | The store would know about project types, so a second document kind means a new method — and a database store would have to know what a manifest is. |
| **Seed in state rather than the manifest** | Would let the seed change between runs, which destroys reproducibility and with it the meaning of "the same project". |
| **Resolve the domain when opening** | Makes a project unopenable exactly when inspecting it matters most. |
| **Keep P001's `Project` and add a separate handle type** | Three project-shaped types where two will do. The placeholder had one consumer — a test — so replacing it cost nothing. |
| **Mutable state with `advance()` / `complete()`** | That is runtime, and runtime is a non-goal. It would also throw away the property that a state document is a comparable value. |

## Consequences

**Good.** PADR-007's deferred question is closed with a consumer in hand rather
than by guesswork. The `Project`/`PlatformConfig` duplication is gone:
`PlatformConfig` is run configuration, `ProjectManifest` is durable identity,
and they no longer restate each other.

**Good.** Persistence is provably storage-independent — an in-memory store
drives a full project lifecycle in the tests.

**Cost.** The P001 `Project` is superseded and its two architecture tests were
rewritten. That is the second time a P001 platform placeholder has been
replaced on contact with a real consumer, which is the pattern working as
intended rather than a failure: placeholders are cheap to declare and cheap to
replace, and both replacements were documented.

**Cost.** Nothing consumes a project yet. The CLI still writes to
`PlatformConfig.output_directory` and knows nothing about workspaces. Wiring
them would change CLI behaviour, which is out of scope.

**Limitation.** `Workspace` is filesystem-shaped. Datasets are large and
adapters write by location, so a `Path` is honest today; a workspace backed by
object storage would need a location abstraction. The *store* is already
storage-independent, which is the part that mattered.

**Limitation.** Duplicate project identifiers are only detectable within a
workspace — creating over an existing project is refused. Global uniqueness
would need a project registry, which does not exist and is not needed while
identifiers are UUIDs.

## Future integration

**Scheduler.** Takes a `Project` and an `ExecutionPlan`. It reads
`state.completed_stages` to decide what remains, narrows the plan with
`build_execution_plan(domain, targets=...)`, and writes state back after each
stage. The plan stays inert; the project holds what was learned.

**Clock.** Reads and writes `state.current_date`. A daily simulation is the
same plan executed once per tick, with the clock advancing the date and the
project persisting it. Nothing in P003 needs to change for that — which is the
test of whether the state model was drawn correctly.

**Execution plans.** Remain independent of projects, and a test asserts it: a
plan is derived from a domain's declarations, so the same plan serves every
project of that domain. Binding them would make plans unshareable and
uncacheable for no benefit.

**Growth and snapshots.** `last_identifiers` is already the hook growth needs to
continue numbering across runs. `snapshots/` is a declared, uncreated path.

## What this decision does not permit

The project package must not gain the ability to run anything. A test forbids
it importing `polars`, `eds.domains`, `eds.adapters` or `eds.platform.execution`
— the last of those deliberately, so that state cannot start interpreting
plans. If a future phase needs the two together, that belongs in a scheduler
that depends on both, not in either one.
