"""Tests for the shipped platform configuration files.

These assert that ``configs/simulation.yaml`` and ``configs/logging.yaml``
parse as YAML mappings and carry only platform-level defaults. No business
configuration is expected in either file at this stage.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

import eds

CONFIG_DIR = Path(eds.__file__).parent.parent / "configs"

SIMULATION_KEYS = frozenset({"seed", "timezone", "locale", "output_directory"})
LOGGING_KEYS = frozenset({"log_level", "log_format", "date_format", "log_to_console", "log_file"})

VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def load(name: str) -> dict[str, Any]:
    """Parse a configuration file from ``configs/`` into a mapping.

    Args:
        name: File name within the ``configs/`` directory.

    Returns:
        The parsed YAML document.

    Raises:
        AssertionError: If the document is not a mapping.
    """
    document = yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{name} must parse to a mapping"
    return document


@pytest.fixture
def simulation_config() -> dict[str, Any]:
    """Return the parsed simulation configuration."""
    return load("simulation.yaml")


@pytest.fixture
def logging_config() -> dict[str, Any]:
    """Return the parsed logging configuration."""
    return load("logging.yaml")


@pytest.mark.parametrize("name", ["simulation.yaml", "logging.yaml"])
def test_config_file_exists(name: str) -> None:
    """Both platform configuration files are present."""
    assert (CONFIG_DIR / name).is_file()


@pytest.mark.parametrize("name", ["simulation.yaml", "logging.yaml"])
def test_config_file_parses_as_a_yaml_mapping(name: str) -> None:
    """Both files are valid YAML documents containing a mapping."""
    assert load(name)


def test_simulation_config_holds_exactly_the_platform_keys(
    simulation_config: dict[str, Any],
) -> None:
    """The simulation config carries the platform keys and nothing else."""
    assert set(simulation_config) == SIMULATION_KEYS


def test_simulation_defaults_are_correctly_typed(
    simulation_config: dict[str, Any],
) -> None:
    """Each simulation default has the expected type and value."""
    assert simulation_config["seed"] == 42
    assert isinstance(simulation_config["seed"], int)
    assert simulation_config["timezone"] == "UTC"
    assert simulation_config["locale"] == "en_US"
    assert simulation_config["output_directory"] == "output"


def test_logging_config_holds_exactly_the_platform_keys(
    logging_config: dict[str, Any],
) -> None:
    """The logging config carries the platform keys and nothing else."""
    assert set(logging_config) == LOGGING_KEYS


def test_log_level_is_a_recognised_level(logging_config: dict[str, Any]) -> None:
    """The default log level is one the standard library accepts."""
    level = logging_config["log_level"]

    assert level in VALID_LOG_LEVELS
    assert isinstance(logging.getLevelName(level), int)


def test_logging_defaults_are_correctly_typed(logging_config: dict[str, Any]) -> None:
    """Each logging default has the expected type."""
    assert isinstance(logging_config["log_format"], str)
    assert isinstance(logging_config["date_format"], str)
    assert logging_config["log_to_console"] is True
    assert logging_config["log_file"] is None


@pytest.mark.parametrize("name", ["simulation.yaml", "logging.yaml"])
def test_configs_contain_no_business_configuration(name: str) -> None:
    """Neither file leaks business configuration into platform defaults."""
    business_keys = {"customers", "products", "orders", "events", "workflows"}

    assert not business_keys & set(load(name))


def test_loading_a_missing_config_raises() -> None:
    """A missing configuration file fails loudly rather than returning None."""
    with pytest.raises(FileNotFoundError):
        load("does_not_exist.yaml")


def test_invalid_yaml_raises(tmp_path: Path) -> None:
    """Malformed YAML raises a parser error instead of being silently accepted."""
    broken = tmp_path / "broken.yaml"
    broken.write_text("seed: 42\n  bad: indentation\n", encoding="utf-8")

    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(broken.read_text(encoding="utf-8"))
