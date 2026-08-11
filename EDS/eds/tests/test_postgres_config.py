"""Tests for PostgreSQL export configuration.

No live database is needed here -- this is pure YAML-to-model validation,
in the same spirit as ``eds.platform.config``'s own tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eds.adapters.postgres.config import PostgresConnectionConfig, load_postgres_config
from eds.core.config import ConfigError


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "postgres.yaml"
    path.write_text(content, encoding="utf-8")
    return tmp_path


def test_defaults_apply_when_the_file_is_empty(tmp_path: Path) -> None:
    """An empty YAML file yields every field's default."""
    config_dir = _write(tmp_path, "")

    config = load_postgres_config(config_dir)

    assert config.host == "localhost"
    assert config.port == 5432
    assert config.schema_name == "public"
    assert config.enforce_constraints is True
    assert config.tables == ()


def test_schema_is_read_from_its_yaml_alias(tmp_path: Path) -> None:
    """The YAML key is `schema`, not `schema_name` (a reserved-ish word made safe)."""
    config_dir = _write(tmp_path, "schema: staging\n")

    config = load_postgres_config(config_dir)

    assert config.schema_name == "staging"


def test_tables_list_is_read_in_order(tmp_path: Path) -> None:
    """Table selection preserves the order given in the file."""
    config_dir = _write(tmp_path, "tables:\n  - orders\n  - customers\n")

    config = load_postgres_config(config_dir)

    assert config.tables == ("orders", "customers")


def test_an_unknown_key_is_rejected(tmp_path: Path) -> None:
    """A typo'd setting fails loudly rather than being silently ignored."""
    config_dir = _write(tmp_path, "hots: localhost\n")

    with pytest.raises(ConfigError):
        load_postgres_config(config_dir)


def test_dsn_is_built_from_the_connection_fields() -> None:
    """The DSN matches what PostgresAdapter expects."""
    config = PostgresConnectionConfig(host="db.example.com", port=6543, database="mydb", user="alice", password="s3cret")

    assert config.dsn == "postgresql+psycopg://alice:s3cret@db.example.com:6543/mydb"


def test_special_characters_in_the_password_are_escaped() -> None:
    """A password with characters that would break a URL is still usable."""
    config = PostgresConnectionConfig(user="postgres", password="p@ss/word?")

    assert "p%40ss%2Fword%3F" in config.dsn


def test_password_env_takes_precedence_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """An environment-variable password overrides the literal one."""
    monkeypatch.setenv("EDS_TEST_PG_PASSWORD", "from-env")
    config = PostgresConnectionConfig(password="from-file", password_env="EDS_TEST_PG_PASSWORD")

    assert config.resolved_password == "from-env"
    assert "from-env" in config.dsn


def test_password_env_missing_falls_back_to_the_literal_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the named variable isn't set but a literal password is, that's used."""
    monkeypatch.delenv("EDS_TEST_PG_PASSWORD_UNSET", raising=False)
    config = PostgresConnectionConfig(password="from-file", password_env="EDS_TEST_PG_PASSWORD_UNSET")

    assert config.resolved_password == "from-file"


def test_password_env_missing_with_no_fallback_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither a set env var nor a literal password is a configuration error, not a silent empty password."""
    monkeypatch.delenv("EDS_TEST_PG_PASSWORD_UNSET", raising=False)

    with pytest.raises(ValueError, match="password_env"):
        PostgresConnectionConfig(password="", password_env="EDS_TEST_PG_PASSWORD_UNSET")
