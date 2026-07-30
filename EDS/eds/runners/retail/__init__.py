"""The Retail runner: Retail, wired into the platform.

Importing this package registers the Retail domain and gives you a
:class:`~eds.runners.retail.executor.RetailExecutor`, which is everything the
scheduler needs to run a complete Retail simulation:

.. code-block:: python

    project = create_project(root, name="Shop", domain="retail", seed=42)
    clock = create_clock(date(2026, 1, 1), end=date(2026, 1, 1))
    report = execute(create_run(project, clock), RetailExecutor())

That chain touches every phase the platform built - the plan from P002, the
project from P003, the clock from P004, the run from P005, the contracts from
P005.1 and the scheduler from P006 - and none of those knows Retail exists.

Nothing in this package is imported by the platform, and nothing in it is
imported by the Retail domain. It depends on both; neither depends on it.
"""

import eds.domains.retail  # noqa: F401  - importing the runner registers the domain
from eds.runners.retail.executor import RetailExecutor
from eds.runners.retail.stages import RETAIL_STAGES, StageValidation, run_stage

__all__ = ["RETAIL_STAGES", "RetailExecutor", "StageValidation", "run_stage"]
