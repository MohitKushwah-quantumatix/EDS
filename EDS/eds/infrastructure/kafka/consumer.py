"""Kafka consumers for healthcare streaming datasets.

Each consumer subscribes to a group of Kafka topics that correspond to a
healthcare domain concept (encounters, billing, vitals, patients).  The
underlying :class:`~kafka.KafkaConsumer` is created lazily.

Topic naming convention:
    All healthcare topics are prefixed with ``healthcare.`` so they are
    domain-scoped (e.g. ``healthcare.encounters``, ``healthcare.claims``).

Consumers:
    - EncounterConsumer: processes encounter events (admissions, discharges)
    - BillingConsumer: processes billing/claims for insurance verification
    - VitalsConsumer: processes vitals for real-time anomaly detection
    - PatientConsumer: processes patient demographic updates
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
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


@dataclass(frozen=True, slots=True)
class ConsumerConfig:
    """Configuration for a Kafka consumer, read from environment variables.

    Attributes:
        bootstrap_servers: Comma-separated Kafka broker list.
        group_id: Consumer group identifier.
    """

    bootstrap_servers: str
    group_id: str

    @classmethod
    def from_env(cls) -> ConsumerConfig:
        """Build a config from environment variables.

        ``KAFKA_BOOTSTRAP_SERVERS`` and ``EDS_CONSUMER_GROUP_ID`` are
        consulted, with sensible defaults.

        Returns:
            A config with defaults applied for missing values.
        """
        return cls(
            bootstrap_servers=os.environ.get(
                "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
            ),
            group_id=os.environ.get(
                "EDS_CONSUMER_GROUP_ID", "eds-consumers"
            ),
        )


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

            self._consumer = _KafkaConsumer(
                *self.topics,
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
    """Consumes encounter-related datasets from Kafka.

    Use cases:
        - Real-time bed occupancy tracking
        - Emergency department load balancing
        - Admission/discharge workflow automation

    Topics: encounters, appointments, medications_prescribed, diagnoses,
            procedures, lab_results, radiology_reports,
            medication_administration, admissions, discharge_summaries, referrals
    """

    topics: tuple[str, ...] = (
        "healthcare.encounters",
        "healthcare.appointments",
        "healthcare.medications_prescribed",
        "healthcare.diagnoses",
        "healthcare.procedures",
        "healthcare.lab_results",
        "healthcare.radiology_reports",
        "healthcare.medication_administration",
        "healthcare.admissions",
        "healthcare.discharge_summaries",
        "healthcare.referrals",
    )


class BillingConsumer(_HealthcareConsumer):
    """Consumes billing-related datasets from Kafka.

    Use cases:
        - Real-time insurance verification
        - Fraud detection on claims
        - Billing exception alerts

    Topics: billing, claims
    """

    topics: tuple[str, ...] = (
        "healthcare.billing",
        "healthcare.claims",
    )


class VitalsConsumer(_HealthcareConsumer):
    """Consumes vitals-related datasets from Kafka.

    Use cases:
        - Real-time alert generation for abnormal vitals
        - ICU/ward monitoring dashboards
        - Early warning score calculation

    Topics: vitals
    """

    topics: tuple[str, ...] = (
        "healthcare.vitals",
    )


class PatientConsumer(_HealthcareConsumer):
    """Consumes patient-related datasets from Kafka.

    Use cases:
        - Real-time patient registry updates
        - Compliance audit logging
        - Patient outreach coordination

    Topics: patients, patient_addresses, patient_insurance,
            patient_allergies, immunizations, patient_emergency_contacts
    """

    topics: tuple[str, ...] = (
        "healthcare.patients",
        "healthcare.patient_addresses",
        "healthcare.patient_insurance",
        "healthcare.patient_allergies",
        "healthcare.immunizations",
        "healthcare.patient_emergency_contacts",
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
