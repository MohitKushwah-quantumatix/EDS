from datetime import date
from pathlib import Path

from eds.domains.retail.config import load_config
from eds.platform.project.project import create_project
from eds.platform.run.configuration import RunConfiguration
from eds.platform.run.run import create_run
from eds.platform.run.stop import AfterTicks, EndOfPeriod
from eds.platform.scheduler.scheduler import execute
from eds.platform.time.clock import create_clock
from eds.runners.retail import RetailExecutor

# A small enterprise, so this finishes quickly
config = load_config()
small = config.model_copy(
    update={
        "customers": config.customers.model_copy(update={"customer_count": 20}),
        "master_data": config.master_data.model_copy(
            update={
                "product_count": 30,
                "brand_count": 10,
                "supplier_count": 5,
                "warehouse_count": 5,
                "warehouses_per_product": 1,
                "root_categories": 2,
                "children_per_category": 2,
            }
        ),
        "returns": config.returns.model_copy(update={"return_rate": 0.5}),
        "engagement": config.engagement.model_copy(update={"wishlist_view_rate": 0.9}),
    }
)

# Run EVERY day from Jan 1 to Jun 1, 2026. EndOfPeriod advances the clock until
# it reaches the end date, so data is generated for the whole range and spreads
# across it (instead of stopping after a fixed tick count).
project = create_project(Path("./my-shop"), name="Demo Shop", domain="retail", seed=42)
clock = create_clock(date(2026, 1, 1), end=date(2026, 6, 1))
run = create_run(project, clock, RunConfiguration(stop_condition=EndOfPeriod()))

report = execute(run, RetailExecutor(config=small))

print("status:", report.result.status)
print("ticks: ", report.progress.completed_ticks)
for stage in report.result.stages:
    print(
        " ",
        stage.stage_id,
        stage.status,
        stage.start_date,
        "->",
        stage.end_date,
        sum(stage.rows_by_dataset.values()),
        "rows",
    )