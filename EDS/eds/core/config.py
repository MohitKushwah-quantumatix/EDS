"""Domain-independent configuration loading.

Pure mechanism: turn a YAML file into a validated Pydantic model, and report
failures as :class:`ConfigError`. This module holds no settings of its own and
expresses no policy, which is what lets every domain and the platform itself
share it.

The platform's own run settings live in :mod:`eds.platform.config`; Retail's
live in :mod:`eds.domains.retail.config`. A future Healthcare or Banking domain
declares its models and loads them with the same helpers, without this module
changing (PADR-002).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel

__all__ = [
    "DEFAULT_CONFIG_DIR",
    "ConfigError",
    "build_model",
    "read_yaml_mapping",
]

#: The installed ``eds`` package directory.
_PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

#: The repository's ``configs/`` directory, resolved from the package location
#: rather than the caller's working directory. Anchored on the package root so
#: that moving this module between subpackages cannot silently change it.
DEFAULT_CONFIG_DIR: Final[Path] = _PACKAGE_ROOT.parent / "configs"


class ConfigError(ValueError):
    """Raised when a configuration file is missing, malformed, or invalid."""


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file and return its top-level mapping.

    Args:
        path: File to read.

    Returns:
        The parsed mapping. An empty file yields an empty mapping.

    Raises:
        ConfigError: If the file is missing, unreadable, not valid YAML, or
            does not contain a mapping at the top level.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except OSError as exc:  # pragma: no cover - platform dependent
        raise ConfigError(f"Could not read configuration file {path}: {exc}") from exc

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return document


def build_model[ModelT: BaseModel](model: type[ModelT], data: dict[str, Any], path: Path) -> ModelT:
    """Validate a mapping into a Pydantic model, re-raising as ``ConfigError``.

    Args:
        model: Model class to construct.
        data: Parsed configuration mapping.
        path: Source file, used in the error message.

    Returns:
        The validated model instance.

    Raises:
        ConfigError: If validation fails.
    """
    try:
        return model.model_validate(data)
    except ValueError as exc:
        raise ConfigError(f"Invalid configuration in {path}: {exc}") from exc
