"""Generate billing records."""

from __future__ import annotations

from datetime import datetime

import polars as pl

from eds.core.random_streams import make_rng

__all__ = ["generate_billing"]


def generate_billing(
    config, encounters: pl.DataFrame, upstream: dict[str, pl.DataFrame], seed: int
) -> pl.DataFrame:
    rng = make_rng(seed, "billing")
    billing_code_ids = upstream["billing_codes"]["billing_code_id"].to_list()
    billing_codes = upstream["billing_codes"]

    rows = []
    billing_id = 1
    for encounter_row in encounters.iter_rows():
        if rng.random() < 0.7:
            billing_code_id = rng.choice(billing_code_ids)
            charge_row = billing_codes.filter(pl.col("billing_code_id") == billing_code_id).row(0)
            charge_amount = charge_row[3] if len(charge_row) > 3 else 1000.0
            discount_amount = round(charge_amount * rng.uniform(0.0, 0.1), 2)
            tax_amount = round((charge_amount - discount_amount) * 0.05, 2)
            total_amount = round(charge_amount - discount_amount + tax_amount, 2)

            admission_date = encounter_row[8]
            billing_year = int(str(admission_date)[:4])
            billing_month = int(str(admission_date)[5:7])
            billing_day = int(str(admission_date)[8:10])
            billing_delay = rng.randint(1, 14)
            billing_date = f"{billing_year}-{billing_month:02d}-{min(billing_day + billing_delay, 28):02d}"

            rows.append({
                "billing_id": billing_id,
                "billing_number": f"BILL-{billing_id:06d}",
                "encounter_id": encounter_row[0],
                "patient_id": encounter_row[2],
                "provider_id": encounter_row[3],
                "billing_code_id": billing_code_id,
                "charge_amount": charge_amount,
                "discount_amount": discount_amount,
                "tax_amount": tax_amount,
                "total_amount": total_amount,
                "billing_date": billing_date,
                "status": rng.choice(["PENDING", "APPROVED", "PAID"]),
                "created_at": datetime.strptime(billing_date, "%Y-%m-%d"),
            })
            billing_id += 1

    df = pl.DataFrame(rows)
    if df.height > 0:
        df = df.with_columns([
            pl.col("billing_date").str.strptime(pl.Date(), "%Y-%m-%d"),
            pl.col("created_at").cast(pl.Datetime("us")),
        ])
    return df
