# F006 - Claude Prompt

## Role

Senior Python Engineer for the Enterprise Data Simulator.

Constraints given:

- Implement F006 exactly as described.
- Do not redesign existing architecture.
- Do not modify previous schemas.
- Do not rename datasets.
- Follow all Architecture Decision Records, ADR-001 through ADR-012.
- Completed features are immutable.
- Stop after F006.

## Task

Generate immutable business documents representing customer orders, producing
`orders.parquet`, `order_lines.parquet`, and `order_status_history.parquet`.

Read the F001, F002, F004 and F005 datasets; never regenerate them.

## Module structure

```
eds/generators/commerce/
    order_generator.py
    order_line_generator.py
    order_status_generator.py
eds/validation/order_validation.py
configs/orders.yaml
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

Stop after the three datasets. Do not begin F007 - Payments.

## Points resolved without escalation

1. **`current_status` cannot be generated before the history exists.** ADR-012
   makes the history the source of truth, so the order is built with a
   placeholder and finalised from the history rather than the other way round.
2. **The expected order line volume is unreachable from frozen upstream
   data.** F004 produces 1.86 cart items per cart, about 1.65 after removals,
   so 311 orders yield 513 lines against an expected 600-900. Both F004 and
   F005 are frozen under ADR-006, so the shortfall is reported rather than
   engineered away by inventing lines.
3. **Ten orders have no order lines**, because every item in their cart was
   removed before checkout. Their subtotal is zero, so the reconciliation
   still holds.
4. **`orders.py` was added as the orchestrator.** The specified module
   structure lists the three generators but no orchestrator; every earlier
   feature has one, and it is what keeps the generation order correct.
