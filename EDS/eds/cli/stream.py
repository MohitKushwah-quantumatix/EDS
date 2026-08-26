"""The ``eds stream`` command for streaming existing Parquet data to Kafka.

This lets you replay data from a final project folder (e.g. ``my-hospital/data``
or ``my-shop/data``) into Kafka topics after a simulation has completed,
rather than streaming during generation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from eds.adapters.parquet.reader import read_dataset

__all__ = ["stream_app"]

stream_app = typer.Typer(
    name="stream",
    help="Stream existing Parquet datasets to Kafka.",
    no_args_is_help=True,
    add_completion=False,
)


@stream_app.command("folder")
def stream_folder(
    data_dir: Annotated[
        Path,
        typer.Argument(help="Directory containing {dataset}.parquet files."),
    ],
    prefix: Annotated[
        str,
        typer.Option("--prefix", help="Domain prefix for topics (e.g. healthcare)."),
    ] = "healthcare",
    pattern: Annotated[
        str,
        typer.Option("--pattern", help="Glob pattern for parquet files."),
    ] = "*.parquet",
) -> None:
    """Read every Parquet file in DATA_DIR and stream rows to Kafka topics.

    Each ``{name}.parquet`` file becomes a topic named ``{prefix}.{name}``.

    Example:
        eds stream my-hospital/data --prefix healthcare
    """
    if not data_dir.is_dir():
        typer.echo(f"Directory not found: {data_dir}", err=True)
        raise typer.Exit(code=1)

    parquet_files = sorted(data_dir.glob(pattern))
    if not parquet_files:
        typer.echo(f"No .parquet files found in {data_dir}", err=True)
        raise typer.Exit(code=1)

    from eds.infrastructure.kafka.streaming import stream_if_enabled  # noqa: PLC0415

    datasets: dict[str, pl.DataFrame] = {}
    for pf in parquet_files:
        name = pf.stem  # e.g. "patients" from "patients.parquet"
        topic = f"{prefix}.{name}"
        try:
            datasets[topic] = read_dataset(name, data_dir)
        except Exception as exc:
            typer.echo(f"Skipping {name}: {exc}", err=True)
            continue

    if not datasets:
        typer.echo("No datasets to stream.", err=True)
        raise typer.Exit(code=1)

    total_rows = sum(df.height for df in datasets.values())
    typer.echo(f"Streaming {len(datasets)} datasets ({total_rows:,} rows) from {data_dir}")
    typer.echo(f"  to topics: {sorted(datasets.keys())}")

    stream_if_enabled(datasets, stream=True)

    typer.echo(f"Done! Streamed {len(datasets)} datasets.")


@stream_app.command("list")
def list_datasets(
    data_dir: Annotated[
        Path,
        typer.Argument(help="Directory containing parquet files."),
    ],
    pattern: Annotated[
        str,
        typer.Option("--pattern", help="Glob pattern."),
    ] = "*.parquet",
) -> None:
    """List all Parquet datasets found in DATA_DIR without streaming."""
    if not data_dir.is_dir():
        typer.echo(f"Directory not found: {data_dir}", err=True)
        raise typer.Exit(code=1)

    parquet_files = sorted(data_dir.glob(pattern))
    if not parquet_files:
        typer.echo(f"No .parquet files found in {data_dir}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Datasets in {data_dir}:")
    for pf in parquet_files:
        df = pl.read_parquet(pf)
        typer.echo(f"  {pf.stem:.<40} {df.height:>8,} rows")
    typer.echo(f"\nTotal: {len(parquet_files)} datasets")
