"""Command-line entry point for the Enterprise Data Simulator.

Defines the root Typer application exposed as the ``eds`` console script and
mounts the command groups each feature contributes.
"""

from __future__ import annotations

import typer

from eds.cli.generate import generate_app
from eds.cli.healthcare import healthcare_app
from eds.cli.stream import stream_app
from eds.infrastructure.kafka.run_consumers import consumers_app
from eds.version import __version__

__all__ = ["app", "main", "version"]

app = typer.Typer(
    name="eds",
    help="Enterprise Data Simulator - simulate business events to generate enterprise data.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(generate_app)
app.add_typer(healthcare_app)
app.add_typer(stream_app)
app.add_typer(consumers_app)


@app.callback()
def main() -> None:
    """Enterprise Data Simulator (EDS)."""


@app.command()
def version() -> None:
    """Print the installed EDS version."""
    typer.echo(__version__)
