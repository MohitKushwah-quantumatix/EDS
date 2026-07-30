"""Teaching the scheduler how to run Retail.

A :class:`RetailExecutor` satisfies
:class:`~eds.platform.scheduler.executor.StageExecutor` and does five things
per stage: read what the plan says the stage requires, read what the stage has
produced before, run the stage for the request's simulated date, write what
changed, and report the row counts. Everything else - ordering, ticks, state,
events, results - already belongs to somebody else.

**The read list comes from the plan.** ``PlannedStage.requires`` is derived
from the same ``REQUIRED_*`` constants the CLI computes its read list from, so
this executor never restates which datasets a stage consumes.

**The history list comes from the domain.** What a stage must be shown of the
past is not something a plan can say - a stage's own output is exactly what a
plan subtracts, and would be a cycle if it did not - so Retail declares it, in
:data:`~eds.domains.retail.temporal.day.HISTORY_READ`, and this executor reads
it. A dataset that does not exist yet is not an error: it is a stage that has
not run before, which is what a founding day is.

**Adapters are used through their protocols.** The executor holds a
:class:`~eds.adapters.base.DatasetReader` and a
:class:`~eds.adapters.base.DatasetWriter`, defaulting to a
:class:`~eds.adapters.parquet.adapter.ParquetAdapter` pointed at the project's
data directory. Nothing here opens a file.

**Simulated time is received and used.** The request's date becomes the
business date, and the business date is what Retail generates against. The
executor never decides what a day does to a business, and never advances one.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from eds.adapters.base import AdapterError, DatasetReader, DatasetWriter
from eds.adapters.parquet.adapter import ParquetAdapter
from eds.core.config import ConfigError
from eds.core.random_streams import resolve_seed
from eds.domains.retail.config import SimulationConfig, load_config
from eds.domains.retail.temporal.context import BusinessContext
from eds.domains.retail.temporal.day import HISTORY_READ
from eds.platform.runtime.failure import FailureType
from eds.platform.scheduler.executor import StageExecutionError, StageOutput, StageRequest
from eds.runners.retail.stages import run_stage

__all__ = ["RetailExecutor"]


class RetailExecutor:
    """Runs Retail's stages for the platform scheduler.

    Satisfies :class:`~eds.platform.scheduler.executor.StageExecutor`.

    Deterministic, as the protocol requires: the same request against the same
    configuration and the same history produces the same rows. The seed comes
    from the project via the request, so two projects with one seed generate
    identically and a project without a seed falls back to the configuration's.
    """

    def __init__(
        self,
        config: SimulationConfig | None = None,
        config_dir: Path | None = None,
        reader: DatasetReader | None = None,
        writer: DatasetWriter | None = None,
    ) -> None:
        """Build an executor.

        Args:
            config: Retail settings. Loaded from ``config_dir`` when omitted.
            config_dir: Where to load settings from. The repository's
                ``configs/`` when omitted.
            reader: Where datasets are read from. A Parquet adapter on the
                project's data directory when omitted.
            writer: Where produced datasets are written. A Parquet adapter on
                the project's data directory when omitted.

        Raises:
            ConfigError: If the configuration cannot be loaded.
        """
        self._config = config if config is not None else load_config(config_dir)
        self._reader = reader
        self._writer = writer

    @property
    def config(self) -> SimulationConfig:
        """Return the Retail settings this executor generates with."""
        return self._config

    def execute(self, request: StageRequest) -> StageOutput:
        """Run one Retail stage for one simulated date.

        Args:
            request: Which stage, when, for whom, and where.

        Returns:
            How many rows each dataset the stage changed now holds.

        Raises:
            StageExecutionError: If the stage is not one Retail declares, if
                its upstream datasets cannot be read, if generation or
                validation fails, or if the result cannot be written. Each case
                carries the failure type that names it.
        """
        stage = request.stage.name
        config = self._configured(request)
        reader = (
            self._reader if self._reader is not None else ParquetAdapter(request.data_directory)
        )
        writer = (
            self._writer if self._writer is not None else ParquetAdapter(request.data_directory)
        )

        try:
            upstream = reader.read(request.stage.requires)
        except AdapterError as exc:
            raise StageExecutionError(
                f"{stage} could not read what it requires: {exc}",
                FailureType.DEPENDENCY,
                cause=repr(exc),
            ) from exc

        context = BusinessContext(
            business_date=request.simulation_date,
            seed=resolve_seed(config.platform.seed),
        )
        day = run_stage(stage, config, context, upstream, self._history(reader, stage))

        try:
            written = writer.write(day.persisted)
        except AdapterError as exc:
            raise StageExecutionError(
                f"{stage} could not be written: {exc}",
                FailureType.PERSISTENCE,
                cause=repr(exc),
            ) from exc

        return StageOutput(rows_by_dataset={result.dataset: result.rows for result in written})

    @staticmethod
    def _history(reader: DatasetReader, stage: str) -> dict[str, pl.DataFrame]:
        """Read what a stage has produced before.

        "Not there yet" is the normal state of a history and is not a failure:
        a stage with no history is a stage founding one. So the whole list is
        asked for at once - which is what every adapter is efficient at - and
        only if that is refused are the datasets asked for one at a time, to
        find out which of them exist. A stage Retail does not run has no
        history to read, and is refused later by name.

        Args:
            reader: Where datasets are read from.
            stage: Which stage.

        Returns:
            Every dataset of the stage's history that exists.
        """
        names = HISTORY_READ.get(stage, ())
        try:
            return reader.read(names)
        except AdapterError:
            pass
        history: dict[str, pl.DataFrame] = {}
        for name in names:
            try:
                history.update(reader.read([name]))
            except AdapterError:
                continue
        return history

    def _configured(self, request: StageRequest) -> SimulationConfig:
        """Return the settings this request should generate with.

        The project's seed wins over the configuration file's, because the
        project is what makes a simulation reproducible (PADR-009). A project
        created without one falls back to the file, which keeps a runner
        usable for a quick unseeded run.

        Args:
            request: The stage request.

        Returns:
            The settings, with the seed and output directory bound to this run.

        Raises:
            StageExecutionError: If the resulting settings are not valid.
        """
        seed = request.seed if request.seed is not None else self._config.platform.seed
        try:
            platform = self._config.platform.model_copy(
                update={"seed": seed, "output_directory": request.data_directory}
            )
            return self._config.model_copy(update={"platform": platform})
        except (ConfigError, ValueError) as exc:  # pragma: no cover - defensive
            raise StageExecutionError(
                f"the run's settings are not valid: {exc}",
                FailureType.CONFIGURATION,
                cause=repr(exc),
            ) from exc
