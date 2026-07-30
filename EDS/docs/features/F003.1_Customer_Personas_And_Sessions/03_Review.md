# F003.1 - Review

| Field | Value |
| --- | --- |
| Outcome | Complete |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pytest`, `ruff check .`, `ruff format --check .`, `mypy eds`, end-to-end CLI run |

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| `customer_personas.parquet` generated | 1,000 rows at the default scale |
| `sessions.parquet` generated | 5,752 rows at the default scale (spec expects ~6,000) |
| Every customer has exactly one persona | Coverage and duplicate checks; asserted at generator, orchestrator, and on-disk levels |
| Every session references an existing customer | Declared foreign key; orphan check |
| Session timestamps are valid | End after start, duration equals the timestamp difference |
| Session starts after customer registration | Enforced by construction and validated |
| Validation passes | Zero issues on generated data |
| CLI works | `eds generate journey` exits 0 |
| Unit tests pass | 516 passed (was 387; F003.1 adds 129) |
| Ruff passes | All checks passed |
| MyPy passes | No issues in 108 source files |
| Deterministic output | Frame equality at generator, orchestrator, and CLI levels |

## Design decisions

### Personas store the actual session count, not a nominal rate

`session_frequency` holds the number of sessions the customer really has.
That makes the two datasets checkable against each other: a test asserts the
row count per customer in `sessions` equals `session_frequency`, with zero
tolerance. A nominal "sessions per year" figure would have been unverifiable.

`average_session_minutes` works the same way - it is the centre the session
generator samples durations around, so the persona and the sessions cannot
drift apart.

### Session counts scale with tenure

Drawing straight from the persona ranges gives a weighted mean of 9.4 sessions
per customer, or ~9,400 at the default scale - well above the ~6,000 the
specification expects. It also implies every customer joined five years ago.

Scaling by tenure fixes both. The multiplier is `0.25 + 0.75 x tenure
fraction`, giving a mean of ~0.64 and therefore ~6.0 sessions per customer.
The observed output is 5,752. The floor of 0.25 means a customer who joined
yesterday still browses a little rather than not at all.

### Coherent device stacks

Operating system is chosen conditionally on device, and browser conditionally
on operating system. Sampling the three independently would put Safari on
Android and Windows on a phone, which is immediately visible in any device
breakdown chart. Two tests assert the constraint holds.

Traffic source and landing page are related the same way: a click from an
email or display campaign lands on campaign or promotion content, and a bounce
exits on the page it landed on whenever that page type is also a valid exit
page.

### Derived rather than sampled

Two values are computed rather than drawn, so they cannot contradict what sits
beside them:

- `purchase_probability` is `cart_probability x conversion ratio`, so a
  purchase can never be more likely than the cart it requires.
- A bounce's `pages_viewed` is 1 and its duration is drawn from a short band,
  because a bounce is a glance rather than a shortened visit.

### Reuse rather than duplication

No new validation machinery was written. `validate_referential_integrity`
already accepted a dataset-declaration parameter after F002, so duplicate
session ids, duplicate persona ids, invalid customer ids, and invalid
geography are all caught by the existing checks. A regression test asserts
F001 and F002 validation still return zero issues.

## Assumptions

1. **`products.parquet` and `categories.parquet` are not read.** They are
   listed as dependencies, but no F003.1 output field references a product or
   category - product views are explicitly out of scope. Requiring them would
   create a false coupling that a later feature would have to unpick. The
   command requires `countries`, `states`, `cities`, `customers`, and
   `customer_addresses`.
2. **The reference date comes from `customers.yaml`.** A session is anchored
   to its customer's registration date, so `JourneyConfig` deliberately has no
   reference date of its own; the two windows cannot disagree.
3. **Sessions start the day after registration at the earliest.** The rule is
   "after customer registration", and registration is recorded as a date. Using
   the next day makes "after" unambiguous rather than depending on the time of
   day the customer signed up.
4. **A session is placed at the customer's primary address**, which is what
   makes its geography keys agree with the customer record. IP addresses are
   drawn from public address blocks chosen per country, so an address is
   plausible for its geography. Private and reserved ranges are excluded, and
   a test asserts it.
5. **Persona and session distributions are fixed catalogues in the
   generators**, as F001 does for its commercial reference tables. Only the
   tunable session-shape settings are in `journey.yaml`.
6. **Seasonal shoppers are biased towards November and December** by resampling
   their session dates up to five times. Their profile says "highly active
   during holidays", so a uniform spread would contradict the description
   shipped in the same row.
7. **`persona_id` reuses `customer_id`.** The relationship is strictly
   one-to-one, so a separate counter would carry no information.
8. **Session start hours follow an evening-weighted distribution.** Uniform
   hours would make a traffic-by-hour chart flat and obviously synthetic.

## Test coverage

516 tests total; F003.1 contributes 129.

| Area | Tests | Notable failure paths |
| --- | --- | --- |
| Persona generator | 19 | Empty customers frame; unknown persona lookup |
| Session generator | 28 | Empty addresses or countries; no primary address; a customer missing an address |
| Orchestrator and configuration | 21 | Each missing upstream dataset; empty customers; out-of-range settings |
| Journey validation | 26 | Every documented check proved by injecting the defect |
| CLI | 15 | Missing upstream data; master data without customers; bad config dir |

Distribution tests assert the documented splits: personas 25/20/20/20/10/5,
devices 65/30/5, and a bounce rate of 25%. Timeline tests assert sessions fall
after registration, inside the five-year window, in chronological order per
customer, and that over 95% land on their own day rather than bunching onto
consecutive ones.

## Known limitations

1. **Session volume is a modelled approximation, not a guarantee.** The tenure
   multiplier targets the ~6,000 figure at the default scale; a configuration
   with a different registration window will land elsewhere. There is no
   configurable session-volume multiplier, because the specification did not
   ask for one.
2. **Personas are assigned independently of customer attributes.** A customer
   whose F002 segment is VIP can be assigned Window Shopper, and a customer
   with a Platinum loyalty tier can be an Impulse Buyer. The specification
   gives a flat persona distribution, so no correlation was introduced.
3. **All of a customer's sessions come from one location.** Travel and
   multi-device households are not modelled, so a customer's sessions always
   share a city and IP block.
4. **`pages_viewed` is a count only.** Which pages were viewed is F003.2 work
   and deliberately absent.
5. **Sessions are held in memory before writing**, sharing the Parquet
   streaming ceiling recorded in the F001 review. At the default scale the
   dataset is a few thousand rows, so this is not currently a constraint.
6. **The bounce rate is global**, not per persona. An impulse buyer bounces as
   often as a researcher, which is unlikely in reality but is what the flat
   25% figure in the specification specifies.

## Suggested improvements

- Correlate persona assignment with the F002 customer segment and loyalty
  tier, so the two features tell one story about the same customer.
- Per-persona bounce rates - an impulse buyer and a researcher should not
  bounce at the same rate.
- Session recency weighting, so activity increases towards the reference date
  rather than spreading uniformly across tenure.
- Weekday and weekend shape on top of the existing hour-of-day curve.
- Occasional travel sessions from a different city, and a stable device
  fingerprint per customer so returning visits look like returning visits.
- A configurable session-volume multiplier for scaling demos without editing
  persona profiles.
