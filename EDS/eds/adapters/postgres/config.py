"""Configuration for exporting to PostgreSQL.

Follows the same pattern as :mod:`eds.platform.config` and every domain's own
``config.py``: a :class:`pydantic.BaseModel`, validated by
:func:`eds.core.config.build_model` from a YAML file read by
:func:`eds.core.config.read_yaml_mapping`. This module only ever imports
``eds.core`` -- the adapter layer still may not know what a "customer" or an
"order" is (PADR-003), so :attr:`PostgresConnectionConfig.tables` is a plain
list of names, not validated against any domain's dataset registry. A caller
that wants unlisted names to mean "every Retail dataset" resolves that itself
against :data:`eds.runners.retail.postgres_schema.RETAIL_DATASET_SCHEMAS`,
the same way :mod:`eds.adapters.postgres.writer` leaves dependency ordering
to a caller-supplied mapping rather than assuming one.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eds.core.config import DEFAULT_CONFIG_DIR, build_model, read_yaml_mapping

__all__ = ["POSTGRES_CONFIG_FILE", "PostgresConnectionConfig", "load_postgres_config"]

POSTGRES_CONFIG_FILE: Final[str] = "postgres.yaml"


class PostgresConnectionConfig(BaseModel):
    """Connection details and export behaviour for a PostgreSQL target.

    Attributes:
        host: Server hostname or IP address.
        port: Server port.
        database: Database name. Must already exist.
        user: Login role.
        password: Login password, in plain text. Prefer ``password_env``
            for anything other than local/throwaway databases -- a
            committed config file is not a safe place for a real password.
        password_env: Name of an environment variable to read the password
            from. Takes precedence over ``password`` when set and present in
            the environment.
        schema_name: PostgreSQL schema tables are read from and written to.
            Must already exist; the adapter does not create schemas.
        enforce_constraints: If ``true``, tables are created with their
            declared primary key, foreign keys, and uniqueness constraints
            (PADR-018). If ``false``, tables are created from Polars'
            inferred schema with no constraints.
        tables: Dataset names to include. Empty means "every dataset the
            caller has to offer" -- this model does not know what the full
            set is (see module docstring).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    host: str = "localhost"
    port: int = 5432
    database: str = "eds_db"
    user: str = "postgres"
    password: str = ""
    password_env: str | None = None
    schema_name: str = Field(default="public", alias="schema")
    enforce_constraints: bool = True
    tables: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _password_env_must_exist_if_set(self) -> PostgresConnectionConfig:
        if self.password_env and self.password_env not in os.environ and not self.password:
            raise ValueError(
                f"password_env {self.password_env!r} is not set in the environment, "
                "and no fallback `password` was given"
            )
        return self

    @property
    def resolved_password(self) -> str:
        """The password to actually connect with.

        Returns:
            The value of the ``password_env`` environment variable if set
            and present, otherwise the literal ``password`` field.
        """
        if self.password_env:
            return os.environ.get(self.password_env, self.password)
        return self.password

    @property
    def dsn(self) -> str:
        """A SQLAlchemy connection URL built from this configuration.

        Returns:
            A ``postgresql+psycopg://`` URL suitable for
            :class:`~eds.adapters.postgres.adapter.PostgresAdapter`.
        """
        from urllib.parse import quote_plus

        user = quote_plus(self.user)
        password = quote_plus(self.resolved_password)
        return f"postgresql+psycopg://{user}:{password}@{self.host}:{self.port}/{self.database}"


def load_postgres_config(config_dir: Path | None = None) -> PostgresConnectionConfig:
    """Load PostgreSQL export settings from ``postgres.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to
            the repository ``configs/`` directory.

    Returns:
        The validated configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (config_dir or DEFAULT_CONFIG_DIR) / POSTGRES_CONFIG_FILE
    return build_model(PostgresConnectionConfig, read_yaml_mapping(path), path)
