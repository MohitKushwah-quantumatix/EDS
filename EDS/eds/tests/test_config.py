"""Tests for configuration models and YAML loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from eds.config import (
    ConfigError,
    MasterDataConfig,
    PlatformConfig,
    load_config,
    load_master_data_config,
    load_platform_config,
)


def write_config(directory: Path, name: str, body: str) -> Path:
    """Write a YAML config file into a directory.

    Args:
        directory: Target directory.
        name: File name.
        body: File contents.

    Returns:
        The written path.
    """
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def test_shipped_configs_load() -> None:
    """The configuration files committed to the repository are valid."""
    config = load_config()

    assert config.platform.seed == 42
    assert config.master_data.product_count >= 1


def test_platform_defaults() -> None:
    """Platform defaults match the documented values."""
    platform = PlatformConfig()

    assert platform.seed == 42
    assert platform.timezone == "UTC"
    assert platform.locale == "en_US"
    assert platform.output_directory == Path("output")


def test_country_codes_are_normalised() -> None:
    """Country codes are upper-cased and de-duplicated in order."""
    config = MasterDataConfig(countries=("us", "US", "ca"))

    assert config.countries == ("US", "CA")


def test_single_country_string_is_accepted() -> None:
    """A bare string is treated as a one-country list."""
    assert MasterDataConfig(countries="gb").countries == ("GB",)  # type: ignore[arg-type]


def test_inventory_row_estimate() -> None:
    """The inventory estimate multiplies products by warehouses per product."""
    config = MasterDataConfig(product_count=1_000, warehouses_per_product=3)

    assert config.inventory_row_estimate == 3_000


def test_empty_country_list_is_rejected() -> None:
    """An empty country list would yield no geography and is refused."""
    with pytest.raises(ValueError, match="at least one country"):
        MasterDataConfig(countries=())


def test_warehouses_per_product_cannot_exceed_warehouse_count() -> None:
    """A product cannot be stocked in more warehouses than exist."""
    with pytest.raises(ValueError, match="cannot exceed"):
        MasterDataConfig(warehouse_count=2, warehouses_per_product=5)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("product_count", 0),
        ("brand_count", 0),
        ("supplier_count", -1),
        ("cities_per_state", 0),
        ("category_depth", 0),
        ("category_depth", 9),
        ("batch_size", 0),
    ],
)
def test_out_of_range_values_are_rejected(field: str, value: int) -> None:
    """Counts outside their declared bounds fail validation."""
    with pytest.raises(ValueError, match=field):
        MasterDataConfig(**{field: value})  # type: ignore[arg-type]


def test_unknown_key_is_rejected() -> None:
    """A misspelled configuration key is an error, not a silent no-op."""
    with pytest.raises(ValueError, match="prodcut_count"):
        MasterDataConfig(prodcut_count=10)  # type: ignore[call-arg]


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    """Loading from a directory without the file reports the missing path."""
    with pytest.raises(ConfigError, match="not found"):
        load_platform_config(tmp_path)


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    """Malformed YAML is reported as a configuration error."""
    write_config(tmp_path, "simulation.yaml", "seed: 42\n  bad: indent\n")

    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_platform_config(tmp_path)


def test_non_mapping_document_raises_config_error(tmp_path: Path) -> None:
    """A YAML list at the top level is not a configuration."""
    write_config(tmp_path, "simulation.yaml", "- 1\n- 2\n")

    with pytest.raises(ConfigError, match="mapping"):
        load_platform_config(tmp_path)


def test_empty_file_uses_defaults(tmp_path: Path) -> None:
    """An empty configuration file falls back to model defaults."""
    write_config(tmp_path, "master_data.yaml", "")

    assert load_master_data_config(tmp_path).product_count == 1_000


def test_invalid_value_raises_config_error(tmp_path: Path) -> None:
    """An out-of-range value names the offending file."""
    write_config(tmp_path, "master_data.yaml", "product_count: 0\n")

    with pytest.raises(ConfigError, match="master_data.yaml"):
        load_master_data_config(tmp_path)


def test_config_is_frozen() -> None:
    """Configuration objects are immutable once built."""
    config = MasterDataConfig()

    # Pydantic raises ValidationError, a ValueError subclass, on frozen models.
    with pytest.raises(ValueError, match="frozen"):
        config.product_count = 5
