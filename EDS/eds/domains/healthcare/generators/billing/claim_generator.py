"""Generate insurance claim records."""

from __future__ import annotations

from datetime import datetime, timedelta

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

            billing_date = bill_row[10]
            submitted_date = billing_date
            processed_date = (billing_date + timedelta(days=rng.randint(0, 3))).isoformat()
            if processed_date > "2026-06-01":
                processed_date = "2026-06-01"

            rows.append({
                "claim_id": claim_id,
                "claim_number": f"CLM-{claim_id:06d}",
                "billing_id": bill_row[0],
                "insurance_plan_id": rng.choice(insurance_plan_ids),
                "patient_id": bill_row[3],
                "claim_amount": claim_amount,
                "approved_amount": approved_amount,
                "denied_amount": denied_amount,
                "status": rng.choice(claim_statuses),
                "submitted_date": submitted_date,
                "processed_date": processed_date,
                "created_at": datetime.strptime(processed_date, "%Y-%m-%d"),
            })
            claim_id += 1

    df = pl.DataFrame(rows)
    if df.height > 0:
        df = df.with_columns([
            pl.col("submitted_date").cast(pl.Date()),
            pl.col("processed_date").str.strptime(pl.Date(), "%Y-%m-%d"),
            pl.col("created_at").cast(pl.Datetime("us")),
        ])
    return df
