# F009 - Claude Prompt

## Role

Senior Python Engineer for the Enterprise Data Simulator.

Constraints given:

- Implement F009 exactly as described.
- Do not redesign the existing architecture.
- Do not modify previous schemas.
- Do not rename datasets.
- Follow all Architecture Decision Records, ADR-001 through ADR-012.
- Completed features are immutable.
- Stop after F009.

## Task

Generate realistic customer return requests, producing `returns.parquet`,
`return_items.parquet`, and `return_status_history.parquet`. Returns originate
only from delivered shipment items.

Read the F001, F006 and F008 datasets; never regenerate them.

## Module structure

```
eds/generators/commerce/
    return_generator.py
    return_item_generator.py
    return_status_generator.py
    returns.py
eds/validation/return_validation.py
configs/returns.yaml
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

Stop after the three datasets. Do not begin F010 - Reviews.

## Point escalated to the technical lead

**`return_reasons.parquet` did not exist.** The specification listed it as an
F001 dependency and required "Read from `return_reasons.parquet` / Never
hardcode", with "Return reasons loaded from master data" as an acceptance
criterion. But F001 generated thirteen master datasets and this was not among
them - there was no reference to it anywhere in the repository.

Every way forward broke one of the standing instructions, so implementation
stopped and the choice went to the technical lead:

1. F009 owns `return_reasons.parquet` as a fourth output (contradicts the
   stop condition, which names three).
2. The reason vocabulary lives in `returns.yaml` (contradicts "loaded from
   master data").
3. Add `return_reasons` to F001 (contradicts "completed features are
   immutable" and ADR-006).

**The technical lead chose option 3.** F001 now generates fourteen master
datasets. This is an explicit, authorised exception to ADR-006, recorded here
and in the review because a future reader will otherwise see it as a
violation.

## Points resolved without escalation

1. **`ShipmentStatus` was not extended with return stages.** A return is its
   own entity with its own lifecycle, so `ReturnStatus` is separate - the same
   call F008 made about `OrderStatus`, and what ADR-011 asks for. Both enums
   carry an `IN_TRANSIT`, but they mean opposite directions of travel.
2. **A delivered shipment with no items is not eligible.** The objective says
   returns originate from delivered shipment *items*; four such shipments exist
   at the default scale, inherited from the F006 empty-order limitation.
3. **A return brings back some or all of the shipment's items, not always
   all.** Returning everything would put the item count at the very top of the
   expected 35-50 range and misrepresent the common case of one damaged item
   out of three. Quantities within an item are never split - partial-quantity
   returns are out of scope.
4. **`created_at` equals `requested_at`.** The return document comes into
   existence when the customer asks; there is no earlier moment to record.
5. **The status history owns the whole timeline**, with `approved_at`,
   `received_at` and `completed_at` read back out of it, matching F008.
