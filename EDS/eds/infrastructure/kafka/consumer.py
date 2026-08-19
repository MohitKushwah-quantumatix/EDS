"""Kafka consumers for healthcare streaming datasets.

Each consumer subscribes to a group of Kafka topics that correspond to a
healthcare domain concept (encounters, billing, vitals, patients).  The
underlying :class:`~kafka.KafkaConsumer` is created lazily.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ConsumerConfig",
    "EncounterConsumer",
    "BillingConsumer",
    "VitalsConsumer",
    "PatientConsumer",
    "run_consumer",
]

_DEFAULT_BOOTSTRAP_SERVERS = "localhost:9092"
_DEFAULT_TOPIC_PREFIX = ""
_DEFAULT_GROUP_ID = "eds-consumers"


@dataclass(frozen=True, slots=True)
class ConsumerConfig:
    """Configuration for a Kafka consumer, read from environment variables.

    Attributes:
        bootstrap_servers: Comma-separated Kafka broker list.
        topic_prefix: Prefix prepended to dataset names to form topic names.
        group_id: Consumer group identifier.
    """

    bootstrap_servers: str
    topic_prefix: str
    group_id: str

    @classmethod
    def from_env(cls) -> ConsumerConfig:
        """Build a config from environment variables.

        ``KAFKA_BOOTSTRAP_SERVERS``, ``EDS_KAFKA_TOPIC_PREFIX`` and
        ``EDS_CONSUMER_GROUP_ID`` are consulted, with sensible defaults.

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
            group_id=os.environ.get(
                "EDS_CONSUMER_GROUP_ID", _DEFAULT_GROUP_ID
            ),
        )

    def topic_for(self, dataset_name: str) -> str:
        """Return the topic name for a dataset.

        Args:
            dataset_name: The dataset name.

        Returns:
            The topic name, prefixed if a prefix is configured.
        """
        if self.topic_prefix:
            return f"{self.topic_prefix}.{dataset_name}"
        return dataset_name

    def topics_for(self, dataset_names: MutableMapping[str, Any] | tuple[str, ...]) -> list[str]:
        """Return the topic names for a collection of dataset names.

        Args:
            dataset_names: Iterable of dataset names.

        Returns:
            List of fully-qualified topic names.
        """
        return [self.topic_for(name) for name in dataset_names]


class _HealthcareConsumer:
    """Base class for healthcare Kafka consumers.

    Subclasses declare their ``topics`` tuple.  The underlying
    :class:`~kafka.KafkaConsumer` is created lazily on first consumption.
    """

    topics: tuple[str, ...] = ()

    def __init__(self, config: ConsumerConfig | None = None) -> None:
        """Initialize the consumer with optional configuration.

        Args:
            config: Consumer configuration.  Defaults to env-based config.
        """
        self._config = config or ConsumerConfig.from_env()
        self._consumer: object | None = None

    @property
    def name(self) -> str:
        """Return the consumer's display name."""
        return self.__class__.__name__

    @property
    def is_ready(self) -> bool:
        """Return whether the underlying Kafka consumer has been created."""
        return self._consumer is not None

    def _get_consumer(self) -> object:
        """Lazily create and return the underlying Kafka consumer.

        Returns:
            The ``KafkaConsumer`` instance subscribed to this consumer's topics.
        """
        if self._consumer is None:
            from kafka import KafkaConsumer as _KafkaConsumer  # noqa: PLC0415

            topic_names = self._config.topics_for(self.topics)
            self._consumer = _KafkaConsumer(
                *topic_names,
                bootstrap_servers=self._config.bootstrap_servers,
                group_id=self._config.group_id,
                auto_offset_reset="earliest",
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                enable_auto_commit=True,
            )
        return self._consumer

    def consume(self) -> Iterator[dict[str, Any]]:
        """Yield messages from the subscribed topics.

        Each yielded dict has ``topic``, ``partition``, ``offset`` and
        ``value`` keys.

        Yields:
            Decoded message dictionaries.
        """
        consumer = self._get_consumer()
        for message in consumer:
            yield {
                "topic": message.topic,
                "partition": message.partition,
                "offset": message.offset,
                "value": message.value,
            }

    def close(self) -> None:
        """Close the underlying consumer if one was created."""
        if self._consumer is not None:
            self._consumer.close()
            self._consumer = None


class EncounterConsumer(_HealthcareConsumer):
    """Consumes encounter-related datasets from Kafka."""

    topics: tuple[str, ...] = (
        "encounters",
        "appointments",
        "medications_prescribed",
        "diagnoses",
        "procedures",
        "lab_results",
        "radiology_reports",
        "medication_administration",
        "admissions",
        "discharge_summaries",
        "referrals",
    )


class BillingConsumer(_HealthcareConsumer):
    """Consumes billing-related datasets from Kafka."""

    topics: tuple[str, ...] = (
        "billing",
        "claims",
        "billing_codes",
        "insurance_plans",
    )


class VitalsConsumer(_HealthcareConsumer):
    """Consumes vitals-related datasets from Kafka."""

    topics: tuple[str, ...] = (
        "vitals",
        "medications_prescribed",
        "diagnoses",
        "procedures",
    )


class PatientConsumer(_HealthcareConsumer):
    """Consumes patient-related datasets from Kafka."""

    topics: tuple[str, ...] = (
        "patients",
        "patient_addresses",
        "patient_insurance",
        "patient_allergies",
        "immunizations",
        "patient_emergency_contacts",
    )


_CONSUMER_REGISTRY: dict[str, type[_HealthcareConsumer]] = {
    "encounters": EncounterConsumer,
    "billing": BillingConsumer,
    "vitals": VitalsConsumer,
    "patients": PatientConsumer,
}


def get_consumer(name: str) -> _HealthcareConsumer:
    """Return an instance of the named consumer.

    Args:
        name: One of ``encounters``, ``billing``, ``vitals``, ``patients``.

    Returns:
        A consumer instance.

    Raises:
        ValueError: If the name is not a known consumer.
    """
    if name not in _CONSUMER_REGISTRY:
        raise ValueError(
            f"unknown consumer {name!r}; choose from {sorted(_CONSUMER_REGISTRY)}"
        )
    return _CONSUMER_REGISTRY[name]()


def run_consumer(consumer: _HealthcareConsumer) -> None:
    """Run a consumer, printing messages as JSON until interrupted.

    Args:
        consumer: The consumer to run.
    """
    print(f"Starting {consumer.name}...", file=sys.stderr)
    try:
        for msg in consumer.consume():
            print(json.dumps(msg, default=str), flush=True)
    except KeyboardInterrupt:
        print(f"\nStopping {consumer.name}.", file=sys.stderr)
    finally:
        consumer.close()