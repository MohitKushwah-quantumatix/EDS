from datetime import date
from pathlib import Path

from eds.domains.retail.config import load_config
from eds.platform.project.project import create_project
from eds.platform.run.configuration import RunConfiguration
from eds.platform.run.run import create_run
from eds.platform.run.stop import AfterTicks
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
                "brand_count": 3,
                "supplier_count": 2,
                "warehouse_count": 2,
                "warehouses_per_product": 1,
                "root_categories": 2,
                "children_per_category": 2,
            }
        ),
    }
)

project = create_project(Path("./my-shop"), name="Demo Shop", domain="retail", seed=42)
clock = create_clock(date(2026, 1, 1), end=date(2026, 1, 3))
run = create_run(project, clock, RunConfiguration(stop_condition=AfterTicks(3)))

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