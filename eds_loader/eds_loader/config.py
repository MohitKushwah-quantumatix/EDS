"""Loader configuration — Pydantic models and YAML loading.

A loader run is entirely described by a YAML file.  Example::

    source:
      kind: local_fs
      path: ./output

    target:
      kind: postgres
      host: localhost
      port: 5432
      database: eds_db
      user: postgres
      password_env: EDS_PG_PASSWORD   # reads os.environ["EDS_PG_PASSWORD"]

    tables: []           # empty = load everything from schema.json
    enforce_constraints: true

The ``source`` and ``target`` sections share the same :class:`ConnectorConfig`
model.  ``kind`` is the only required field; everything else is connector-
specific and passed through as keyword arguments.

Credentials can be supplied two ways (FR-16):

- **Inline** (``password: "secret"``) — convenient for local dev, never
  commit to version control.
- **Via env-var** (``password_env: MY_SECRET``) — the loader reads
  ``os.environ["MY_SECRET"]`` at runtime; the YAML itself is safe to commit.

Credentials are never included in raised exceptions or log lines.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal

from eds_loader.exceptions import ConfigError

__all__ = ["ConnectorConfig", "LoaderConfig", "ScheduleConfig"]


# ---------------------------------------------------------------------------
# ScheduleConfig — when to run the loader automatically
# ---------------------------------------------------------------------------

_VALID_FREQUENCIES = ("daily", "every_other_day", "weekly", "monthly")
_VALID_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class ScheduleConfig(BaseModel):
    """Schedule configuration — controls when the loader runs automatically.

    Attach this as ``schedule:`` inside ``loader.yaml``.  After editing, run::

        eds-loader schedule -c loader.yaml

    to register (or update) the scheduled task on the host OS.

    Two styles are supported:

    **Simple style** (no cron knowledge needed)::

        schedule:
          time: "02:00"            # HH:MM, 24-hour
          timezone: Asia/Kolkata
          frequency: daily

    **Advanced style** (full cron expression)::

        schedule:
          cron: "0 2 * * 1-5"      # weekdays at 02:00
          timezone: Asia/Kolkata
    """

    model_config = ConfigDict(extra="forbid")

    # ── WHEN to run ──────────────────────────────────────────────────────────
    time: str | None = Field(
        default=None,
        description="HH:MM in 24-hour format (e.g. '02:00'). Required unless 'cron' is set.",
    )
    cron: str | None = Field(
        default=None,
        description=(
            "Full 5-field cron expression (e.g. '0 2 * * *'). "
            "When set, overrides 'time' + 'frequency'. "
            "skip_weekends and skip_days are still applied at runtime."
        ),
    )
    timezone: str = Field(
        default="UTC",
        description="IANA timezone name (e.g. 'Asia/Kolkata', 'UTC', 'US/Eastern').",
    )
    frequency: Literal["daily", "every_other_day", "weekly", "monthly"] = Field(
        default="daily",
        description=(
            "How often to run. Used with 'time' (not 'cron'). "
            "daily | every_other_day | weekly | monthly."
        ),
    )
    on_day: str | None = Field(
        default=None,
        description="Day of week for frequency='weekly' (e.g. 'Monday').",
    )
    on_date: int | None = Field(
        default=None,
        ge=1,
        le=28,
        description="Day of month for frequency='monthly' (1–28).",
    )

    # ── DATE RANGE ───────────────────────────────────────────────────────────
    start_date: str | None = Field(
        default=None,
        description="YYYY-MM-DD — do not run before this date.",
    )
    end_date: str | None = Field(
        default=None,
        description="YYYY-MM-DD — stop running after this date.",
    )

    # ── SKIP RULES ───────────────────────────────────────────────────────────
    skip_weekends: bool = Field(
        default=False,
        description="Skip Saturday and Sunday automatically.",
    )
    skip_days: list[str] = Field(
        default_factory=list,
        description="Day names to skip (e.g. ['Saturday', 'Sunday']).",
    )
    skip_dates: list[str] = Field(
        default_factory=list,
        description="Specific calendar dates to skip as YYYY-MM-DD strings (e.g. holidays).",
    )

    # ── RETRY ────────────────────────────────────────────────────────────────
    retry_on_failure: bool = Field(
        default=False,
        description="Automatically retry the run if it fails.",
    )
    retry_after_minutes: int = Field(
        default=30,
        ge=1,
        description="Minutes to wait before retrying after a failure.",
    )
    max_retries: int = Field(
        default=2,
        ge=1,
        description="Maximum number of retry attempts after a failure.",
    )

    # ── Validators ───────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def _check_time_or_cron(self) -> "ScheduleConfig":
        if not self.time and not self.cron:
            raise ValueError(
                "ScheduleConfig requires either 'time' (with optional 'frequency') "
                "or 'cron' (full 5-field expression)."
            )
        if self.time and self.cron:
            raise ValueError(
                "ScheduleConfig: set either 'time' or 'cron', not both."
            )
        return self

    @model_validator(mode="after")
    def _check_weekly_needs_on_day(self) -> "ScheduleConfig":
        if self.frequency == "weekly" and not self.on_day:
            raise ValueError("frequency='weekly' requires 'on_day' (e.g. on_day: Monday).")
        return self

    @model_validator(mode="after")
    def _check_monthly_needs_on_date(self) -> "ScheduleConfig":
        if self.frequency == "monthly" and not self.on_date:
            raise ValueError("frequency='monthly' requires 'on_date' (1–28).")
        return self

    @field_validator("time")
    @classmethod
    def _validate_time(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError(f"'time' must be HH:MM (24-hour), got: {v!r}")
        try:
            h, m = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError(f"'time' must be HH:MM (24-hour), got: {v!r}")
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"'time' out of range (00:00–23:59), got: {v!r}")
        return v

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        try:
            import zoneinfo
            zoneinfo.ZoneInfo(v)
        except (ImportError, zoneinfo.ZoneInfoNotFoundError):
            raise ValueError(
                f"Unknown timezone {v!r}. Use an IANA name like 'Asia/Kolkata' or 'UTC'."
            )
        return v

    @field_validator("on_day")
    @classmethod
    def _validate_on_day(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_WEEKDAYS:
            raise ValueError(
                f"'on_day' must be a weekday name, got {v!r}. "
                f"Valid: {', '.join(_VALID_WEEKDAYS)}"
            )
        return v

    @field_validator("skip_days", mode="before")
    @classmethod
    def _validate_skip_days(cls, v: list[str]) -> list[str]:
        for day in v:
            if day not in _VALID_WEEKDAYS:
                raise ValueError(
                    f"'skip_days' entry {day!r} is not a valid weekday name. "
                    f"Valid: {', '.join(_VALID_WEEKDAYS)}"
                )
        return v

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _validate_date_string(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"Date must be YYYY-MM-DD, got: {v!r}")
        return v

    @field_validator("skip_dates", mode="before")
    @classmethod
    def _validate_skip_dates(cls, v: list[str]) -> list[str]:
        for d in v:
            try:
                date.fromisoformat(d)
            except ValueError:
                raise ValueError(f"skip_dates entry must be YYYY-MM-DD, got: {d!r}")
        return v

    @model_validator(mode="after")
    def _check_date_range(self) -> "ScheduleConfig":
        if self.start_date and self.end_date:
            if date.fromisoformat(self.start_date) > date.fromisoformat(self.end_date):
                raise ValueError(
                    f"start_date ({self.start_date}) must be before end_date ({self.end_date})."
                )
        return self


class ConnectorConfig(BaseModel):
    """Configuration for one connector endpoint (source or target).

    ``kind`` is the only field validated at this level.  All other fields
    are connector-specific (``host``, ``port``, ``bucket``, ``path``, …)
    and are captured via ``extra="allow"`` — they are passed through to the
    connector class as keyword arguments by :func:`~eds_loader.connectors.registry.get_connector`.
    """

    model_config = ConfigDict(extra="allow")

    kind: str = Field(
        ...,
        description="Connector type identifier: 'local_fs', 'postgres', 's3', etc.",
    )

    def extra_fields(self) -> dict[str, Any]:
        """Return all fields beyond ``kind`` — the connector-specific config.

        These are passed verbatim to the connector class constructor.
        """
        return {k: v for k, v in self.model_dump().items() if k != "kind"}

    def resolved_credential(self, value_field: str, env_field: str) -> str | None:
        """Return a credential, preferring the env-var form (FR-16).

        Lookup order:

        1. If *env_field* is set in config, read ``os.environ[env_field]``.
        2. Otherwise fall back to *value_field* directly.

        Credentials are never mentioned in raised exceptions — only the env-
        var *name* appears, never its value.

        Args:
            value_field: Config field holding an inline value (e.g.
                ``"password"``).
            env_field: Config field holding an environment variable *name*
                (e.g. ``"password_env"``).

        Returns:
            The resolved credential string, or ``None`` if neither field is
            set.

        Raises:
            ConfigError: If *env_field* is set but the named environment
                variable is absent.
        """
        data = self.model_dump()
        env_var_name: str | None = data.get(env_field)
        if env_var_name:
            value = os.environ.get(env_var_name)
            if value is None:
                raise ConfigError(
                    f"Environment variable {env_var_name!r} "
                    f"(referenced by config field {env_field!r}) is not set."
                )
            return value
        return data.get(value_field)


class LoaderConfig(BaseModel):
    """Top-level configuration for one loader run.

    Attributes:
        source: Where to read datasets and ``schema.json`` from.
        target: Where to write datasets.
        tables: Specific dataset names to load.  An empty list means load
            every dataset listed in ``schema.json``.
        enforce_constraints: When ``True``, pass schema metadata to the
            target so it can enforce primary key / foreign key / unique
            constraints.  When ``False``, schema metadata is not forwarded
            (useful if the target does not support constraints, or for a
            quick load without enforcement).
        load_mode: ``"full"`` (default) performs a full replace every run.
            ``"incremental"`` detects changed datasets via content hashing
            and only upserts rows for datasets that changed.  Unchanged
            datasets are skipped entirely.
        state_file: Path to the incremental state file.  When ``None``
            (default) the state file is placed next to the config file and
            named ``.<config-stem>_state.json``.
        retry_count: Number of additional attempts after the first failure
            (``0`` = no retries, default).  Only :class:`LoadError` triggers
            a retry; configuration errors are never retried.
        retry_delay: Seconds to wait between retry attempts (default: 60).
    """

    model_config = ConfigDict(extra="forbid")

    source: ConnectorConfig = Field(..., description="Source connector config.")
    target: ConnectorConfig = Field(..., description="Target connector config.")
    tables: list[str] = Field(
        default_factory=list,
        description=(
            "Datasets to load.  Empty list = load everything in schema.json."
        ),
    )
    enforce_constraints: bool = Field(
        default=True,
        description="Apply PK/FK/UNIQUE constraints on the target (where supported).",
    )
    schema_required: bool = Field(
        default=True,
        description=(
            "When False, schema.json is not read.  Datasets are auto-discovered "
            "by listing *.parquet files from the source.  Constraint enforcement "
            "is automatically disabled (no schema metadata to forward)."
        ),
    )
    load_mode: Literal["full", "incremental"] = Field(
        default="full",
        description=(
            "'full' = full replace every run (default). "
            "'incremental' = hash-based change detection + upsert for changed datasets only."
        ),
    )
    state_file: str | None = Field(
        default=None,
        description=(
            "Path to the incremental state JSON file. "
            "Defaults to '.<config-stem>_state.json' next to the config file."
        ),
    )
    retry_count: int = Field(
        default=0,
        ge=0,
        description="Extra retry attempts after a LoadError (0 = no retries).",
    )
    retry_delay: int = Field(
        default=60,
        ge=1,
        description="Seconds to wait between retry attempts.",
    )
    batch_size: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Write datasets in chunks of this many rows. "
            "None (default) = write all rows at once. "
            "Useful for very large datasets to cap peak memory usage."
        ),
    )
    parallelism: int = Field(
        default=1,
        ge=1,
        description=(
            "Number of datasets to load concurrently (default: 1 = sequential). "
            "Datasets without foreign-key dependencies may be loaded in parallel."
        ),
    )
    metrics_file: str | None = Field(
        default=None,
        description=(
            "Path to write a JSON run-metrics file after every run. "
            "Defaults to 'run_metrics.json' next to the config file when set to 'auto', "
            "or disabled when None."
        ),
    )
    run_log_file: str | None = Field(
        default=None,
        description=(
            "Path to the append-only JSONL run history file. "
            "Defaults to '.eds_loader_runs.jsonl' next to the config file when set to 'auto', "
            "or disabled when None (default)."
        ),
    )
    on_validation_error: Literal["warn", "fail", "quarantine"] = Field(
        default="warn",
        description=(
            "What to do when row-level validation rules are violated. "
            "'warn' = log and load all rows. "
            "'fail' = abort the run. "
            "'quarantine' = load valid rows, write rejected rows to rejected_dir."
        ),
    )
    rejected_dir: str = Field(
        default="rejected",
        description="Directory for quarantined (rejected) rows when on_validation_error='quarantine'.",
    )
    schema_drift: Literal["warn", "fail", "ignore"] = Field(
        default="warn",
        description=(
            "What to do when source dataset schema changes between runs. "
            "'warn' = log and continue. 'fail' = abort. 'ignore' = silent."
        ),
    )
    delete_mode: Literal["keep", "soft", "hard"] = Field(
        default="keep",
        description=(
            "Incremental mode only. What to do with rows deleted from the source. "
            "'keep' = leave them in target (default). "
            "'soft' = add _eds_deleted_at timestamp column. "
            "'hard' = DELETE rows from target whose PK no longer exists in source."
        ),
    )
    notifications: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict,
        description=(
            "Notification channels keyed by trigger: 'on_failure', 'on_success', 'always'. "
            "Each value is a list of channel configs (kind: email | slack | teams | webhook)."
        ),
    )
    schedule: ScheduleConfig | None = Field(
        default=None,
        description=(
            "Optional schedule configuration. When set, run "
            "'eds-loader schedule -c <this-file>' to register the scheduled task "
            "on the host OS (Windows Task Scheduler or Linux crontab)."
        ),
    )

    @model_validator(mode="after")
    def _no_blank_table_names(self) -> "LoaderConfig":
        blanks = [t for t in self.tables if not t.strip()]
        if blanks:
            raise ValueError("'tables' list must not contain blank entries")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> "LoaderConfig":
        """Load and validate a loader config from a YAML file.

        Supports ``${ENV_VAR}`` interpolation in any string value —
        resolved via :func:`os.path.expandvars` before YAML parsing.

        Args:
            path: Path to the YAML config file (typically ``loader.yaml``).

        Returns:
            A validated :class:`LoaderConfig` instance.

        Raises:
            ConfigError: If the file is missing, is not valid YAML, or fails
                Pydantic validation.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ConfigError(f"Config file not found: {path}") from None
        except OSError as exc:
            raise ConfigError(f"Cannot read config file {path}: {exc}") from exc

        # Expand ${VAR} and $VAR patterns before parsing YAML.
        text = os.path.expandvars(text)

        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"Config file {path} is not valid YAML: {exc}") from exc

        if not isinstance(raw, dict):
            raise ConfigError(
                f"Config file {path} must be a YAML mapping at the top level, "
                f"got: {type(raw).__name__}"
            )

        try:
            return cls.model_validate(raw)
        except Exception as exc:
            raise ConfigError(f"Config validation error in {path}: {exc}") from exc
