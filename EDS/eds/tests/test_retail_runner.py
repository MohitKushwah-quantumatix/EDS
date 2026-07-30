"""End-to-end tests for the Retail runtime integration (P006.1).

These are the first tests in the repository that run a *complete* simulation
through the platform: a project, a plan, a clock, a run, a scheduler, a
domain-specific executor, real generators, real validators and a real adapter.
Nothing is faked below the scheduler.

The test that matters most is
:func:`test_the_platform_path_produces_the_same_bytes_as_the_cli`. It runs all
four stages twice - once through ``eds generate`` and once through the platform
- and compares every one of the thirty-nine Parquet files byte for byte. Two
execution paths that are *proven* to agree are a cost; two that are *assumed*
to agree are a defect.

Most other tests run at a reduced scale, because what they are checking is
orchestration rather than volume, and two hundred products prove a plan
executed just as well as fifty thousand do.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from eds.adapters.base import AdapterError, WriteResult
from eds.adapters.parquet.adapter import ParquetAdapter
from eds.cli.main import app
from eds.config import SimulationConfig, load_config
from eds.domains.retail.registry import RetailDomain
from eds.domains.retail.temporal.day import HISTORY_READ
from eds.platform.execution import plan_domain
from eds.platform.project import Project, create_project, open_project
from eds.platform.run import (
    AfterStage,
    AfterTicks,
    RunConfiguration,
    RunMode,
    SimulationRun,
    create_run,
)
from eds.platform.runtime import (
    ExecutionStatus,
    FailureType,
    RunCompleted,
    RunStarted,
    StageCompleted,
    StageStarted,
    in_sequence,
)
from eds.platform.scheduler import (
    ExecutionReport,
    StageExecutionError,
    StageExecutor,
    StageOutput,
    StageRequest,
    execute,
)
from eds.platform.time import MONTHLY, SimulationClock, create_clock
from eds.runners.retail import RETAIL_STAGES, RetailExecutor

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
RUNNER_ROOT = PACKAGE_ROOT / "runners"

#: Retail's configured reference date, so the clock sits where its data does.
DAY = date(2026, 1, 1)

RETAIL_STAGE_IDS = (
    "retail:master-data",
    "retail:customers",
    "retail:journey",
    "retail:commerce",
)


@pytest.fixture(scope="module")
def small_config() -> SimulationConfig:
    """Return Retail's settings at a scale that proves orchestration quickly."""
    config = load_config()
    return config.model_copy(
        update={
            "master_data": config.master_data.model_copy(update={"product_count": 200}),
            "customers": config.customers.model_copy(update={"customer_count": 40}),
        }
    )


@pytest.fixture
def executor(small_config: SimulationConfig) -> RetailExecutor:
    """Return a Retail executor at the reduced scale."""
    return RetailExecutor(config=small_config)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """Return a freshly created retail project."""
    return create_project(tmp_path / "shop", name="Shop", domain="retail", seed=42)


@pytest.fixture
def clock() -> SimulationClock:
    """Return a single-day clock on Retail's reference date."""
    return create_clock(DAY, end=DAY)


@pytest.fixture
def one_tick() -> RunConfiguration:
    """Return a configuration that executes exactly one tick."""
    return RunConfiguration(stop_condition=AfterTicks(1))


@pytest.fixture
def run(project: Project, clock: SimulationClock, one_tick: RunConfiguration) -> SimulationRun:
    """Return a validated single-tick full run of the retail project."""
    return create_run(project, clock, one_tick, run_id="r1")


@pytest.fixture(scope="module")
def completed(
    tmp_path_factory: pytest.TempPathFactory, small_config: SimulationConfig
) -> tuple[ExecutionReport, Project]:
    """Run one complete Retail simulation, shared by the read-only assertions."""
    root = tmp_path_factory.mktemp("shared")
    shop = create_project(root / "shop", name="Shop", domain="retail", seed=42)
    run = create_run(
        shop,
        create_clock(DAY, end=DAY),
        RunConfiguration(stop_condition=AfterTicks(1)),
        run_id="shared",
    )
    return execute(run, RetailExecutor(config=small_config)), shop


def _digests(directory: Path) -> dict[str, str]:
    """Return a SHA-256 digest per Parquet file in a directory.

    Args:
        directory: Where the datasets are.

    Returns:
        File name to digest.
    """
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*.parquet"))
    }


def _imported_modules(source: Path) -> list[str]:
    """Return every module name a source file imports.

    Args:
        source: The file to read.

    Returns:
        The imported module names, from both import forms.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    return names


# --------------------------------------------------------------------------
# A full simulation
# --------------------------------------------------------------------------


def test_a_full_retail_simulation_runs_through_the_platform(
    completed: tuple[ExecutionReport, Project],
) -> None:
    """The claim the whole platform has been making since P001."""
    report, _ = completed

    assert report.succeeded
    assert report.result.status is ExecutionStatus.COMPLETED
    assert report.result.completed_stages == RETAIL_STAGE_IDS
    assert report.result.failure is None


def test_every_declared_dataset_is_produced(
    completed: tuple[ExecutionReport, Project],
) -> None:
    """Thirty-nine datasets, exactly the ones the domain declares."""
    report, _ = completed

    assert set(report.result.rows_by_dataset) == set(RetailDomain().dataset_names)
    assert len(report.result.rows_by_dataset) == 39


def test_the_datasets_are_written_to_the_project_workspace(
    completed: tuple[ExecutionReport, Project],
) -> None:
    """The project owns where data lives; the executor writes where it is told."""
    report, shop = completed

    files = {path.stem for path in shop.workspace.data_directory.glob("*.parquet")}

    assert files == set(report.result.rows_by_dataset)


def test_the_row_counts_come_from_the_adapter(
    completed: tuple[ExecutionReport, Project],
) -> None:
    """What the result reports is what was actually written, not what was intended."""
    report, shop = completed

    for dataset, rows in report.result.rows_by_dataset.items():
        path = shop.workspace.data_directory / f"{dataset}.parquet"
        assert pl.read_parquet(path).height == rows, dataset


def test_each_stage_reports_only_what_it_produces(
    completed: tuple[ExecutionReport, Project],
) -> None:
    """The plan says what a stage produces; the result agrees with it."""
    report, _ = completed
    plan = plan_domain("retail")

    for stage in report.result.stages:
        assert set(stage.rows_by_dataset) == set(plan[stage.stage_id.split(":", 1)[1]].produces)


def test_the_commerce_chain_narrows(completed: tuple[ExecutionReport, Project]) -> None:
    """The business shape survives the platform: each link is smaller than the last."""
    rows = completed[0].result.rows_by_dataset

    assert rows["sessions"] > rows["shopping_carts"] > rows["orders"]
    assert rows["orders"] >= rows["shipments"] >= rows["returns"]
    assert rows["reviews"] > 0


# --------------------------------------------------------------------------
# The equivalence proof
# --------------------------------------------------------------------------


def test_the_platform_path_produces_the_same_bytes_as_the_cli(tmp_path: Path) -> None:
    """Two execution paths, one output. The central claim of this phase.

    Retail has two ways to run now - ``eds generate`` and the platform - and
    they duplicate the generate/validate/write sequence. This is what makes
    that duplication safe: every one of the thirty-nine files is compared byte
    for byte. Run at full configured scale, because a reduced scale would
    prove the two paths agree about a scale nobody uses.
    """
    through_cli = tmp_path / "cli"
    through_cli.mkdir()
    runner = CliRunner()
    for command in ("master-data", "customers", "journey", "commerce"):
        result = runner.invoke(app, ["generate", command, "--output", str(through_cli)])
        assert result.exit_code == 0, command

    shop = create_project(tmp_path / "shop", name="Shop", domain="retail", seed=42)
    report = execute(
        create_run(
            shop, create_clock(DAY, end=DAY), RunConfiguration(stop_condition=AfterTicks(1))
        ),
        RetailExecutor(),
    )

    assert report.succeeded
    assert _digests(shop.workspace.data_directory) == _digests(through_cli)


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_two_runs_of_one_project_produce_identical_everything(
    tmp_path: Path, small_config: SimulationConfig
) -> None:
    """Same seed, same project, same plan: identical contracts, events and bytes."""
    reports = []
    digests = []
    for name in ("a", "b"):
        shop = create_project(
            tmp_path / name, name="Shop", domain="retail", seed=42, project_id="fixed-project"
        )
        report = execute(
            create_run(
                shop,
                create_clock(DAY, end=DAY),
                RunConfiguration(stop_condition=AfterTicks(1)),
                run_id="fixed",
            ),
            RetailExecutor(config=small_config),
        )
        reports.append(report)
        digests.append(_digests(shop.workspace.data_directory))

    assert reports[0].result == reports[1].result
    assert reports[0].events == reports[1].events
    assert reports[0].result.to_document() == reports[1].result.to_document()
    assert digests[0] == digests[1]


def test_a_different_seed_produces_different_data(
    tmp_path: Path, small_config: SimulationConfig
) -> None:
    """The project's seed reaches the generators, and it is the project's that wins."""
    digests = []
    for name, seed in (("a", 42), ("b", 4242)):
        shop = create_project(tmp_path / name, name="Shop", domain="retail", seed=seed)
        execute(
            create_run(
                shop, create_clock(DAY, end=DAY), RunConfiguration(stop_condition=AfterTicks(1))
            ),
            RetailExecutor(config=small_config),
        )
        digests.append(_digests(shop.workspace.data_directory))

    assert digests[0]["customers.parquet"] != digests[1]["customers.parquet"]


def test_a_project_without_a_seed_falls_back_to_the_configuration(
    tmp_path: Path, small_config: SimulationConfig
) -> None:
    """A quick unseeded project is still runnable, and still reproducible."""
    shop = create_project(tmp_path / "shop", name="Shop", domain="retail")

    report = execute(
        create_run(
            shop, create_clock(DAY, end=DAY), RunConfiguration(stop_condition=AfterTicks(1))
        ),
        RetailExecutor(config=small_config),
    )

    assert report.succeeded


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


def test_the_event_stream_brackets_every_retail_stage(
    completed: tuple[ExecutionReport, Project],
) -> None:
    """A real run produces the same shape a fake executor did in P006."""
    report, _ = completed

    assert [event.kind for event in report.events] == (
        ["run_started"] + ["stage_started", "stage_completed"] * 4 + ["run_completed"]
    )
    assert isinstance(report.events[0], RunStarted)
    assert isinstance(report.events[-1], RunCompleted)


def test_the_events_name_the_retail_stages_in_plan_order(
    completed: tuple[ExecutionReport, Project],
) -> None:
    """Ordering is the plan's, and the plan's order is the CLI's."""
    report, _ = completed

    started = [e.stage_id for e in report.events if isinstance(e, StageStarted)]

    assert started == list(RETAIL_STAGE_IDS)
    assert in_sequence(report.events) == report.events


def test_the_completion_events_carry_real_row_counts(
    completed: tuple[ExecutionReport, Project],
) -> None:
    """An event says what happened, and something did."""
    report, _ = completed

    completions = [e for e in report.events if isinstance(e, StageCompleted)]

    assert all(event.rows > 0 for event in completions)
    assert sum(event.rows for event in completions) == report.result.total_rows


def test_every_event_carries_the_simulated_date(
    completed: tuple[ExecutionReport, Project],
) -> None:
    """Not the wall clock: the date the run was told to simulate."""
    report, _ = completed

    assert {event.simulation_date for event in report.events} == {DAY}


# --------------------------------------------------------------------------
# Persistence and restoration
# --------------------------------------------------------------------------


def test_progress_is_persisted_as_each_stage_completes(
    project: Project, clock: SimulationClock, one_tick: RunConfiguration, executor: RetailExecutor
) -> None:
    """The project records what exists, stage by stage."""
    execute(create_run(project, clock, one_tick, run_id="r1"), executor)

    state = project.read_state()

    assert state.completed_stages == RETAIL_STAGE_IDS
    assert state.current_date == DAY


def test_a_project_can_be_reopened_and_read_back(
    project: Project, clock: SimulationClock, one_tick: RunConfiguration, executor: RetailExecutor
) -> None:
    """A simulation outlives the process that ran it."""
    execute(create_run(project, clock, one_tick, run_id="r1"), executor)

    reopened = open_project(project.workspace.root)

    assert reopened.manifest == project.manifest
    assert reopened.read_state().completed_stages == RETAIL_STAGE_IDS
    assert reopened.validate() == []


def test_the_scheduler_writes_no_files_itself(
    project: Project, clock: SimulationClock, one_tick: RunConfiguration, executor: RetailExecutor
) -> None:
    """Documents go through the store, datasets through the adapter."""
    execute(create_run(project, clock, one_tick, run_id="r1"), executor)

    root = project.workspace.root

    assert sorted(path.name for path in root.glob("*.json")) == ["manifest.json", "state.json"]
    assert (root / "data").is_dir()


# --------------------------------------------------------------------------
# Resume
# --------------------------------------------------------------------------


def test_a_resume_runs_only_what_is_outstanding(
    project: Project, clock: SimulationClock, executor: RetailExecutor
) -> None:
    """The lifecycle P003 through P006 were all built for."""
    first = execute(
        create_run(project, clock, RunConfiguration(stop_condition=AfterStage("customers"))),
        executor,
    )

    assert first.result.completed_stages == RETAIL_STAGE_IDS[:2]

    resumed = RunConfiguration(mode=RunMode.RESUME, stop_condition=AfterTicks(1))
    second = execute(create_run(project, clock, resumed, run_id="r2"), executor)

    assert second.result.completed_stages == RETAIL_STAGE_IDS[2:]
    assert project.read_state().completed_stages == RETAIL_STAGE_IDS


def test_a_resumed_run_reads_what_the_first_one_wrote(
    project: Project, clock: SimulationClock, executor: RetailExecutor
) -> None:
    """Resumption is only real if the second half sees the first half's data."""
    execute(
        create_run(project, clock, RunConfiguration(stop_condition=AfterStage("customers"))),
        executor,
    )
    resumed = RunConfiguration(mode=RunMode.RESUME, stop_condition=AfterTicks(1))

    report = execute(create_run(project, clock, resumed, run_id="r2"), executor)

    assert report.succeeded
    assert report.result.rows_by_dataset["orders"] > 0
    assert len(_digests(project.workspace.data_directory)) == 39


def test_a_resume_produces_the_same_data_as_an_uninterrupted_run(
    tmp_path: Path, small_config: SimulationConfig
) -> None:
    """Interrupting a simulation must not change what it eventually produces."""
    whole = create_project(tmp_path / "whole", name="Shop", domain="retail", seed=42)
    execute(
        create_run(
            whole, create_clock(DAY, end=DAY), RunConfiguration(stop_condition=AfterTicks(1))
        ),
        RetailExecutor(config=small_config),
    )

    halted = create_project(tmp_path / "halted", name="Shop", domain="retail", seed=42)
    executor = RetailExecutor(config=small_config)
    halt = RunConfiguration(stop_condition=AfterStage("customers"))
    execute(create_run(halted, create_clock(DAY, end=DAY), halt), executor)
    execute(
        create_run(
            halted,
            create_clock(DAY, end=DAY),
            RunConfiguration(mode=RunMode.RESUME, stop_condition=AfterTicks(1)),
        ),
        executor,
    )

    assert _digests(halted.workspace.data_directory) == _digests(whole.workspace.data_directory)


# --------------------------------------------------------------------------
# Targeted execution
# --------------------------------------------------------------------------


def test_a_targeted_run_produces_only_its_closure(
    project: Project, clock: SimulationClock, executor: RetailExecutor
) -> None:
    """Narrowing is P002's; the executor runs whatever it is handed."""
    configuration = RunConfiguration(
        mode=RunMode.TARGETED, targets=("customers",), stop_condition=AfterTicks(1)
    )

    report = execute(create_run(project, clock, configuration, run_id="r1"), executor)

    assert report.result.stage_ids == RETAIL_STAGE_IDS[:2]
    assert "customers" in report.result.rows_by_dataset
    assert "orders" not in report.result.rows_by_dataset


def test_a_targeted_run_writes_only_its_own_datasets(
    project: Project, clock: SimulationClock, executor: RetailExecutor
) -> None:
    """Nothing downstream appears on disk."""
    configuration = RunConfiguration(
        mode=RunMode.TARGETED, targets=("master-data",), stop_condition=AfterTicks(1)
    )

    execute(create_run(project, clock, configuration, run_id="r1"), executor)

    written = {path.stem for path in project.workspace.data_directory.glob("*.parquet")}

    assert written == set(plan_domain("retail", targets=["master-data"]).datasets)
    assert len(written) == 14


# --------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------


def test_a_dry_run_writes_nothing_at_all(
    project: Project, clock: SimulationClock, executor: RetailExecutor
) -> None:
    """No adapter is called, so no file appears - guaranteed by the scheduler."""
    configuration = RunConfiguration(dry_run=True)

    report = execute(create_run(project, clock, configuration, run_id="r1"), executor)

    assert report.succeeded
    assert list(project.workspace.data_directory.glob("*.parquet")) == []
    assert not project.has_state()


def test_a_dry_run_still_reports_the_plan(
    project: Project, clock: SimulationClock, executor: RetailExecutor
) -> None:
    """A rehearsal answers "what would run", and it answers it fully."""
    report = execute(
        create_run(project, clock, RunConfiguration(dry_run=True), run_id="r1"), executor
    )

    assert report.result.stage_ids == RETAIL_STAGE_IDS
    assert report.result.skipped_stages == RETAIL_STAGE_IDS
    assert report.result.total_rows == 0
    assert [warning.rule for warning in report.result.warnings] == ["dry_run"]


# --------------------------------------------------------------------------
# Failure
# --------------------------------------------------------------------------


def test_a_missing_upstream_dataset_is_a_dependency_failure(
    project: Project, clock: SimulationClock, executor: RetailExecutor
) -> None:
    """Running customers with no master data on disk. Only this layer can name it."""
    configuration = RunConfiguration(stop_condition=AfterTicks(1))
    run = SimulationRun(
        run_id="r1",
        project=project,
        plan=plan_domain("retail", targets=["customers"]),
        clock=clock,
        configuration=configuration,
    )
    # Execute only the second stage, so its upstream was never written.
    partial = SimulationRun(
        run_id="r1",
        project=project,
        plan=type(run.plan)(domain="retail", stages=run.plan.stages[1:]),
        clock=clock,
        configuration=configuration,
    )

    report = execute(partial, executor)

    assert report.result.failure is not None
    assert report.result.failure.failure_type is FailureType.DEPENDENCY
    assert report.result.failed_stage == "retail:customers"


def test_a_write_failure_is_a_persistence_failure(
    project: Project,
    clock: SimulationClock,
    one_tick: RunConfiguration,
    small_config: SimulationConfig,
) -> None:
    """The adapter's error becomes the contract's failure type."""

    class Broken(ParquetAdapter):
        """Reads normally and refuses to write."""

        def write(self, datasets: Mapping[str, pl.DataFrame]) -> tuple[WriteResult, ...]:
            del datasets
            raise AdapterError("the disk is full")

    broken = RetailExecutor(config=small_config, writer=Broken(project.workspace.data_directory))

    report = execute(create_run(project, clock, one_tick, run_id="r1"), broken)

    assert report.result.failure is not None
    assert report.result.failure.failure_type is FailureType.PERSISTENCE
    assert report.result.failed_stage == "retail:master-data"


def test_an_unknown_stage_is_a_configuration_failure(
    project: Project, clock: SimulationClock, executor: RetailExecutor
) -> None:
    """A stage the domain declares but the runner has no work for."""
    plan = plan_domain("retail", targets=["master-data"])
    renamed = dataclasses.replace(plan.stages[0], stage_id="retail:growth", name="growth")
    run = SimulationRun(
        run_id="r1",
        project=project,
        plan=type(plan)(domain="retail", stages=(renamed,)),
        clock=clock,
        configuration=RunConfiguration(stop_condition=AfterTicks(1)),
    )

    report = execute(run, executor)

    assert report.result.failure is not None
    assert report.result.failure.failure_type is FailureType.CONFIGURATION
    assert "no work for stage 'growth'" in report.result.failure.message


def test_a_failed_stage_leaves_earlier_work_recorded(
    project: Project,
    clock: SimulationClock,
    one_tick: RunConfiguration,
    small_config: SimulationConfig,
) -> None:
    """A failure stops the run and does not undo what already succeeded."""

    class FailsOnJourney(RetailExecutor):
        """Refuses the journey stage."""

        def execute(self, request: StageRequest) -> StageOutput:
            if request.stage.name == "journey":
                raise StageExecutionError("no", FailureType.GENERATION)
            return super().execute(request)

    report = execute(
        create_run(project, clock, one_tick, run_id="r1"), FailsOnJourney(config=small_config)
    )

    assert report.result.failed_stage == "retail:journey"
    assert project.read_state().completed_stages == RETAIL_STAGE_IDS[:2]
    assert {path.stem for path in project.workspace.data_directory.glob("*.parquet")} == set(
        plan_domain("retail", targets=["customers"]).datasets
    )


# --------------------------------------------------------------------------
# Multiple ticks
# --------------------------------------------------------------------------


def test_a_multi_tick_run_executes_every_stage_on_every_tick(
    project: Project, executor: RetailExecutor
) -> None:
    """The scheduler's tick loop, driven by real work."""
    clock = create_clock(DAY, end=date(2026, 12, 31), tick=MONTHLY)
    configuration = RunConfiguration(stop_condition=AfterTicks(3))

    report = execute(create_run(project, clock, configuration, run_id="r1"), executor)

    assert report.succeeded
    assert report.progress.completed_ticks == 3
    assert report.result.end_date == date(2026, 3, 1)


def test_a_multi_tick_stage_gets_one_result_spanning_the_ticks(
    project: Project, executor: RetailExecutor
) -> None:
    """PADR-012 forbids two results for one stage, so they aggregate."""
    clock = create_clock(DAY, end=date(2026, 12, 31), tick=MONTHLY)
    configuration = RunConfiguration(stop_condition=AfterTicks(3))

    report = execute(create_run(project, clock, configuration, run_id="r1"), executor)

    master = report.result.stage("retail:master-data")

    assert master.start_date == DAY
    assert master.end_date == date(2026, 3, 1)
    assert len(report.result.stages) == 4


def test_the_simulated_date_reaches_the_data(
    tmp_path: Path, small_config: SimulationConfig
) -> None:
    """The date the platform supplies is the date the business is founded on.

    This is the inverse of what P006.1 asserted. Retail took its reference
    date from its own configuration then, so two runs on different simulated
    days produced identical bytes; the execution date is the reference date
    now, so they cannot.
    """
    digests = []
    for name, day in (("a", DAY), ("b", date(2026, 6, 15))):
        shop = create_project(tmp_path / name, name="Shop", domain="retail", seed=42)
        execute(
            create_run(
                shop,
                create_clock(day, end=day),
                RunConfiguration(stop_condition=AfterTicks(1)),
            ),
            RetailExecutor(config=small_config),
        )
        digests.append(_digests(shop.workspace.data_directory))

    assert digests[0] != digests[1]
    assert set(digests[0]) == set(digests[1])


# --------------------------------------------------------------------------
# The integration seam
# --------------------------------------------------------------------------


def test_the_runner_covers_exactly_the_declared_stages() -> None:
    """A stage added to the domain without work here fails loudly."""
    assert set(RETAIL_STAGES) == {stage.name for stage in RetailDomain().stages}


def test_the_executor_satisfies_the_protocol(executor: RetailExecutor) -> None:
    """The seam is a protocol; nothing was subclassed to make this work."""
    assert isinstance(executor, StageExecutor)


def test_the_executor_reads_what_the_plan_declares(
    project: Project,
    clock: SimulationClock,
    one_tick: RunConfiguration,
    small_config: SimulationConfig,
) -> None:
    """The read list is derived from P002, never restated by this layer.

    A stage also reads its own history, which no plan can express, so what is
    checked is the *first* thing each stage asks for. On a founding day none
    of the history exists, so the bulk request for it is refused and the
    executor falls back to asking dataset by dataset - which is why there are
    more requests than stages.
    """
    asked: list[tuple[str, ...]] = []

    class Watching(ParquetAdapter):
        """Records what each stage was asked to read."""

        def read(self, names: Iterable[str]) -> dict[str, pl.DataFrame]:
            wanted = tuple(names)
            asked.append(wanted)
            return super().read(wanted)

    watcher = Watching(project.workspace.data_directory)
    execute(
        create_run(project, clock, one_tick, run_id="r1"),
        RetailExecutor(config=small_config, reader=watcher),
    )

    plan = plan_domain("retail")
    history = [tuple(HISTORY_READ[stage.name]) for stage in plan.stages]
    first = [wanted for wanted in asked if wanted in {*history, *(s.requires for s in plan.stages)}]

    assert [wanted for wanted in first if wanted not in history] == [
        stage.requires for stage in plan.stages
    ]
    assert [wanted for wanted in first if wanted in history] == history


def test_the_platform_does_not_know_retail_exists() -> None:
    """The success criterion of the whole phase."""
    for source in (PACKAGE_ROOT / "platform").rglob("*.py"):
        for imported in _imported_modules(source):
            assert not imported.startswith(("eds.domains", "eds.runners")), (
                f"{source.name} imports {imported}"
            )


def test_the_retail_domain_does_not_know_the_runner_exists() -> None:
    """The dependency runs one way: the runner depends on both, neither on it."""
    for source in (PACKAGE_ROOT / "domains").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "eds.runners" not in text, f"{source.name} reaches into the runner"


def test_the_runner_depends_on_both_sides() -> None:
    """The positive half: this is the layer that knows about both."""
    imported = {name for source in RUNNER_ROOT.rglob("*.py") for name in _imported_modules(source)}

    assert any(name.startswith("eds.domains.retail") for name in imported)
    assert any(name.startswith("eds.platform.scheduler") for name in imported)
    assert any(name.startswith("eds.adapters") for name in imported)


def test_the_runner_opens_no_files_itself() -> None:
    """Persistence goes through adapters, which is what makes a second one possible."""
    banned = ("pathlib.Path.write", "open", "write_parquet", "read_parquet")
    for source in RUNNER_ROOT.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        for name in banned:
            assert f"{name}(" not in text, f"{source.name} calls {name}()"


@pytest.mark.parametrize(
    "name",
    [
        "eds.runners",
        "eds.runners.retail",
        "eds.runners.retail.executor",
        "eds.runners.retail.stages",
    ],
)
def test_runner_modules_are_importable_and_documented(name: str) -> None:
    """Every module in the package imports cleanly and states its purpose."""
    import importlib

    module = importlib.import_module(name)

    assert module.__doc__ is not None
    assert module.__doc__.strip()
