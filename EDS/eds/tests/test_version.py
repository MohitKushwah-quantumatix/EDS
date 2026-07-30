"""Tests for the EDS version module and package exports."""

from __future__ import annotations

import re
from importlib import metadata

import pytest

import eds
from eds.version import __version__

SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")


def test_version_is_a_non_empty_string() -> None:
    """The version is exposed as a populated string."""
    assert isinstance(__version__, str)
    assert __version__.strip() == __version__
    assert __version__


def test_version_follows_semantic_versioning() -> None:
    """The version string is MAJOR.MINOR.PATCH with an optional suffix."""
    assert SEMVER_PATTERN.match(__version__) is not None


def test_package_reexports_version() -> None:
    """``eds.__version__`` is the same object as ``eds.version.__version__``."""
    assert eds.__version__ == __version__
    assert eds.__all__ == ["__version__"]


def test_installed_distribution_version_matches_module() -> None:
    """The built distribution metadata agrees with the version module."""
    try:
        installed = metadata.version("eds")
    except metadata.PackageNotFoundError:  # pragma: no cover - uninstalled checkout
        pytest.skip("eds is not installed; run `pip install -e .[dev]` first")
    assert installed == __version__


def test_version_module_has_no_unexpected_exports() -> None:
    """The version module exports only the version."""
    from eds import version

    assert version.__all__ == ["__version__"]
