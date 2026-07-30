# ADR-003 - Configuration Preservation

**Status:** Accepted

**Applies from:** F003.1 (documented retrospectively, after two defects)

---

## Decision

Completed configuration sections are never discarded during configuration
merging.

When a command-line override rebuilds the run configuration, every section it
does not touch is carried through unchanged. A section is never allowed to
fall back to its defaults as a side effect of overriding a different one.

---

## Why

`SimulationConfig` is assembled from one section per feature. The CLI rebuilds
it whenever an override such as `--seed` or `--products` is passed, because
the models are frozen.

A rebuild that lists only the sections it can override silently resets every
other section to its class defaults. The failure is invisible in normal use -
the defaults match the shipped YAML - and only appears once a user edits a
configuration file and passes an unrelated flag.

---

## The defect this documents

This has now been introduced twice:

| Introduced | Section lost | Found by |
| --- | --- | --- |
| F003.1 | `journey` | Reading the code during F003.2 |
| F003.3 | `engagement` | The regression test added in F003.2 |

Both times the cause was identical: a new section was added to
`SimulationConfig` without being added to the override rebuild in
`_apply_overrides`.

---

## How it is enforced

Every feature from F003.2 onward carries a CLI test that:

1. copies the whole shipped `configs/` directory to a temporary location,
2. overwrites the one file under test with non-default values,
3. runs the command with an unrelated `--seed` override,
4. asserts the edited values survived into the generated data.

The tests copy the entire directory rather than a hand-written file list, so
they stay correct as later features add configuration files - an earlier
version listed files by name and went stale the moment F003.3 added one.

---

## Consequences for a new feature

Adding a section to `SimulationConfig` means touching three places, and the
third is the one that gets forgotten:

1. the model and its loader,
2. `load_config`,
3. **the rebuild inside `_apply_overrides`.**

If a fourth section is ever lost this way, the function should be restructured
to carry sections through by default rather than by enumeration.
