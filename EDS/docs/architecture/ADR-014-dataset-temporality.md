# ADR-014: Every Dataset Declares How It Behaves in Time

**Status:** Accepted (Retail Temporal Evolution)

**Applies from:** the Retail temporal layer onward.

**Related:** ADR-010 (state history over mutable state), ADR-011 (one dataset
per business entity), ADR-012 (business document immutability), ADR-013
(history is the state), PADR-003 (adapters know nothing about business).

## Context

When a simulated day ends, something has to decide what happens to each of the
thirty-nine datasets. Some of them accumulate. One is replaced. One has rows
that move. Most are not written at all.

Deciding that per dataset, at the point of writing, would put thirty-nine
answers in thirty-nine places and no way to check any of them.

## Decision

Every Retail dataset declares exactly one temporality, in
`eds.domains.retail.temporal.temporality.DATASET_TEMPORALITY`, and the merge
step reads that declaration to decide what to do. A dataset with no declaration
raises rather than defaulting: silently appending to something that should have
been replaced corrupts a history quietly, and quietly is the worst way for that
to happen.

A test asserts the classification covers exactly the datasets the domain says it
produces, so a feature that adds a dataset must say how it behaves in time
before it can run for a second day.

## The four kinds

| Kind | Rule when a day arrives | Datasets |
| --- | --- | --- |
| **Static** | Keep history, discard the day | The thirteen fixtures: geography, the commercial catalogues, the supply chain, the category tree, brands, products |
| **Append-only** | History first, the day's rows after it, nothing altered | Twenty-four: customers and what registers with them, the whole journey, all of commerce |
| **Mutable snapshot** | Take the day's version whole | `inventory` |
| **Slowly changing** | Keep untouched rows, take the day's version of the ones it touched, order by identity | `customer_loyalty` |

### Why four and not three

Append-only and mutable-snapshot are the obvious pair: a history that
accumulates, and a current picture that is replaced.

**Slowly-changing earns its place** because `customer_loyalty` is neither. It is
one row per customer, enrolled once, kept for the life of the customer, whose
balance and tier move. Treated as append-only it would grow a second row per
customer per day; treated as a snapshot it would be rewritten whole, which is
what happens but says nothing about the row's identity surviving. The merge that
implements it - keep what the day did not touch, take what it did, order by the
primary key - is the only one of the four that needs the key.

**Static is worth naming separately from mutable-snapshot** even though both are
"one current picture". Static means *nothing writes it after the founding day*,
which is a stronger promise and a cheaper one: over three hundred and sixty-five
days the thirteen static datasets are written once.

### Why `customers` is append-only

A person who registered on the fourth of March registered on the fourth of March
for ever, and every column on the row is a fact about registration - the name
they gave, the channel they came through, the risk score they were scored at.
Nothing on it is a running total: there is no lifetime-value column, because
lifetime value is a sum over orders and ADR-001 says derive rather than store.

`lifecycle_stage` is the one column with a claim to move, and ADR-013 records
the argument for making it move as a question rather than answering it here.

### Why `inventory` is the only snapshot

Stock is not a record of what happened - the order lines are that. It is a
picture of now, and yesterday's picture is not history, it is a stale number.

It is also the only dataset whose current value is *recomputed* rather than
adjusted: opening stock is a pure function of the catalogue and the seed,
cumulative demand is a sum over the order history, and the reorder policy is a
function of both. That makes today's stock a function of history alone, which is
what lets a run be stopped on any day and picked up on any later one without the
two disagreeing (ADR-013).

## This classification belongs to Retail

A dataset's temporality is a statement about a *business*, not about storage.
That inventory is a snapshot and orders are history is true whether they are
Parquet files, tables or topics, and it is not something an adapter can know or
should ask.

So the adapters are untouched by this decision (PADR-003). They are handed
frames and told to write them; what makes those frames the right frames happened
before they were called.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| **Decide at the point of writing** | Thirty-nine answers in thirty-nine places, none of them checkable. |
| **Infer from the schema** | A snapshot and a history are indistinguishable by shape. `inventory` and `order_lines` both have a surrogate key and foreign keys. |
| **Let the adapter declare a write mode** | Puts a business fact in the storage layer, and every new adapter would have to be told all thirty-nine again. |
| **Two kinds: append or replace** | Loses the two distinctions that matter - that a static dataset is never written again, and that a slowly-changing row keeps its identity. |
| **A fifth kind for deletion** | Nothing in Retail deletes a row, and adding a kind nothing uses is how a taxonomy stops being read. |

## Consequences

**Good.** "Never rewrite history" is a property of the code rather than a hope:
there is one rule per kind, and no rule anywhere else.

**Good.** A day writes only what it changed. On an evolved day the master-data
stage writes one file rather than fourteen, which over a year is the difference
between four thousand seven hundred writes and three hundred and sixty-five.

**Good.** The classification is a description of the domain that a reader can
consult. "Which of these datasets can change under me?" has an answer, and the
answer is two.

**Cost.** A new dataset cannot run for a second day until somebody has decided
what it does when a day passes. That is the intent, and it will be experienced
as friction.
