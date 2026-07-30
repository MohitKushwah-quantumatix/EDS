# F008 - Claude Prompt

## Role

Senior Python Engineer for the Enterprise Data Simulator.

Constraints given:

- Implement F008 exactly as described.
- Do not redesign existing architecture.
- Do not modify previous schemas.
- Do not rename datasets.
- Follow all Architecture Decision Records, ADR-001 through ADR-012.
- Completed features are immutable.
- Stop after F008.

## Task

Generate shipment business documents, producing `shipments.parquet`,
`shipment_items.parquet`, and `shipment_status_history.parquet`. Shipments
originate only from successfully captured payments.

Read the F001, F005, F006 and F007 datasets; never regenerate them.

## Module structure

```
eds/generators/commerce/
    shipment_generator.py
    shipment_item_generator.py
    shipment_status_generator.py
    shipments.py
eds/validation/shipment_validation.py
configs/shipments.yaml
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

Stop after the three datasets. Do not begin F009 - Returns.

## Points resolved without escalation

1. **`PACKED`, `SHIPPED` and `DELIVERED` were not added to `OrderStatus`.**
   F006's enum documents them as belonging to a later feature, but F006 is
   frozen under ADR-006 and its lifecycle is a separate concern. A new
   `ShipmentStatus` enum carries the fulfilment stages instead, which is also
   what ADR-011 asks for: one lifecycle per business entity.
2. **`shipping_method` comes from the checkout.** The shipments schema carries
   it and the carrier depends on it, but neither `orders` nor `payments` has
   the column. `checkout` is a declared F008 dependency, so it is read - one
   column, via the order's own `checkout_id`.
3. **The tracking number is derived, not drawn.** "Unique" and "deterministic"
   together rule out sampling: a random ten-digit body would only be *probably*
   unique. A modular multiplication by a constant coprime to the modulus is a
   bijection on the shipment identifier, so uniqueness is structural.
4. **`estimated_delivery_at` is measured from `created_at`, not `shipped_at`.**
   The promise is made to the customer when the shipment is created, before it
   is known when the parcel will actually leave. The separate rule that
   `delivered_at` follows `shipped_at` is unaffected.
5. **The configuration layer was not given a domain import.** `shipments.yaml`
   is keyed by shipping method, but `eds/config.py` imports nothing from
   `eds.domain` today. Rather than change that layering, the config validates
   the tables structurally and the generator checks method coverage against the
   methods actually present in the data - which catches the failure that
   matters rather than a theoretical one.
6. **Six shipments carry no items**, because every item in their cart was
   removed before checkout, an F006 known limitation. The order still has a
   positive total from shipping and tax, so it was paid for, and
   "exactly one shipment per captured payment" is stated unconditionally.
7. **`shipments.py` was included as the orchestrator**, which this
   specification lists explicitly - unlike F006 and F007, where it had to be
   added.
