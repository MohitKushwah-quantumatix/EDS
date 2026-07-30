# F003.3 - Review

| Field | Value |
| --- | --- |
| Outcome | Complete |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pytest`, `ruff check .`, `ruff format --check .`, `mypy eds`, end-to-end CLI run |

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| `product_views.parquet` generated | 88,248 rows (spec expects 80,000–90,000) |
| `wishlists.parquet` generated | 988 rows (spec expects 800–1,500) |
| Views reference an existing session | Declared foreign key; a test also asserts the session matches the category view's |
| Views reference an existing customer | Declared foreign key plus an inheritance test |
| Every product belongs to the referenced category | Path-containment rule with an injected cross-section defect test |
| Search-originated views reference a valid search | Nullable foreign key plus category, session and ordering checks |
| Wishlist entries originate from product views | Product, customer, and source all matched against the originating view |
| Duplicate wishlist products prevented | Dedupe on `(customer_id, product_id)`, validated |
| Timeline validation passes | Views inside their session and after their category view; wishlists after their view |
| Referential integrity passes | Zero issues on generated data |
| CLI works | `eds generate journey` exits 0 and writes six datasets |
| Unit tests pass | 778 passed (was 647; F003.3 adds 131) |
| Ruff passes | All checks passed |
| MyPy passes | No issues in 126 source files |
| Deterministic output | Frame equality at generator, orchestrator, and CLI levels |

Measured at the default scale: 3.12 product views per category view (spec:
average 3), average dwell 43.1 seconds (spec: approximately 45), popularity
split 68/20/11 (spec: 70/20/10), and 8.2% of customers holding a wishlist
(spec: 8–12%).

## Design decisions

### Category containment is by subtree, not by equality

F001 attaches products to leaf categories only; F003.2 browses categories at
every level. Requiring `product.category_id == category_view.category_id`
would leave 40 of 168 categories unable to produce a single product view, and
volume would fall well short of the specified range.

A product view therefore inherits the browsed `category_id` and draws its
product from that category's **subtree**. Validation checks it by category
path: the product's own path must equal the browsed path or start with it plus
a separator. A test injects a product from a different top-level section and
asserts the rule fires.

### Product views live in session time, not category-view time

A category view lasts at most 180 seconds, but the specification asks for
three product views per category view averaging 45 seconds each. Nesting them
inside the category view window would force durations far below the stated
average. They are instead placed between the category view and the end of the
session, which is what the stated data-quality rule requires ("no timestamp
outside the session"). Each view is clamped so it also *ends* inside the
session.

### View source is conditioned on search availability

Only about 40% of category views produce a search, so drawing `view_source`
from the flat 55/25/10/5/5 split and falling back when no search exists would
deliver a Search share near 10%. Two weight rows are used instead - one for
category views that produced a search, one for those that did not - chosen so
the **marginal** distribution lands on the specified split. The achieved split
is 56/19/12/7/5.

Persona preferences ride on top: the bargain hunter's promotion weight and the
loyal customer's brand-page weight are multiplied, which is what makes
"frequently enters from Promotion" and "returns to familiar brands" visible in
the data. Both are asserted as share comparisons against the other personas.

### Popularity weights are calibrated, not derived

The obvious weight - view share divided by catalog share - only produces the
target distribution when every pool mirrors the catalog. Leaf pools hold about
eight products, and roughly one in six contains no popular product at all,
which flattens the result: the derived weights achieved 57/27/17 rather than
70/20/10. The weights are calibrated against the achieved distribution
instead, and a test asserts the outcome rather than the input.

Sampling uses a precomputed cumulative weight table per category and a binary
search. A linear scan would be 88,000 draws over pools up to catalog-wide.

### Wishlists are modelled as adoption, then adding

With around 85 product views per customer, any single per-view probability
high enough to fill a wishlist would give almost every customer one - the
specification asks for 8–12%. Each customer is first decided to be a wishlist
user from a per-persona adoption rate; only adopters then get a per-view
chance, scaled from the `wishlist_probability` F003.1 already records for
their persona. This uses the existing persona column rather than inventing a
parallel one, while still honouring the ordering this specification states.

## Assumptions

1. **"Same category" means the product sits under the browsed category.**
   Forced by F001's leaf-only product attachment; see above.
2. **Product views may overlap each other within a session.** They are placed
   independently in the window after their category view rather than being
   serialised, so two product pages can be open at once. Serialising them
   would truncate later category views' product counts in short sessions.
3. **A bounce session still produces product views.** The specification sets a
   minimum of one product view per category view with no bounce exception.
   This compounds the `pages_viewed` limitation already recorded in the F003.2
   review.
4. **Search-text-to-product consistency is enforced at the category level
   only.** The specification says "where practical". F001 product names take
   the form `{brand} {category} {token} {number}` - "Owens-Martinez Health
   Classic 1234" - and share no vocabulary with search phrases like "Gaming
   Laptop", so textual matching is not achievable against the existing master
   data. The enforceable part, that the search and the product are in the same
   category, is validated.
5. **A search-sourced view falls back to Category** when the chosen search
   leaves no room before the session ends. Inventing a search or letting the
   view spill past the session would break a stated rule.
6. **`added_from_source` mirrors the originating product view's source**, and
   is validated as such.
7. **Popularity tiers are assigned globally**, from a seeded shuffle, so a
   product's popularity is a property of the product rather than of the pool
   it is drawn from.

## Test coverage

778 tests total; F003.3 contributes 131.

| Area | Tests | Notable failure paths |
| --- | --- | --- |
| Product views | 33 | Empty categories or products; unknown persona; unknown category pool |
| Wishlists | 17 | Zero rate, no product views, unknown persona |
| Orchestrator and configuration | 26 | Each of seven missing upstream datasets; inverted ranges |
| Engagement validation | 44 | Every documented check proved by injecting the defect, including all eight foreign keys and the nullable search key |
| CLI | 11 | Missing `products.parquet`; a config override that must not reset settings |

Distribution tests assert the popularity split, the view source split, the
per-category-view average, and the average dwell time. Persona behaviour is
asserted as comparisons: researchers dwell longer than impulse buyers, bargain
hunters view more from promotions, loyal customers more from brand pages.

## Defects found and fixed

1. **`_apply_overrides` dropped the new configuration section - again.** The
   same class of bug fixed during F003.2: adding `EngagementConfig` to
   `SimulationConfig` without adding it to the override rebuild meant any
   command-line override silently reset engagement settings to their defaults.
   This time the regression test added in F003.2 caught it immediately, along
   with a second failure showing that test's own file list had gone stale.
   Both config tests now copy the whole `configs/` directory, so they stay
   correct as later features add files.
2. **61 timeline violations from the search bump.** Moving a product view to
   after its search could push it past the end of the session. Fixed by
   checking there is room before accepting the search, and falling back to a
   category-sourced view otherwise.
3. **Popularity achieved 57/27/17 instead of 70/20/10.** Diagnosed as the
   small-pool effect described above and fixed by calibrating the weights.
4. A mypy redefinition error where a build-loop variable and a main-loop
   variable shared the name `search_id` with different types.

## Known limitations

1. **Product views can overlap in time within a session.** Two product pages
   may be open simultaneously. Realistic for tabbed browsing, but a strict
   funnel analysis would need them serialised.
2. **Category views and product views together can exceed the session's
   `pages_viewed`.** This extends the F003.2 limitation: the page budget
   recorded in F003.1 is now spent by two features that do not consult it.
   All three should be reconciled together rather than patched individually.
3. **Search text and product name are unrelated.** Enforced at the category
   level only, for the reason given under assumptions. Making this real needs
   product names built from the same vocabulary the search generator uses,
   which is F001 work.
4. **Popularity is global, not per category.** A product that is popular
   overall is popular in every pool it appears in; there is no notion of a
   product that sells well only within its niche.
5. **The popularity weights are calibrated for the current catalog shape.** A
   very different products-per-leaf ratio would shift the achieved split, and
   the test tolerance (±8pp) would eventually catch it.
6. **Wishlist entries are never removed**, and a customer's wishlist grows
   monotonically across the whole five-year window.

## Suggested improvements

- Reconcile `pages_viewed` across F003.1, F003.2 and F003.3 in one pass, so
  the session's page budget is spent by category views and product views
  together rather than tracked independently.
- Build F001 product names from the F003.2 search vocabulary, which would make
  genuine search-text-to-product matching possible.
- Derive the popularity weights at runtime from the actual pool composition
  rather than using calibrated constants.
- Give popularity a per-category dimension so niche products can lead their
  own section.
- Correlate view duration with the persona's `research_depth` trait, which
  F003.1 already records but F003.3 does not read.
- Model wishlist removal, and let a saved product influence later sessions.
