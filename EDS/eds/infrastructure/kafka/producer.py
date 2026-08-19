"""Kafka streaming producer for real-time dataset broadcasting.

Sends generated :class:`~polars.DataFrame` rows to Kafka topics as JSON.
Optionally registers a JSON Schema with the Confluent Schema Registry so that
consumers can validate and deserialize messages.  The underlying
:class:`~kafka.KafkaProducer` is created lazily so that constructing a
:class:`StreamingProducer` never blocks on a reachable broker.
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
_DEFAULT_SCHEMA_REGISTRY_URL = "http://localhost:8081"
_DEFAULT_SCHEMA_REGISTRY_URL = "http://localhost:8081"

__all__ = ["KafkaConfig", "StreamingProducer", "stream_datasets"]

_DEFAULT_BOOTSTRAP_SERVERS = "localhost:9092"
_DEFAULT_TOPIC_PREFIX = ""
_DEFAULT_SCHEMA_REGISTRY_URL = "http://localhost:8081"


@dataclass(frozen=True, slots=True)
class KafkaConfig:
    """Configuration for Kafka streaming, read from environment variables.

    Attributes:
        bootstrap_servers: Comma-separated Kafka broker list.
        topic_prefix: Domain prefix prepended to dataset names (e.g. "healthcare").
        realtime: Whether real-time streaming is enabled (``EDS_REALTIME=1``).
        schema_registry_url: URL of the Confluent Schema Registry, or empty
            to disable schema registration.
    """

    bootstrap_servers: str
    topic_prefix: str
    realtime: bool
    schema_registry_url: str

    @classmethod
    def from_env(cls) -> KafkaConfig:
        """Build a config from the environment variables.

        ``EDS_REALTIME``, ``KAFKA_BOOTSTRAP_SERVERS``, ``EDS_KAFKA_TOPIC_PREFIX``
        and ``EDS_KAFKA_SCHEMA_REGISTRY_URL`` are consulted, with sensible defaults.

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
            schema_registry_url=os.environ.get(
                "EDS_KAFKA_SCHEMA_REGISTRY_URL", _DEFAULT_SCHEMA_REGISTRY_URL
            ),
        )

    @property
    def is_enabled(self) -> bool:
        """Return whether real-time streaming is active."""
        return self.realtime

    @property
    def has_schema_registry(self) -> bool:
        """Return whether a Schema Registry URL is configured."""
        return bool(self.schema_registry_url)


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
        self._schemas: dict[str, str] = {}

    def _register_schema(self, topic: str, schema: dict[str, object]) -> str:
        """Register a JSON Schema with the Schema Registry for a topic.

        Args:
            topic: The Kafka topic name (becomes the schema subject).
            schema: A JSON Schema dict describing the message structure.

        Returns:
            The schema ID string returned by the registry.
        """
        import requests  # noqa: PLC0415

        url = f"{self._config.schema_registry_url}/subjects/{topic}-value/versions"
        response = requests.post(url, json={"schema": json.dumps(schema)}, timeout=10)
        if response.status_code == 409:
            # Schema already registered
            return str(response.json()["id"])
        response.raise_for_status()
        return str(response.json()["id"])

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

    def _topic_for(self, dataset: str) -> str:
        """Return the Kafka topic name for a dataset.

        Dataset names are expected in ``domain.dataset`` format (e.g.
        ``healthcare.encounters``).  When a prefix is configured only the
        last segment is used, so ``healthcare.encounters`` becomes
        ``healthcare.encounters`` (prefix + dataset).

        Args:
            dataset: The dataset name, optionally with a domain prefix.

        Returns:
            The topic name, prefixed if a prefix is configured.
        """
        if self._config.topic_prefix:
            return f"{self._config.topic_prefix}.{dataset}"
        return dataset

    def send_dataset(self, dataset_name: str, data: pl.DataFrame) -> None:
        """Send every row of a DataFrame to the dataset's Kafka topic.

        Empty frames are skipped.  The producer is flushed after each dataset
        so messages reach the broker promptly.  If a Schema Registry URL is
        configured, a JSON Schema is registered first.

        Args:
            dataset_name: The dataset name, used to derive the topic.
            data: The DataFrame whose rows should be published.
        """
        if data.is_empty():
            return
        producer = self._get_producer()
        topic = self._topic_for(dataset_name)
        if self._config.has_schema_registry and topic not in self._schemas:
            schema = _infer_json_schema(data)
            try:
                self._register_schema(topic, schema)
                self._schemas[topic] = str(schema.get("name", topic))
            except Exception:
                # Schema registration is best-effort: data should still
                # be streamed even if the registry is unavailable.
                pass
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

def _infer_json_schema(df: pl.DataFrame) -> dict[str, object]:
    """Infer a minimal JSON Schema from a DataFrame's columns.

    Args:
        df: The DataFrame to infer a schema from.

    Returns:
        A JSON Schema dict with properties derived from column names and
        Polars dtypes.
    """
    _POLARS_TO_JSON = {
        "Int64": "integer",
        "Int32": "integer",
        "Int16": "integer",
        "Int8": "integer",
        "UInt64": "integer",
        "UInt32": "integer",
        "UInt16": "integer",
        "UInt8": "integer",
        "Float64": "number",
        "Float32": "number",
        "Float16": "number",
        "Boolean": "boolean",
        "String": "string",
        "Date": {"type": "string", "format": "date"},
        "Datetime": {"type": "string", "format": "date-time"},
        "Time": {"type": "string", "format": "time"},
    }

    properties: dict[str, object] = {}
    for name, dtype in zip(df.columns, df.dtypes):
        dtype_name = str(dtype)
        mapped = _POLARS_TO_JSON.get(dtype_name, "string")
        if isinstance(mapped, str):
            properties[name] = {"type": mapped}
        else:
            properties[name] = mapped

    return {
        "name": "dataset-record",
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
