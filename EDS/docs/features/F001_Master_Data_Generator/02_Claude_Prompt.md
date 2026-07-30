# F001 - Claude Prompt

## Role

Senior Python Software Engineer implementing features for the Enterprise Data
Simulator (EDS).

Constraints given:

- Do not redesign the architecture.
- Do not invent new abstractions.
- Follow the provided Feature Specification exactly.
- If the specification is ambiguous, stop and report the ambiguity rather than
  making architectural decisions.

## Input supplied

`01_Business_Context.md` only - purpose, business objective, scope, out of
scope, business assumptions, design principles, dependencies, the thirteen
output datasets, and success criteria.

## Ambiguity raised before implementation

The business context defines **what** to generate and the invariants the
output must satisfy, but not the data model. Implementation required
decisions the document does not make:

1. Column definitions for all thirteen datasets, and the foreign key edges.
2. Identifier strategy (surrogate integers vs. ULIDs vs. business codes).
3. Configuration key names, nesting, defaults, and validation ranges.
4. Concrete price and capacity distributions behind "logical distributions"
   and "realistic capacities".
5. The geography source - real reference data vs. Faker vs. synthesised.
6. The scale strategy for 100 million products, which cannot be held in
   memory.

## Decision

The reviewer chose **"Implement now under stated assumptions"**: make every
open decision, document each as an explicit assumption, and build it.

The assumptions taken are recorded in `03_Review.md`.

## Accompanying change requests

Delivered in the same pass:

1. Move `eds/_version.py` to `eds/version.py` - it is public API, and the
   architecture references `from eds.version import __version__`.
2. Create `configs/simulation.yaml` and `configs/logging.yaml` with platform
   defaults only. Nothing business-specific.
3. Reorganise documentation so each feature owns a folder
   (`docs/features/F<NNN>_<Name>/`) containing a business context, the Claude
   prompt, and a review.

## Required report

1. Files created.
2. Files modified.
3. Commands executed.
4. Test results.
5. Any assumptions made.
