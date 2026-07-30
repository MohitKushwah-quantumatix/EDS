# F007 - Claude Prompt

## Role

Senior Python Engineer for the Enterprise Data Simulator.

Constraints given:

- Implement F007 exactly as described.
- Do not redesign existing architecture.
- Do not refactor previous features.
- Do not modify previous schemas.
- Do not rename datasets.
- Follow all Architecture Decision Records, ADR-001 through ADR-012.
- Completed features are immutable.
- Stop after F007.

## Task

Simulate payment processing for orders, producing `payments.parquet` and
`payment_status_history.parquet`. Payments originate only from orders.

Read the F002, F005 and F006 datasets; never regenerate them.

## Module structure

```
eds/generators/commerce/
    payment_generator.py
    payment_status_generator.py
eds/validation/payment_validation.py
configs/payments.yaml
```

## CLI

Extend `eds generate commerce`. Do not add new CLI commands.

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

Stop after the two datasets. Do not begin F008 - Shipments.

## Points resolved without escalation

1. **`checkout` is not in the declared dependency list, but the specification
   requires the payment method to be copied from the checkout.** `orders` has
   no `payment_method` column, so the rule is unsatisfiable without reading
   `checkout`. It is read - one column, via the order's own `checkout_id` -
   rather than the method being re-drawn, because re-drawing would break the
   stated rule and ADR-007.
2. **`payment_methods.parquet` is a declared dependency but is not usable.**
   The F001 reference table carries a carrier-level vocabulary (`VISA`, `MC`,
   `AMEX`, `DISC`, `DEBIT`, `PAYPAL`, ...) that does not intersect the F005
   checkout vocabulary (`UPI`, `CREDIT_CARD`, `DEBIT_CARD`, `NET_BANKING`,
   `WALLET`, `COD`) the provider mapping is defined over. Joining the two
   would produce no matches, so it is not read and no foreign key is declared
   against it. This mirrors the F005 decision on `shipping_methods`.
3. **`payment_status` cannot be generated before the history exists.**
   ADR-012 makes the history the source of truth, so the payment carries the
   drawn outcome and is finalised by `apply_payment_status`, matching how F006
   handles `current_status`.
4. **A `FAILED` payment has no `authorized_at`.** The lifecycle the
   specification gives places `FAILED` as an opening status rather than a
   successor of `AUTHORIZED`, so a failed payment never reached authorisation.
   Its single history row is stamped with the attempt.
5. **Two orders are not charged**, because their `total_amount` is zero -
   every item in their cart was removed before checkout, an F006 known
   limitation. There is nothing to authorise, so no payment is created and a
   validation rule asserts it in both directions.
6. **`payments.py` was added as the orchestrator.** The specified module
   structure lists the two generators but no orchestrator; every earlier
   feature has one, and it is what keeps the generation order correct.
