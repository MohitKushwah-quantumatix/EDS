"""What happened: the outcome of a stage, and the outcome of a run.

Results are **records of things that finished**. That is why neither will hold
``PENDING`` or ``RUNNING`` - a result carrying an in-flight status would be a
typed value that cannot be true, and every consumer would have to handle a case
that should never reach it. Both refuse one at construction.

**Time here is simulated time.** A stage's dates are the simulated dates it
covered, and a run's ticks are the clock's ticks. There is no wall-clock
duration anywhere, deliberately: a contract carrying ``datetime.now()`` would
differ between two runs of the same seed, which would destroy the property that
two results of the same simulation compare equal - the property that makes a
result worth storing at all. A scheduler is free to log elapsed seconds beside
the contract; it does not belong inside it.

The invariants are enforced rather than trusted, because a result that
contradicts itself is worse than no result: ``FAILED`` always carries a
failure and a failure always means ``FAILED``, a skipped stage produced
nothing, a run cannot claim to have completed while holding a stage that
failed, and no stage appears twice.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from eds.platform.runtime.documents import (
    require_date,
    require_int,
    require_list,
    require_mapping,
    require_str,
)
from eds.platform.runtime.errors import RuntimeContractError
from eds.platform.runtime.failure import ExecutionWarning, Failure
from eds.platform.runtime.status import ExecutionStatus
from eds.platform.time.dates import format_simulation_date

__all__ = ["RunResult", "StageResult"]


def _require_terminal(status: ExecutionStatus, what: str) -> None:
    """Reject a status that describes work still in flight.

    Args:
        status: The status to check.
        what: What is being built, for the message.

    Raises:
        RuntimeContractError: If the status is not terminal.
    """
    if not status.is_terminal:
        raise RuntimeContractError(
            f"a {what} records something that finished, so its status cannot be "
            f"{status.value!r}; use a terminal status"
        )


def _check_failure_agrees(status: ExecutionStatus, failure: Failure | None, what: str) -> None:
    """Reject a status and a failure that contradict each other.

    Args:
        status: The recorded status.
        failure: The recorded failure, if any.
        what: What is being built, for the message.

    Raises:
        RuntimeContractError: If a failed record carries no failure, or a
            record that did not fail carries one. Either way the record would
            be telling two different stories.
    """
    if status is ExecutionStatus.FAILED and failure is None:
        raise RuntimeContractError(f"a failed {what} must carry the failure that caused it")
    if status is not ExecutionStatus.FAILED and failure is not None:
        raise RuntimeContractError(
            f"a {what} with status {status.value!r} must not carry a failure"
        )


def _check_rows(rows: Mapping[str, int]) -> None:
    """Reject row counts that could not have been produced.

    Args:
        rows: Dataset name to row count.

    Raises:
        RuntimeContractError: If a key is blank or a count is negative.
    """
    for dataset, count in rows.items():
        if not dataset.strip():
            raise RuntimeContractError("a row count must name the dataset it counted")
        if isinstance(count, bool) or not isinstance(count, int):
            raise RuntimeContractError(
                f"row count for {dataset!r} must be an integer, found {count!r}"
            )
        if count < 0:
            raise RuntimeContractError(
                f"row count for {dataset!r} cannot be negative, found {count}"
            )


@dataclass(frozen=True, slots=True)
class StageResult:
    """What happened to one stage.

    Attributes:
        stage_id: The stage's stable identifier, ``"<domain>:<stage>"``. An
            opaque string here: a result must be readable without the plan
            that produced it.
        status: How it finished. Terminal only.
        start_date: The simulated date the stage began at.
        end_date: The simulated date it ended at. Equal to the start for a
            stage that covered a single day.
        rows_by_dataset: How many rows each dataset gained. Empty for a stage
            that produced nothing.
        failure: Why it failed, when it did. Present exactly when the status
            is ``FAILED``.
        warnings: What was worth reporting but did not stop it.
    """

    stage_id: str
    status: ExecutionStatus
    start_date: date
    end_date: date
    rows_by_dataset: dict[str, int] = field(default_factory=dict)
    failure: Failure | None = None
    warnings: tuple[ExecutionWarning, ...] = ()

    def __post_init__(self) -> None:
        """Reject a stage result that contradicts itself.

        Raises:
            RuntimeContractError: If the stage is unnamed, the status is not
                terminal, the dates run backwards, the failure and the status
                disagree, a row count is impossible, or a stage that never ran
                claims to have produced rows.
        """
        if not self.stage_id.strip():
            raise RuntimeContractError("a stage result must name its stage")
        _require_terminal(self.status, "stage result")
        if self.end_date < self.start_date:
            raise RuntimeContractError(
                f"stage {self.stage_id!r} ends on {self.end_date.isoformat()}, before it "
                f"starts on {self.start_date.isoformat()}"
            )
        _check_failure_agrees(self.status, self.failure, "stage result")
        _check_rows(self.rows_by_dataset)
        if self.status in (ExecutionStatus.SKIPPED, ExecutionStatus.CANCELLED) and self.total_rows:
            raise RuntimeContractError(
                f"stage {self.stage_id!r} is {self.status.value} and cannot have produced rows"
            )

    def __str__(self) -> str:
        """Render the result for a log line."""
        return f"{self.stage_id} {self.status.value} ({self.total_rows} rows)"

    @property
    def total_rows(self) -> int:
        """Return how many rows the stage produced across every dataset."""
        return sum(self.rows_by_dataset.values())

    @property
    def datasets(self) -> tuple[str, ...]:
        """Return the datasets the stage produced, in name order."""
        return tuple(sorted(self.rows_by_dataset))

    @property
    def duration_days(self) -> int:
        """Return how many simulated days the stage covered.

        Both ends included, so a stage that began and ended on the same
        simulated day covers one day rather than none. This is *simulated*
        duration; how long the work actually took is not recorded here.
        """
        return (self.end_date - self.start_date).days + 1

    @property
    def is_successful(self) -> bool:
        """Report whether the stage did what was asked, or was skipped."""
        return self.status.is_successful

    def to_document(self) -> dict[str, Any]:
        """Render the result as a storable document.

        Returns:
            A plain mapping of primitives, with datasets sorted so the same
            result always produces the same document.
        """
        return {
            "stage_id": self.stage_id,
            "status": self.status.value,
            "start_date": format_simulation_date(self.start_date),
            "end_date": format_simulation_date(self.end_date),
            "rows_by_dataset": dict(sorted(self.rows_by_dataset.items())),
            "failure": self.failure.to_document() if self.failure else None,
            "warnings": [warning.to_document() for warning in self.warnings],
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> StageResult:
        """Rebuild a stage result from a stored document.

        Args:
            document: The stored document.

        Returns:
            The result.

        Raises:
            RuntimeContractError: If a field is absent, malformed, or
                contradicts another.
        """
        rows = require_mapping(document, "rows_by_dataset")
        if not all(isinstance(key, str) for key in rows):
            raise RuntimeContractError(f"rows_by_dataset must be keyed by dataset name: {rows!r}")
        raw_failure = document.get("failure")
        if raw_failure is not None and not isinstance(raw_failure, dict):
            raise RuntimeContractError(
                f"field 'failure' must be an object or null: {raw_failure!r}"
            )
        return cls(
            stage_id=require_str(document, "stage_id"),
            status=_status_from(document),
            start_date=require_date(document, "start_date"),
            end_date=require_date(document, "end_date"),
            rows_by_dataset=dict(rows),
            failure=Failure.from_document(raw_failure) if raw_failure else None,
            warnings=tuple(
                ExecutionWarning.from_document(_as_object(entry, "warning"))
                for entry in require_list(document, "warnings")
            ),
        )


@dataclass(frozen=True, slots=True)
class RunResult:
    """What happened to one run.

    Attributes:
        run_id: The run's identifier, matching the
            :class:`~eds.platform.run.run.SimulationRun` that produced it.
            An opaque string: a result must be readable without that run.
        project_id: The project the run belonged to.
        status: How the run finished. Terminal, and never ``SKIPPED`` - a
            stage may be passed over, a run cannot be.
        start_date: The simulated date the run began at.
        end_date: The simulated date it reached.
        started_tick: The clock's elapsed tick count when the run began.
            Non-zero for a resume.
        finished_tick: The clock's elapsed tick count when it stopped.
        stages: What happened to each stage, in execution order.
        failure: Why the run failed, when it did. Present exactly when the
            status is ``FAILED``, so a consumer reading only the run learns
            the reason without walking the stages.
        warnings: Run-level warnings. Stage warnings stay on their stage; use
            :attr:`all_warnings` for both.
    """

    run_id: str
    project_id: str
    status: ExecutionStatus
    start_date: date
    end_date: date
    started_tick: int = 0
    finished_tick: int = 0
    stages: tuple[StageResult, ...] = ()
    failure: Failure | None = None
    warnings: tuple[ExecutionWarning, ...] = ()

    def __post_init__(self) -> None:
        """Reject a run result that contradicts itself.

        Raises:
            RuntimeContractError: If an identifier is missing, the status is
                not terminal or is ``SKIPPED``, the dates or ticks run
                backwards, a stage appears twice, the failure and the status
                disagree, or the run claims to have completed while holding a
                stage that failed.
        """
        for name, value in (("run_id", self.run_id), ("project_id", self.project_id)):
            if not value.strip():
                raise RuntimeContractError(f"a run result must carry a {name}")
        _require_terminal(self.status, "run result")
        if self.status is ExecutionStatus.SKIPPED:
            raise RuntimeContractError(
                "a run is never skipped; only a stage within one can be passed over"
            )
        if self.end_date < self.start_date:
            raise RuntimeContractError(
                f"run {self.run_id!r} ends on {self.end_date.isoformat()}, before it starts "
                f"on {self.start_date.isoformat()}"
            )
        if self.started_tick < 0:
            raise RuntimeContractError(
                f"started_tick cannot be negative, found {self.started_tick}"
            )
        if self.finished_tick < self.started_tick:
            raise RuntimeContractError(
                f"run {self.run_id!r} finished on tick {self.finished_tick}, before the "
                f"tick {self.started_tick} it started on"
            )
        seen: set[str] = set()
        for stage in self.stages:
            if stage.stage_id in seen:
                raise RuntimeContractError(
                    f"stage {stage.stage_id!r} has more than one result in run {self.run_id!r}"
                )
            seen.add(stage.stage_id)
        _check_failure_agrees(self.status, self.failure, "run result")
        if self.status is ExecutionStatus.COMPLETED and self.failed_stages:
            raise RuntimeContractError(
                f"run {self.run_id!r} claims to have completed but "
                f"{list(self.failed_stages)} failed"
            )

    def __str__(self) -> str:
        """Render the result for a log line."""
        return (
            f"run {self.run_id} {self.status.value}: {len(self.completed_stages)}/"
            f"{len(self.stages)} stages, {self.total_rows} rows, "
            f"{self.ticks_elapsed} tick(s)"
        )

    @property
    def stage_ids(self) -> tuple[str, ...]:
        """Return every stage identifier, in execution order."""
        return tuple(stage.stage_id for stage in self.stages)

    @property
    def completed_stages(self) -> tuple[str, ...]:
        """Return the identifiers of the stages that completed."""
        return self._ids_with(ExecutionStatus.COMPLETED)

    @property
    def failed_stages(self) -> tuple[str, ...]:
        """Return the identifiers of the stages that failed.

        Plural because a scheduler running one dependency level concurrently
        may see more than one fail before it stops. :attr:`failed_stage` is
        the common case.
        """
        return self._ids_with(ExecutionStatus.FAILED)

    @property
    def skipped_stages(self) -> tuple[str, ...]:
        """Return the identifiers of the stages that were passed over."""
        return self._ids_with(ExecutionStatus.SKIPPED)

    @property
    def cancelled_stages(self) -> tuple[str, ...]:
        """Return the identifiers of the stages that were cancelled."""
        return self._ids_with(ExecutionStatus.CANCELLED)

    @property
    def failed_stage(self) -> str | None:
        """Return the first stage that failed, if any."""
        return self.failed_stages[0] if self.failed_stages else None

    @property
    def rows_by_dataset(self) -> dict[str, int]:
        """Return how many rows every dataset gained across the whole run.

        Summed rather than replaced, because two stages may write to one
        dataset and a consumer asking how big a dataset got means the total.
        """
        totals: dict[str, int] = {}
        for stage in self.stages:
            for dataset, count in stage.rows_by_dataset.items():
                totals[dataset] = totals.get(dataset, 0) + count
        return dict(sorted(totals.items()))

    @property
    def total_rows(self) -> int:
        """Return how many rows the run produced in total."""
        return sum(stage.total_rows for stage in self.stages)

    @property
    def ticks_elapsed(self) -> int:
        """Return how many ticks the run advanced."""
        return self.finished_tick - self.started_tick

    @property
    def duration_days(self) -> int:
        """Return how many simulated days the run covered, both ends included."""
        return (self.end_date - self.start_date).days + 1

    @property
    def all_warnings(self) -> tuple[ExecutionWarning, ...]:
        """Return run-level warnings followed by every stage's, in order."""
        return self.warnings + tuple(warning for stage in self.stages for warning in stage.warnings)

    @property
    def is_successful(self) -> bool:
        """Report whether the run did what was asked.

        Warnings do not make a run unsuccessful. A status that folded them in
        would leave every consumer unable to tell "it worked" from "it worked
        and something is worth reading", which is the distinction warnings
        exist to draw.
        """
        return self.status.is_successful

    def stage(self, stage_id: str) -> StageResult:
        """Return one stage's result by identifier.

        Args:
            stage_id: The stable stage identifier.

        Returns:
            That stage's result.

        Raises:
            KeyError: If the run has no result for that stage.
        """
        for stage in self.stages:
            if stage.stage_id == stage_id:
                return stage
        raise KeyError(f"Run {self.run_id!r} has no result for stage {stage_id!r}")

    def _ids_with(self, status: ExecutionStatus) -> tuple[str, ...]:
        """Return the identifiers of the stages holding a status.

        Args:
            status: The status to select.

        Returns:
            The matching stage identifiers, in execution order.
        """
        return tuple(stage.stage_id for stage in self.stages if stage.status is status)

    def to_document(self) -> dict[str, Any]:
        """Render the result as a storable document.

        Returns:
            A plain mapping of primitives, which
            :meth:`from_document` reads back unchanged. Unlike a
            :class:`~eds.platform.run.run.SimulationRun`, a result holds no
            handles and no code, so it round-trips completely.
        """
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "status": self.status.value,
            "start_date": format_simulation_date(self.start_date),
            "end_date": format_simulation_date(self.end_date),
            "started_tick": self.started_tick,
            "finished_tick": self.finished_tick,
            "stages": [stage.to_document() for stage in self.stages],
            "failure": self.failure.to_document() if self.failure else None,
            "warnings": [warning.to_document() for warning in self.warnings],
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> RunResult:
        """Rebuild a run result from a stored document.

        Args:
            document: The stored document.

        Returns:
            The result.

        Raises:
            RuntimeContractError: If a field is absent, malformed, or
                contradicts another.
        """
        raw_failure = document.get("failure")
        if raw_failure is not None and not isinstance(raw_failure, dict):
            raise RuntimeContractError(
                f"field 'failure' must be an object or null: {raw_failure!r}"
            )
        return cls(
            run_id=require_str(document, "run_id"),
            project_id=require_str(document, "project_id"),
            status=_status_from(document),
            start_date=require_date(document, "start_date"),
            end_date=require_date(document, "end_date"),
            started_tick=require_int(document, "started_tick"),
            finished_tick=require_int(document, "finished_tick"),
            stages=tuple(
                StageResult.from_document(_as_object(entry, "stage result"))
                for entry in require_list(document, "stages")
            ),
            failure=Failure.from_document(raw_failure) if raw_failure else None,
            warnings=tuple(
                ExecutionWarning.from_document(_as_object(entry, "warning"))
                for entry in require_list(document, "warnings")
            ),
        )


def _status_from(document: dict[str, Any]) -> ExecutionStatus:
    """Read a status field from a document.

    Args:
        document: The stored document.

    Returns:
        The status.

    Raises:
        RuntimeContractError: If the status is absent or not one this platform
            knows.
    """
    raw = document.get("status")
    known = [member.value for member in ExecutionStatus]
    if not isinstance(raw, str) or raw not in known:
        raise RuntimeContractError(f"status {raw!r} is not one of {known}")
    return ExecutionStatus(raw)


def _as_object(entry: Any, what: str) -> dict[str, Any]:
    """Check that a list entry is an object before reading it.

    Args:
        entry: The entry.
        what: What it should have been, for the message.

    Returns:
        The entry.

    Raises:
        RuntimeContractError: If it is not a mapping.
    """
    if not isinstance(entry, dict):
        raise RuntimeContractError(f"each {what} must be an object, found {entry!r}")
    return entry
