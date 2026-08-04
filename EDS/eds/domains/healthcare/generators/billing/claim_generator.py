"""Generate insurance claim records."""

from __future__ import annotations

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_claims"]


def generate_claims(
    config, billing: pl.DataFrame, upstream: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "claims")
    insurance_plan_ids = upstream["insurance_plans"]["insurance_plan_id"].to_list()
    claim_statuses = ["SUBMITTED", "APPROVED", "DENIED", "PAID"]

    rows = []
    claim_id = 1
    for bill_row in billing.iter_rows():
        if rng.random() < config.claim_rate:
            claim_amount = bill_row[9]
            approved_amount = claim_amount if rng.random() < 0.8 else 0.0
            denied_amount = claim_amount - approved_amount

            billing_date = bill_row[11]
            processed_year = config.reference_date.year
            try:
                processed_year = int(str(billing_date)[:4])
            except (ValueError, TypeError):
                pass
            processed_date = f"{processed_year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"

            rows.append({
                "claim_id": claim_id,
                "claim_number": f"CLM-{claim_id:06d}",
                "billing_id": bill_row[0],
                "insurance_plan_id": rng.choice(insurance_plan_ids),
                "patient_id": bill_row[2],
                "claim_amount": claim_amount,
                "approved_amount": approved_amount,
                "denied_amount": denied_amount,
                "status": rng.choice(claim_statuses),
                "submitted_date": billing_date,
                "processed_date": processed_date,
                "created_at": config.reference_date.isoformat(),
            })
            claim_id += 1

    return pl.DataFrame(rows)
