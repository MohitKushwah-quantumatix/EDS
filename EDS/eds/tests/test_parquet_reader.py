"""Tests for reading previously exported Parquet datasets."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from eds.exporters.parquet.reader import DatasetNotFoundError, read_dataset, read_datasets
from eds.exporters.parquet.writer import write_datasets
from eds.generators.master_data import MasterData


def test_round_trip_through_the_writer(tmp_path: Path) -> None:
    """A dataset written by the exporter reads back unchanged."""
    frame = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    write_datasets({"sample": frame}, tmp_path)

    assert read_dataset("sample", tmp_path).equals(frame)


def test_read_datasets_preserves_request_order(tmp_path: Path) -> None:
    """Datasets come back keyed in the order requested."""
    write_datasets({"one": pl.DataFrame({"a": [1]}), "two": pl.DataFrame({"a": [2]})}, tmp_path)

    assert list(read_datasets(["two", "one"], tmp_path)) == ["two", "one"]


def test_master_data_round_trips(master_data: MasterData, tmp_path: Path) -> None:
    """The F001 geography datasets survive a write and read cycle."""
    write_datasets(master_data.datasets, tmp_path)

    restored = read_datasets(["countries", "states", "cities"], tmp_path)

    for name, frame in restored.items():
        assert frame.equals(master_data[name]), name


def test_missing_dataset_names_the_next_step(tmp_path: Path) -> None:
    """The error tells the user which command to run first."""
    with pytest.raises(DatasetNotFoundError, match="generate master-data"):
        read_dataset("cities", tmp_path)


def test_missing_dataset_is_a_file_not_found_error(tmp_path: Path) -> None:
    """The error is catchable as a standard FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        read_dataset("cities", tmp_path)


def test_read_datasets_fails_on_the_first_missing_entry(tmp_path: Path) -> None:
    """A partially populated directory is still an error."""
    write_datasets({"countries": pl.DataFrame({"a": [1]})}, tmp_path)

    with pytest.raises(DatasetNotFoundError, match="'states'"):
        read_datasets(["countries", "states"], tmp_path)
