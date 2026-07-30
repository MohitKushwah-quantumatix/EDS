"""Tests asserting the repository foundation stays structurally intact.

These guard the package layout itself: every declared package must be
importable, carry a module docstring, and ship type information.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import eds

PACKAGE_ROOT = Path(eds.__file__).parent
REPO_ROOT = PACKAGE_ROOT.parent

EXPECTED_PACKAGES: tuple[str, ...] = (
    "eds",
    "eds.domain",
    "eds.domain.catalog",
    "eds.domain.customer",
    "eds.domain.order",
    "eds.domain.payment",
    "eds.domain.inventory",
    "eds.domain.shipment",
    "eds.domain.returns",
    "eds.domain.review",
    "eds.events",
    "eds.workflows",
    "eds.state",
    "eds.generators",
    "eds.generators.customers",
    "eds.generators.products",
    "eds.generators.suppliers",
    "eds.generators.warehouses",
    "eds.generators.pricing",
    "eds.simulation",
    "eds.exporters",
    "eds.exporters.csv",
    "eds.exporters.parquet",
    "eds.exporters.sql",
    "eds.exporters.delta",
    "eds.validation",
    "eds.cli",
    "eds.tests",
)


@pytest.mark.parametrize("name", EXPECTED_PACKAGES)
def test_package_is_importable(name: str) -> None:
    """Every declared package imports without side effects."""
    assert importlib.import_module(name) is not None


@pytest.mark.parametrize("name", EXPECTED_PACKAGES)
def test_package_has_a_module_docstring(name: str) -> None:
    """Every declared package documents its purpose."""
    module = importlib.import_module(name)

    assert module.__doc__ is not None
    assert module.__doc__.strip()


def test_py_typed_marker_is_present() -> None:
    """The package ships a PEP 561 marker so downstream type checking works."""
    assert (PACKAGE_ROOT / "py.typed").is_file()


@pytest.mark.parametrize(
    "filename",
    ["pyproject.toml", "pytest.ini", "ruff.toml", "README.md", "LICENSE"],
)
def test_required_repository_file_exists(filename: str) -> None:
    """The repository foundation files are present at the repository root."""
    assert (REPO_ROOT / filename).is_file()


def test_importing_a_missing_package_raises() -> None:
    """Importing an undeclared subpackage fails loudly."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("eds.does_not_exist")
