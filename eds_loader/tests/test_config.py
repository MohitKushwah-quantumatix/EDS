"""Tests for LoaderConfig — YAML loading, validation, and credential resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from eds_loader.config import ConnectorConfig, LoaderConfig
from eds_loader.exceptions import ConfigError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "loader.yaml"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# LoaderConfig.from_yaml — happy path
# ---------------------------------------------------------------------------

def test_from_yaml_loads_minimal_valid_config(tmp_path: Path) -> None:
    """A config with just source + target is valid."""
    cfg_path = _write_yaml(tmp_path, """
source:
  kind: local_fs
  path: ./output

target:
  kind: postgres
  host: localhost
""")
    config = LoaderConfig.from_yaml(cfg_path)
    assert config.source.kind == "local_fs"
    assert config.target.kind == "postgres"
    assert config.tables == []
    assert config.enforce_constraints is True


def test_from_yaml_tables_and_enforce_constraints(tmp_path: Path) -> None:
    """tables and enforce_constraints are respected."""
    cfg_path = _write_yaml(tmp_path, """
source:
  kind: s3
  bucket: my-bucket
target:
  kind: local_fs
  path: ./landing
tables:
  - orders
  - customers
enforce_constraints: false
""")
    config = LoaderConfig.from_yaml(cfg_path)
    assert config.tables == ["orders", "customers"]
    assert config.enforce_constraints is False


def test_from_yaml_connector_extra_fields_pass_through(tmp_path: Path) -> None:
    """Connector-specific fields beyond 'kind' are accessible via extra_fields()."""
    cfg_path = _write_yaml(tmp_path, """
source:
  kind: local_fs
  path: /data/output
target:
  kind: postgres
  host: db.example.com
  port: 5432
  database: eds
""")
    config = LoaderConfig.from_yaml(cfg_path)
    assert config.source.extra_fields() == {"path": "/data/output"}
    assert config.target.extra_fields()["host"] == "db.example.com"
    assert config.target.extra_fields()["port"] == 5432


# ---------------------------------------------------------------------------
# LoaderConfig.from_yaml — error cases
# ---------------------------------------------------------------------------

def test_from_yaml_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        LoaderConfig.from_yaml(tmp_path / "does_not_exist.yaml")


def test_from_yaml_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    cfg_path = _write_yaml(tmp_path, "source: [unclosed")
    with pytest.raises(ConfigError, match="not valid YAML"):
        LoaderConfig.from_yaml(cfg_path)


def test_from_yaml_non_mapping_raises_config_error(tmp_path: Path) -> None:
    cfg_path = _write_yaml(tmp_path, "- just a list item\n")
    with pytest.raises(ConfigError, match="mapping"):
        LoaderConfig.from_yaml(cfg_path)


def test_from_yaml_missing_source_raises_config_error(tmp_path: Path) -> None:
    cfg_path = _write_yaml(tmp_path, "target:\n  kind: postgres\n")
    with pytest.raises(ConfigError):
        LoaderConfig.from_yaml(cfg_path)


def test_from_yaml_unknown_top_level_key_raises_config_error(tmp_path: Path) -> None:
    """extra='forbid' on LoaderConfig catches typos in top-level keys."""
    cfg_path = _write_yaml(tmp_path, """
source:
  kind: local_fs
target:
  kind: postgres
typo_key: oops
""")
    with pytest.raises(ConfigError):
        LoaderConfig.from_yaml(cfg_path)


def test_blank_table_name_raises_config_error(tmp_path: Path) -> None:
    cfg_path = _write_yaml(tmp_path, """
source:
  kind: local_fs
target:
  kind: postgres
tables:
  - orders
  - ""
""")
    with pytest.raises(ConfigError):
        LoaderConfig.from_yaml(cfg_path)


# ---------------------------------------------------------------------------
# ConnectorConfig.resolved_credential
# ---------------------------------------------------------------------------

def test_resolved_credential_uses_env_var_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_PASSWORD", "supersecret")
    cfg = ConnectorConfig(kind="postgres", password=None, password_env="MY_PASSWORD")
    assert cfg.resolved_credential("password", "password_env") == "supersecret"


def test_resolved_credential_falls_back_to_inline_value(tmp_path: Path) -> None:
    cfg = ConnectorConfig(kind="postgres", password="inline_pw")
    assert cfg.resolved_credential("password", "password_env") == "inline_pw"


def test_resolved_credential_returns_none_when_neither_set() -> None:
    cfg = ConnectorConfig(kind="postgres")
    assert cfg.resolved_credential("password", "password_env") is None


def test_resolved_credential_raises_config_error_when_env_var_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_VAR", raising=False)
    cfg = ConnectorConfig(kind="postgres", password_env="MISSING_VAR")
    with pytest.raises(ConfigError, match="MISSING_VAR"):
        cfg.resolved_credential("password", "password_env")


def test_resolved_credential_never_exposes_secret_in_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error message must name the env var, never a credential value."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    cfg = ConnectorConfig(kind="s3", access_key_env="SECRET_KEY")
    with pytest.raises(ConfigError) as exc_info:
        cfg.resolved_credential("access_key", "access_key_env")
    # The error mentions the env var NAME, not any secret value.
    assert "SECRET_KEY" in str(exc_info.value)
