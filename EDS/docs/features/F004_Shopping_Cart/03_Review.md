# F004 - Review

| Field | Value |
| --- | --- |
| Outcome | Complete |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pytest`, `ruff check .`, `ruff format --check .`, `mypy eds`, end-to-end CLI run |

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| `shopping_carts.parquet` generated | 914 rows (spec expects 700–1000) |
| `cart_items.parquet` generated | 1,703 rows (spec expects 1500–2500) |
| Carts reference an existing customer | Declared foreign key; a test also asserts the customer matches the session owner |
| Carts reference an existing session | Declared foreign key, declared unique so a session holds at most one cart |
| Items reference an existing cart | Declared foreign key with an injected-orphan test |
| Items reference an existing product | Declared foreign key plus a price-agreement test |
| Items reference an existing product view | Declared foreign key, populated even for wishlist-sourced items |
| Wishlist items reference a valid wishlist | Nullable foreign key with product and customer agreement checks |
| Product IDs match their origin | Validated against both the product view and the wishlist entry |
| `item_count` equals the item rows | Counted from the items rather than asserted alongside them |
| Timeline validation passes | Cart inside its session, item after its source, removal after add |
| Referential integrity passes | Zero issues on generated data |
| CLI works | `eds generate commerce` exits 0 and writes two datasets |
| Unit tests pass | 910 passed (was 778; F004 adds 132) |
| Ruff passes | All checks passed |
| MyPy passes | No issues in 139 source files |
| Deterministic output | Frame equality at generator, orchestrator, and CLI levels |

Measured at the default scale: 1.86 items per cart, cart status 53/41/6
against the documented 55/40/5, quantity 71% single units, and 15.9% of
sessions producing a cart.

## Design decisions

### Carts are planned, then filled, then built

A cart's own columns depend on the items it ends up holding, so generating it
first would mean writing `item_count` and hoping the items agree.

`plan_carts` decides which sessions start a cart and with what status and
target size. `generate_cart_items` fills them. `generate_carts` then counts
what actually arrived and brackets the real add and remove times with
`created_at` and `updated_at`. A planned cart that received nothing is
dropped, which is what makes "every cart contains at least one item" true by
construction rather than by luck.

### Cart rate reads the persona's own propensity

F003.1 already records `cart_probability` per customer. F004 scales it by a
single configured rate rather than inventing a second set of per-persona
numbers, so a loyal customer fills a cart more often than a window shopper
because the persona says so, not because F004 repeats it.

### A bounce never starts a cart

F003.1 records a bounce as one page view. Letting a bounced session hold a
cart would contradict it. This also keeps the cart rate near the documented
volume without a second tuning knob.

### The wishlist flow crosses sessions

A wishlist entry saved weeks earlier is exactly the flow the specification's
timeline describes, so wishlist candidates are drawn from the customer's whole
history rather than the current session. The add itself happens during the
cart's own session, which is the point the first timeline defect turned on.

### One row per product, quantity carries repeats

A cart holds each product once; wanting three of something is `quantity`, not
three rows. Validated as a uniqueness check on `(cart_id, product_id)`.

## Assumptions

1. **A wishlist-sourced item still carries `product_view_id`.** The
   specification requires every item to reference an existing product view,
   and a wishlist entry records the view it was saved from, so the chain is
   preserved rather than broken. `wishlist_id` is what distinguishes the two
   sources.
2. **`configs/commerce.yaml` lives at the repository root.** The module
   structure in the specification shows it under `eds/`, but every earlier
   feature's configuration is in the top-level `configs/` directory and the
   loader reads from there.
3. **`unit_price` is the product's list price.** Discounts, coupons, and the
   discount engine are all explicitly out of scope, so there is nothing to
   apply to it.
4. **Removed items still count towards `item_count`.** The rule reads
   "`item_count` equals the number of cart_items", which counts rows; a
   removal is recorded by `removed_at` rather than by deleting the row.
5. **`removed_at` stays inside the session.** The specification only requires
   it to be after `added_at`; keeping it in the session avoids inventing a
   post-session lifetime that later features would have to honour.
6. **The "5+" size bucket spreads across `max_cart_items`**, which defaults to
   seven, so the tail is a real tail rather than a spike at exactly five.
7. **`cart_status` is drawn per cart rather than derived.** F005 will decide
   what actually happens at checkout; F004 only records the intent, and a
   `CHECKED_OUT` cart here is a label, not an order.

## Test coverage

910 tests total; F004 contributes 132.

| Area | Tests | Notable failure paths |
| --- | --- | --- |
| Cart planning and building | 24 | Unknown persona; zero rate; a planned cart that receives no items |
| Cart items | 26 | Empty product views or products; no planned carts; empty wishlists |
| Orchestrator and configuration | 28 | Each of six missing upstream datasets; inverted quantity range |
| Commerce validation | 36 | Every documented check proved by injecting the defect, including all six foreign keys and the nullable wishlist key |
| CLI | 18 | Missing upstream data; missing product views; a config override that must not reset settings |

Distribution tests cover the cart status split, the cart size split, and the
quantity split. Persona behaviour is asserted as comparisons: loyal customers
check out more than window shoppers, researchers hold larger carts than
impulse buyers, and the profile ordering itself is asserted against the
specification's wording.

A CLI test reads every earlier Parquet file before and after running commerce
and asserts the bytes are unchanged, which is the direct check on "do not
regenerate previous datasets".

## Defects found and fixed

1. **Wishlist items were added before their session started.** The add time
   was computed as "wishlist time plus a delay", which for an entry saved in
   an earlier session lands in the past - 16 carts ended up opening before
   their own session. Fixed by flooring the add time at the cart's session
   start.
2. **The floor was one second too low.** With the add clamped to exactly the
   session start, `created_at = min(added_at) - 1s` still fell a second
   before the session. The floor now leaves the same lead clear, and the
   constant is shared between the two generators rather than duplicated.
3. **A dict literal was closed with a parenthesis.** Caught by a syntax check
   before the first run.
4. Status weights initially produced a 50/44/6 split; the per-persona weights
   were nudged to land on 53/41/6 against the documented 55/40/5.

## Known limitations

1. **`cart_status` is independent of what is in the cart.** A cart holding one
   cheap item is as likely to be marked `CHECKED_OUT` as a full one. Basket
   value should influence conversion, but pricing logic beyond `list_price` is
   out of scope here.
2. **`ACTIVE` carts are not treated as still open.** The status is drawn like
   any other, so an active cart from four years ago sits in the data. A real
   catalog would only leave recent carts active.
3. **Cart items never span sessions.** Everything is added during the session
   that opened the cart, so a cart is never revisited later. Real abandoned
   carts often are.
4. **The wishlist share of items is small** - 39 of 1,703 at the default
   scale - because F003.3 only gives about 8% of customers a wishlist at all.
   The persona wishlist rates are visible in the profiles but barely visible
   in the data.
5. **"Bargain Hunter: frequently promotion-driven" is not modelled.** The
   product view a cart item comes from carries a `view_source`, so the
   information exists, but F004 does not bias selection towards
   promotion-sourced views.
6. **No cart is abandoned and later recovered.** Each session's cart is
   independent, and there is no notion of the same products reappearing.

## Suggested improvements

- Bias cart item selection towards promotion-sourced product views for bargain
  hunters, using the `view_source` F003.3 already records.
- Let basket size and value influence `cart_status`, so large carts convert
  differently from single-item ones.
- Restrict `ACTIVE` to carts from recent sessions, and let older ones fall to
  `ABANDONED`.
- Model cart persistence across sessions, so an abandoned cart can be revisited
  and either extended or converted.
- Correlate quantity with product category - groceries are bought in multiples,
  televisions are not.
- Reconsider the wishlist-to-cart rate once wishlist adoption in F003.3 is
  revisited; the two are tuned independently today.
