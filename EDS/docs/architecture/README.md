# Architecture Decision Records

Each ADR records one decision, why it was taken, and what it obliges future
features to do.

| ADR | Decision | Applies from |
| --- | --- | --- |
| [ADR-001](ADR-001-derived-data-over-random-data.md) | Derived data preferred over random data | F001 |
| [ADR-002](ADR-002-generate-causality-not-coincidence.md) | Generate causality, not coincidence | F003.1 |
| [ADR-003](ADR-003-configuration-preservation.md) | Configuration preservation | F003.1 |
| [ADR-004](ADR-004-subtree-category-matching.md) | Subtree category matching | F003.3 |
| [ADR-005](ADR-005-deterministic-generation.md) | Deterministic generation | F001 |
| [ADR-006](ADR-006-feature-immutability.md) | Feature immutability | F006 |
| [ADR-007](ADR-007-single-source-of-financial-truth.md) | Single source of financial truth | F006 |
| [ADR-008](ADR-008-golden-record-principle.md) | Golden record principle | F006 |
| [ADR-009](ADR-009-derived-data-over-random-data.md) | Derived data over random data (commerce chain) | F006 |
| [ADR-010](ADR-010-state-history-over-mutable-state.md) | State history preferred over mutable state | F006 |
| [ADR-011](ADR-011-one-dataset-per-business-entity.md) | One dataset per business entity | F006 |
| [ADR-012](ADR-012-business-document-immutability.md) | Business document immutability | F006 |
| [ADR-013](ADR-013-history-is-the-state.md) | History is the state | Temporal evolution |
| [ADR-014](ADR-014-dataset-temporality.md) | Every dataset declares how it behaves in time | Temporal evolution |

## Two groups

**ADR-001 to ADR-005 document existing behaviour.** They were written
retrospectively to record decisions already taken and already implemented
during F000 to F005. They changed no code.

**ADR-006 to ADR-012 govern future features.** They apply from F006 onward.
F000 to F005 are frozen under ADR-006 and are not revisited to comply
retroactively; where the existing code already satisfies one of them, that is
noted in the ADR's "Current state" section.

**ADR-013 and ADR-014 govern Retail over simulated time.** They apply to
anything that runs the domain for more than one business date. The founding day
is unchanged by both, which is why F001 to F010 need no revision: a snapshot is
a simulation of one day, and ADR-013's rules are silent on it.

## Overlapping records

ADR-001 and ADR-009 share a title. ADR-001 is the general decision, applied
from F001; ADR-009 names the parents for the commerce entities specifically.
ADR-009 adds no new rule and cross-references ADR-001. If the two are ever
consolidated, ADR-001 is the one to keep.

ADR-010 and ADR-012 are two halves of one decision: state changes live in a
history dataset, and the document they belong to is frozen. A feature
implementing a business document needs both.

ADR-013 and ADR-014 are also two halves of one decision. ADR-013 says a day is
added to a history rather than replacing it; ADR-014 says what "added" means for
each of the thirty-nine datasets. Neither is usable without the other.
