# F005 - Claude Prompt

## Role

Senior Python Engineer working on the Enterprise Data Simulator.

Constraints given:

- Implement F005 exactly as described.
- Do not redesign the existing architecture.
- Do not refactor previous features.
- Do not modify schemas from previous features.
- Do not implement future features.
- Follow the conventions established in F000 through F004.
- Stop after F005 is complete.

## Task

Convert shopping carts into checkout attempts, producing `checkout.parquet`.

Read the F001, F002, F003.1 and F004 datasets; never regenerate them.

## Module structure

```
eds/generators/commerce/checkout_generator.py
eds/validation/checkout_validation.py
configs/checkout.yaml
```

## CLI

Extend `eds generate commerce`. Do not introduce additional CLI commands.

## Required report

1. Files created.
2. Files modified.
3. Commands executed.
4. Test results.
5. Design decisions.
6. Assumptions.
7. Known limitations.
8. Suggested improvements.

## Stop condition

Stop after implementing `checkout.parquet`. Do not implement orders,
payments, shipments, returns, or reviews. Do not begin F006.

## Points resolved without escalation

1. **`COMMERCE_DATASETS` was left alone.** Adding the checkout to F004's
   registry would have changed a previous feature's declared output, so the
   checkout is declared in its own `CHECKOUT_DATASETS` tuple - the same
   pattern F003.2 and F003.3 used against the journey registry.
2. **A CHECKED_OUT cart can produce a FAILED or ABANDONED checkout.** The two
   statuses answer different questions: F004's records the customer's intent
   to pay, F005's records how that attempt ended.
3. **The shipping and payment vocabularies are F005's own**, not the F001
   `shipping_methods` and `payment_methods` reference tables, which carry
   different values. The specification lists the exact strings to use and
   declares no foreign key to either table.
4. **The subtotal sums every cart item**, including one the customer later
   removed, because the specification's formula does not exclude removals.
5. **`configs/checkout.yaml` sits at the repository root**, as with F004.
