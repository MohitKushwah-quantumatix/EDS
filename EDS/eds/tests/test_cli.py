"""Tests for the minimal EDS Typer command-line interface."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from eds.cli.main import app
from eds.version import __version__


@pytest.fixture
def runner() -> CliRunner:
    """Return a Typer CLI runner for invoking the ``eds`` application."""
    return CliRunner()


def test_help_exits_successfully(runner: CliRunner) -> None:
    """``eds --help`` exits with code 0."""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0


def test_help_lists_the_application_name_and_commands(runner: CliRunner) -> None:
    """``eds --help`` documents the application and its registered commands."""
    result = runner.invoke(app, ["--help"])

    assert "Enterprise Data Simulator" in result.output
    assert "version" in result.output


def test_version_command_prints_the_package_version(runner: CliRunner) -> None:
    """``eds version`` prints exactly the package version."""
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_no_arguments_shows_help(runner: CliRunner) -> None:
    """Invoking ``eds`` with no arguments shows help instead of failing silently."""
    result = runner.invoke(app, [])

    assert "Usage" in result.output


def test_unknown_command_fails(runner: CliRunner) -> None:
    """An unrecognised command exits with a non-zero status."""
    result = runner.invoke(app, ["definitely-not-a-command"])

    assert result.exit_code != 0


def test_unknown_option_fails(runner: CliRunner) -> None:
    """An unrecognised option exits with a non-zero status."""
    result = runner.invoke(app, ["--definitely-not-an-option"])

    assert result.exit_code != 0
