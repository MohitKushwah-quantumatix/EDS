# F003.2 - Review

| Field | Value |
| --- | --- |
| Outcome | Complete |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pytest`, `ruff check .`, `ruff format --check .`, `mypy eds`, end-to-end CLI run |

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| `category_views.parquet` generated | 28,310 rows at the default scale (spec expects 28,000–32,000) |
| `search_history.parquet` generated | 11,460 rows (spec expects 10,000–14,000) |
| Views reference an existing session | Declared foreign key; orphan check |
| Views reference an existing customer | Declared foreign key; a test also asserts the customer matches the session's owner |
| Every category exists | Declared foreign key against `categories` |
| Searches reference session, customer, view, category | Four declared foreign keys, each with an injected-orphan test |
| Search category matches its view | Dedicated rule plus a vocabulary test |
| Timeline validation passes | Views and searches inside their session; searches after the first view |
| Referential integrity passes | Zero issues on generated data |
| CLI works | `eds generate journey` exits 0 and writes four datasets |
| Unit tests pass | 647 passed (was 516; F003.2 adds 131) |
| Ruff passes | All checks passed |
| MyPy passes | No issues in 117 source files |
| Deterministic output | Frame equality at generator, orchestrator, and CLI levels |

Volumes at the default scale: 5,752 sessions, 28,310 category views (4.92 per
session), 11,460 searches (1.99 per session). All three inside the documented
ranges.

## Design decisions

### Searches inherit their category from the view they belong to

`search_history.category_id` is copied from the attached `category_view`, not
sampled. The "Electronics -> Coffee Table" failure the specification calls out
is therefore impossible by construction rather than by luck, and the validator
proves it with a join rather than by inspecting text.

Search text is then drawn from a vocabulary keyed by that category's
**top-level ancestor**, so a search on `Electronics/Computers/Laptops` uses the
Electronics vocabulary. A test walks every generated row and asserts the text
came from its own category's vocabulary.

### Search timing is derived from the view window

A search timestamp is `view.timestamp + 1..view.duration` seconds. That single
rule satisfies three separate requirements at once: the search falls inside
its session, it happens after the first category view, and it happens while
the customer is actually on that category page. No separate clamping logic is
needed, and no generated row can violate the chronology.

### Bounce sessions view one category and never search

F003.1 records a bounce as a single page view. A bounce therefore produces
exactly one category view and no searches. Without this the two features would
contradict each other: a "bounced" session would show eight category pages.

### Views are packed into the session's real duration

Durations are allocated with a running reserve - each view keeps at least
`min_view_seconds` for every view still to come - so the views always fit
inside the session that contains them, and no view can outlast its session.
The number of views is also capped by `duration // min_view_seconds`, which is
what makes a short session hold few views rather than impossible ones.

### Browsing stays in one section

After the first category, the next view stays under the same top-level
category 65% of the time. Sampling uniformly from all 168 categories would
model a customer teleporting around the store; a test asserts over half of
consecutive views share a section.

### Entry method is inherited, then persona-driven

The first view's entry method comes from the session's `landing_page`, so
F003.1 and F003.2 agree about how the visit began. Later views use
persona weights, which is where "Bargain Hunter prefers Promotion Banner" and
"Loyal Customer frequently starts from Homepage" live. Both are asserted as
share comparisons against the other personas rather than absolute thresholds.

## Assumptions

1. **Nine additional search vocabularies were written.** The specification
   names five; F001 has fourteen top-level categories. Two of the five use
   different names in F001 - "Fashion" is `Clothing` and "Sports" is
   `Sports & Outdoors` - so those were mapped, and vocabularies added for
   Computers, Health & Beauty, Toys & Games, Grocery, Automotive, Books &
   Media, Office Products, Pet Supplies, and Garden & Outdoor. Without them,
   nine of fourteen sections could not produce a relevant search. A test
   asserts every F001 root has a vocabulary.
2. **`products.parquet` is not read.** It is listed as a dependency, but no
   F003.2 output field references a product - product views are explicitly out
   of scope. This matches the F003.1 decision. F001 product names are of the
   form `{brand} {category} {token} {number}`, which would make poor search
   text in any case.
3. **A search that returned no results was never clicked.** The specification
   allows `clicked_result` to be either value and `results_count` to be zero,
   but a click on nothing is incoherent. Enforced and validated.
4. **Qualifiers are added to about 30% of searches** ("Best", "Cheap",
   "Wireless"...), keeping phrases within the one-to-four word rule while
   avoiding a catalogue of only ~120 distinct strings.
5. **Categories at every level are browsable**, not just leaves. A customer
   browsing "Electronics" before "Electronics/Computers" is normal.
6. **A bounce session performs no searches**, following from the single page
   view it records.
7. **Browsing settings live in `configs/browsing.yaml`**; per-persona view and
   search ranges stay in the generators, as F003.1 does for persona profiles.

## Test coverage

647 tests total; F003.2 contributes 131.

| Area | Tests | Notable failure paths |
| --- | --- | --- |
| Category views | 26 | Empty categories; a session naming an unsupported persona |
| Searches | 28 | Zero-maximum configuration yields an empty, schema-shaped frame |
| Orchestrator and configuration | 27 | Each missing upstream dataset; every inverted range |
| Browsing validation | 39 | Every documented check proved by injecting the defect, including all seven foreign keys |
| CLI | 11 | Missing `categories.parquet`; a config override that must not reset settings |

Persona behaviour is asserted as comparisons rather than fixed numbers:
researchers view more categories than impulse buyers, bargain hunters use
promotion banners more than other personas, loyal customers use the homepage
more, and bargain hunters search more than impulse buyers.

## Defects found and fixed

1. **`_apply_overrides` silently dropped configuration sections.** Introduced
   in F003.1 and found while wiring this feature: the function rebuilt
   `SimulationConfig` from only the three sections it could override, so
   `journey` (and now `browsing`) reset to defaults whenever any command-line
   override was passed. Tests had not caught it because the defaults matched
   the shipped YAML. Fixed by carrying the untouched sections through, with a
   CLI test that edits `browsing.yaml` and asserts the values survive a
   `--seed` override.
2. **Category-view volume fell below the specified range.** An early ceiling
   tied views to the session's `pages_viewed` produced 24,966 views (4.34 per
   session) against a stated 28,000–32,000 and "approximately 5". The ceiling
   was my own addition, not a requirement, so it was removed; the result is
   28,310 views at 4.92 per session. The trade-off is recorded under known
   limitations.
3. A test asserted `"browsing" not in` the CLI help text, which the journey
   command's own description legitimately contains. Rewritten to assert that
   `eds generate browsing` does not exist.

## Known limitations

1. **Category views may exceed the session's `pages_viewed`.** F003.1 records
   `pages_viewed` for a session, and F003.2 does not constrain view counts to
   it, so a session recording four pages can carry six category views.
   Enforcing the constraint pushed volumes below the specified range, so the
   specification's per-persona ranges won. The two columns should be
   reconciled when product views arrive and the page budget is fully spent.
2. **Consecutive views can repeat a category.** The section-affinity rule
   picks from the section, so a customer may view the same category twice in a
   row. Real navigation would usually move on.
3. **Search text has around 120 base phrases plus qualifiers.** Realistic per
   row, but a distinct-search-terms count across the dataset looks small.
4. **`entry_method` of `SEARCH_RESULT` is not linked to an actual search.** A
   view can claim it arrived from a search result without a preceding row in
   `search_history`.
5. **Searches attach to a uniformly chosen view.** A real customer searches
   more often on a category page they lingered on.
6. **The bounce rate is inherited from F003.1 and is global**, so persona
   browsing depth varies but bounce likelihood does not.

## Suggested improvements

- Reconcile `pages_viewed` with category views once product views exist, so
  the page budget is spent across both rather than tracked independently.
- Link `SEARCH_RESULT` entry methods to a real preceding search row.
- Weight search attachment by view duration, so longer views attract more
  searches.
- Correlate `results_count` with the search phrase - a niche phrase should
  return fewer results than a broad one - and correlate `clicked_result` with
  the persona's purchase intent.
- Vary vocabulary by season for the seasonal shopper, whose sessions already
  concentrate in November and December.
- Avoid repeating the same category on consecutive views within a session.
