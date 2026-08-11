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
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eds_loader.exceptions import ConfigError

__all__ = ["ConnectorConfig", "LoaderConfig"]


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

    @model_validator(mode="after")
    def _no_blank_table_names(self) -> "LoaderConfig":
        blanks = [t for t in self.tables if not t.strip()]
        if blanks:
            raise ValueError("'tables' list must not contain blank entries")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> "LoaderConfig":
        """Load and validate a loader config from a YAML file.

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
