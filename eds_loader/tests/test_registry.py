"""Tests for the connector registry — lookup, registration, and error messages."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from eds_loader.connectors.registry import (
    CONNECTORS,
    ConnectorSpec,
    _is_package_available,
    get_connector,
    list_connectors,
    register_connector,
)
from eds_loader.exceptions import ConnectorNotFoundError, ConnectorNotInstalledError


# ---------------------------------------------------------------------------
# Helpers — isolated registry state
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_registry():
    """Restore CONNECTORS to its original state after each test."""
    original = dict(CONNECTORS)
    yield
    CONNECTORS.clear()
    CONNECTORS.update(original)


def _make_connector_class(**kwargs):
    """Return a mock connector class that records its constructor kwargs."""
    cls = MagicMock()
    cls.return_value = MagicMock(**kwargs)
    return cls


# ---------------------------------------------------------------------------
# register_connector
# ---------------------------------------------------------------------------

def test_register_connector_adds_to_registry() -> None:
    cls = _make_connector_class()
    register_connector(
        "test_kind",
        ConnectorSpec(
            connector_class=cls,
            required_packages=[],
            install_extra="test_kind",
            can_read=True,
            can_write=True,
            description="Test connector",
        ),
    )
    assert "test_kind" in CONNECTORS


def test_register_connector_first_wins_when_implemented() -> None:
    """When a connector_class is already registered, a second call is a no-op."""
    cls1 = _make_connector_class()
    cls2 = _make_connector_class()
    spec1 = ConnectorSpec(connector_class=cls1, description="first")
    spec2 = ConnectorSpec(connector_class=cls2, description="second")
    register_connector("my_kind", spec1)
    register_connector("my_kind", spec2)  # should be ignored
    assert CONNECTORS["my_kind"].description == "first"   # first-wins


def test_register_connector_placeholder_can_be_upgraded() -> None:
    """A placeholder (connector_class=None) can be replaced by a real implementation."""
    cls = _make_connector_class()
    spec_placeholder = ConnectorSpec(connector_class=None, description="placeholder")
    spec_real = ConnectorSpec(connector_class=cls, description="real")
    register_connector("placeholder_kind", spec_placeholder)
    register_connector("placeholder_kind", spec_real)  # should replace
    assert CONNECTORS["placeholder_kind"].description == "real"


# ---------------------------------------------------------------------------
# get_connector — happy path
# ---------------------------------------------------------------------------

def test_get_connector_instantiates_class_with_config() -> None:
    cls = _make_connector_class()
    register_connector(
        "happy_kind",
        ConnectorSpec(
            connector_class=cls,
            required_packages=[],
            install_extra="happy_kind",
            can_read=True,
            can_write=False,
            description="Happy",
        ),
    )
    get_connector("happy_kind", {"host": "localhost", "port": 5432})
    cls.assert_called_once_with(host="localhost", port=5432)


# ---------------------------------------------------------------------------
# get_connector — ConnectorNotFoundError
# ---------------------------------------------------------------------------

def test_get_connector_unknown_kind_raises_not_found() -> None:
    with pytest.raises(ConnectorNotFoundError) as exc_info:
        get_connector("totally_unknown", {})
    assert "totally_unknown" in str(exc_info.value)


def test_connector_not_found_error_lists_available_kinds() -> None:
    register_connector(
        "kind_a",
        ConnectorSpec(connector_class=MagicMock(), description="a"),
    )
    with pytest.raises(ConnectorNotFoundError) as exc_info:
        get_connector("not_this_one", {})
    assert "kind_a" in str(exc_info.value)


# ---------------------------------------------------------------------------
# get_connector — ConnectorNotInstalledError
# ---------------------------------------------------------------------------

def test_get_connector_missing_package_raises_not_installed() -> None:
    register_connector(
        "needs_fake_pkg",
        ConnectorSpec(
            connector_class=MagicMock(),
            required_packages=["_eds_loader_fake_package_xyz"],
            install_extra="fake",
            can_read=True,
            can_write=True,
            description="Needs fake package",
        ),
    )
    with pytest.raises(ConnectorNotInstalledError) as exc_info:
        get_connector("needs_fake_pkg", {})
    error_msg = str(exc_info.value)
    assert "_eds_loader_fake_package_xyz" in error_msg
    assert "pip install eds-loader[fake]" in error_msg


def test_connector_not_installed_error_includes_install_command() -> None:
    exc = ConnectorNotInstalledError(
        kind="mysql",
        install_extra="mysql",
        missing_packages=["pymysql"],
    )
    assert "pip install eds-loader[mysql]" in str(exc)
    assert "pymysql" in str(exc)


# ---------------------------------------------------------------------------
# list_connectors
# ---------------------------------------------------------------------------

def test_list_connectors_returns_snapshot() -> None:
    register_connector(
        "snap_kind",
        ConnectorSpec(connector_class=MagicMock(), description="snap"),
    )
    snapshot = list_connectors()
    assert "snap_kind" in snapshot
    # Mutating the snapshot does not affect the registry.
    del snapshot["snap_kind"]
    assert "snap_kind" in CONNECTORS


# ---------------------------------------------------------------------------
# _is_package_available
# ---------------------------------------------------------------------------

def test_is_package_available_true_for_stdlib() -> None:
    assert _is_package_available("json") is True


def test_is_package_available_false_for_nonexistent() -> None:
    assert _is_package_available("_eds_loader_nonexistent_xyz") is False
