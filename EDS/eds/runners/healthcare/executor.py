"""Teach the scheduler how to run Healthcare."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import polars as pl

from eds.adapters.base import AdapterError, DatasetReader, DatasetWriter
from eds.adapters.parquet.adapter import ParquetAdapter
from eds.core.config import ConfigError
from eds.core.random_streams import resolve_seed
from eds.domains.healthcare.config import SimulationConfig, load_config
from eds.domains.healthcare.temporal.context import BusinessContext
from eds.domains.healthcare.temporal.day import HISTORY_READ
from eds.platform.runtime.failure import FailureType
from eds.platform.scheduler.executor import StageExecutionError, StageOutput, StageRequest
from eds.runners.healthcare.stages import run_stage

__all__ = ["HealthcareExecutor"]


class HealthcareExecutor:
    """Runs Healthcare stages for the platform scheduler."""

    def __init__(
        self,
        config: SimulationConfig | None = None,
        config_dir: Path | None = None,
        reader: DatasetReader | None = None,
        writer: DatasetWriter | None = None,
        stream: bool = False,
    ) -> None:
        self._config = config if config is not None else load_config(config_dir)
        self._reader = reader
        self._writer = writer
        self._stream = stream

    @property
    def config(self) -> SimulationConfig:
        """Return the Healthcare settings this executor generates with."""
        return self._config

    @property
    def stream(self) -> bool:
        """Return whether Kafka streaming was requested."""
        return self._stream

    def execute(self, request: StageRequest) -> StageOutput:
        """Run one Healthcare stage for one simulated date."""
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

        self._stream_generated(day.generated)

        try:
            written = writer.write(day.persisted)
        except AdapterError as exc:
            raise StageExecutionError(
                f"{stage} could not be written: {exc}",
                FailureType.PERSISTENCE,
                cause=repr(exc),
            ) from exc

        return StageOutput(rows_by_dataset={result.dataset: result.rows for result in written})

    def _stream_generated(self, datasets: Mapping[str, pl.DataFrame]) -> None:
        """Publish generated datasets to Kafka if streaming is enabled.

        Dataset names are prefixed with ``healthcare.`` so that topics are
        domain-scoped (e.g. ``healthcare.encounters``).

        Streaming is best-effort: if Kafka is unavailable or the
        ``kafka-python`` package is missing, a warning is logged and the
        simulation proceeds normally.

        Args:
            datasets: The ``day.generated`` mapping from the stage that
                just ran.
        """
        if not self._stream:
            return
        prefixed = {f"healthcare.{name}": data for name, data in datasets.items()}
        try:
            from eds.infrastructure.kafka.streaming import (  # noqa: PLC0415
                stream_if_enabled,
            )
        except ImportError:
            return
        stream_if_enabled(prefixed, stream=True)

    @staticmethod
    def _history(reader: DatasetReader, stage: str) -> dict[str, pl.DataFrame]:
        """Read what a stage has produced before."""
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
        """Return the settings this request should generate with."""
        seed = request.seed if request.seed is not None else self._config.platform.seed
        try:
            platform = self._config.platform.model_copy(
                update={"seed": seed, "output_directory": request.data_directory}
            )
            return self._config.model_copy(update={"platform": platform})
        except (ConfigError, ValueError) as exc:
            raise StageExecutionError(
                f"the run settings are not valid: {exc}",
                FailureType.CONFIGURATION,
                cause=repr(exc),
            ) from exc