"""Kafka streaming producer for real-time dataset broadcasting.

Sends generated :class:`~polars.DataFrame` rows to Kafka topics as JSON.
The underlying :class:`~kafka.KafkaProducer` is created lazily so that
constructing a :class:`StreamingProducer` never blocks on a reachable broker.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl

__all__ = ["KafkaConfig", "StreamingProducer", "stream_datasets"]

_DEFAULT_BOOTSTRAP_SERVERS = "localhost:9092"
_DEFAULT_TOPIC_PREFIX = ""


@dataclass(frozen=True, slots=True)
class KafkaConfig:
    """Configuration for Kafka streaming, read from environment variables.

    Attributes:
        bootstrap_servers: Comma-separated Kafka broker list.
        topic_prefix: Prefix prepended to dataset names to form topic names.
        realtime: Whether real-time streaming is enabled (``EDS_REALTIME=1``).
    """

    bootstrap_servers: str
    topic_prefix: str
    realtime: bool

    @classmethod
    def from_env(cls) -> KafkaConfig:
        """Build a config from the environment variables.

        ``EDS_REALTIME``, ``KAFKA_BOOTSTRAP_SERVERS`` and
        ``EDS_KAFKA_TOPIC_PREFIX`` are consulted, with sensible defaults.

        Returns:
            A config with defaults applied for missing values.
        """
        return cls(
            bootstrap_servers=os.environ.get(
                "KAFKA_BOOTSTRAP_SERVERS", _DEFAULT_BOOTSTRAP_SERVERS
            ),
            topic_prefix=os.environ.get(
                "EDS_KAFKA_TOPIC_PREFIX", _DEFAULT_TOPIC_PREFIX
            ),
            realtime=os.environ.get("EDS_REALTIME", "0") == "1",
        )

    @property
    def is_enabled(self) -> bool:
        """Return whether real-time streaming is active."""
        return self.realtime


class StreamingProducer:
    """Lazily connects to Kafka and publishes DataFrame rows as JSON.

    The underlying :class:`~kafka.KafkaProducer` is only created on first
    use, so constructing this object is cheap and safe even when no broker is
    reachable.
    """

    def __init__(self, config: KafkaConfig | None = None) -> None:
        """Bind the producer to a configuration.

        Args:
            config: The Kafka settings to use.  Defaults to
                :meth:`KafkaConfig.from_env`.
        """
        self._config = config or KafkaConfig.from_env()
        self._producer: object | None = None

    @property
    def config(self) -> KafkaConfig:
        """Return the producer's configuration."""
        return self._config

    @property
    def is_ready(self) -> bool:
        """Return whether the underlying Kafka producer has been created."""
        return self._producer is not None

    def _get_producer(self) -> object:
        """Lazily create and return the underlying Kafka producer.

        Returns:
            The ``KafkaProducer`` instance.
        """
        if self._producer is None:
            from kafka import KafkaProducer as _KafkaProducer  # noqa: PLC0415

            self._producer = _KafkaProducer(
                bootstrap_servers=self._config.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            )
        return self._producer

    def _topic_for(self, dataset_name: str) -> str:
        """Return the Kafka topic name for a dataset.

        Args:
            dataset_name: The name of the dataset.

        Returns:
            The topic name, prefixed if a prefix is configured.
        """
        if self._config.topic_prefix:
            return f"{self._config.topic_prefix}.{dataset_name}"
        return dataset_name

    def send_dataset(self, dataset_name: str, data: pl.DataFrame) -> None:
        """Send every row of a DataFrame to the dataset's Kafka topic.

        Empty frames are skipped.  The producer is flushed after each dataset
        so messages reach the broker promptly.

        Args:
            dataset_name: The dataset name, used to derive the topic.
            data: The DataFrame whose rows should be published.
        """
        if data.is_empty():
            return
        producer = self._get_producer()
        topic = self._topic_for(dataset_name)
        for record in data.to_dicts():
            producer.send(topic, value=record)
        producer.flush()

    def stream_datasets(self, datasets: Mapping[str, pl.DataFrame]) -> None:
        """Send every dataset's rows to its corresponding Kafka topic.

        Args:
            datasets: Dataset name to DataFrame mapping.
        """
        for dataset_name, data in datasets.items():
            self.send_dataset(dataset_name, data)

    def close(self) -> None:
        """Close the underlying producer if one was created."""
        if self._producer is not None:
            self._producer.close()
            self._producer = None


def stream_datasets(
    datasets: Mapping[str, pl.DataFrame],
    config: KafkaConfig | None = None,
) -> None:
    """Publish a batch of datasets to Kafka.

    Creates a :class:`StreamingProducer`, sends all datasets, then closes it.

    Args:
        datasets: Dataset name to DataFrame mapping.
        config: Optional configuration override.  Defaults to env-based config.
    """
    producer = StreamingProducer(config=config)
    producer.stream_datasets(datasets)
    producer.close()