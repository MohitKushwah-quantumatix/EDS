"""Kafka streaming infrastructure.

Lazily imports :mod:`kafka` only when a producer or consumer is actually
constructed, so the rest of EDS runs fine without the ``kafka-python``
package installed.
"""

from eds.infrastructure.kafka.consumer import (
    BillingConsumer,
    ConsumerConfig,
    EncounterConsumer,
    PatientConsumer,
    VitalsConsumer,
    run_consumer,
)
from eds.infrastructure.kafka.producer import (
    KafkaConfig,
    StreamingProducer,
    stream_datasets,
)
from eds.infrastructure.kafka.streaming import stream_if_enabled

__all__ = [
    "BillingConsumer",
    "ConsumerConfig",
    "EncounterConsumer",
    "KafkaConfig",
    "PatientConsumer",
    "StreamingProducer",
    "VitalsConsumer",
    "run_consumer",
    "stream_datasets",
    "stream_if_enabled",
]