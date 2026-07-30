"""Platform-level run settings.

``PlatformConfig`` holds what is true of a *run* rather than of a business:
the seed, the timezone, the locale and where output goes. Those are lifecycle
concerns, so under PADR-004 they belong to the platform.

The machinery that turns YAML into a validated model stays in
:mod:`eds.core.config`, which remains free of any policy. This module is the
policy: it says what a run's settings *are*.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict

from eds.core.config import DEFAULT_CONFIG_DIR, build_model, read_yaml_mapping

__all__ = ["PLATFORM_CONFIG_FILE", "PlatformConfig", "load_platform_config"]

PLATFORM_CONFIG_FILE: Final[str] = "simulation.yaml"


class PlatformConfig(BaseModel):
    """Platform-level defaults shared by every simulator feature.

    Attributes:
        seed: Random seed. ``None`` produces a non-deterministic run.
        timezone: IANA timezone used for every simulated timestamp.
        locale: Faker locale used by reference-data generators.
        output_directory: Root directory for generated datasets.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: int | None = 42
    timezone: str = "UTC"
    locale: str = "en_US"
    output_directory: Path = Path("output")


def load_platform_config(config_dir: Path | None = None) -> PlatformConfig:
    """Load platform defaults from ``simulation.yaml``.

    Args:
        config_dir: Directory holding the configuration files. Defaults to the
            repository ``configs/`` directory.

    Returns:
        The validated platform configuration.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    path = (config_dir or DEFAULT_CONFIG_DIR) / PLATFORM_CONFIG_FILE
    return build_model(PlatformConfig, read_yaml_mapping(path), path)
