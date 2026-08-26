"""Command-line entry point for running Kafka consumers.

Exposes ``eds consumers encounters``, ``billing``, ``vitals``, ``patients``
and ``all`` as subcommands of the root ``eds`` application.
"""

from __future__ import annotations

import typer

__all__ = ["consumers_app"]

consumers_app = typer.Typer(
    name="consumers",
    help="Run Kafka consumers for healthcare streaming datasets.",
    no_args_is_help=True,
    add_completion=False,
)


@consumers_app.command("encounters")
def run_encounters() -> None:
    """Consume encounter-related datasets from Kafka."""
    from eds.infrastructure.kafka.consumer import (  # noqa: PLC0415
        EncounterConsumer,
        run_consumer,
    )

    run_consumer(EncounterConsumer())


@consumers_app.command("billing")
def run_billing() -> None:
    """Consume billing-related datasets from Kafka."""
    from eds.infrastructure.kafka.consumer import (  # noqa: PLC0415
        BillingConsumer,
        run_consumer,
    )

    run_consumer(BillingConsumer())


@consumers_app.command("vitals")
def run_vitals() -> None:
    """Consume vitals-related datasets from Kafka."""
    from eds.infrastructure.kafka.consumer import (  # noqa: PLC0415
        VitalsConsumer,
        run_consumer,
    )

    run_consumer(VitalsConsumer())


@consumers_app.command("patients")
def run_patients() -> None:
    """Consume patient-related datasets from Kafka."""
    from eds.infrastructure.kafka.consumer import (  # noqa: PLC0415
        PatientConsumer,
        run_consumer,
    )

    run_consumer(PatientConsumer())


@consumers_app.command("all")
def run_all() -> None:
    """Run all healthcare consumers simultaneously."""
    from eds.infrastructure.kafka.consumer import (  # noqa: PLC0415
        BillingConsumer,
        EncounterConsumer,
        PatientConsumer,
        VitalsConsumer,
    )

    for cls in (EncounterConsumer, BillingConsumer, VitalsConsumer, PatientConsumer):
        typer.echo(f"Starting {cls.__name__}...")
        try:
            run_consumer(cls())
        except KeyboardInterrupt:
            typer.echo(f"\nStopping {cls.__name__}.")
            continue