"""Conditional streaming wrapper that respects the ``EDS_REALTIME`` flag.

Provides a single entry point -- :func:`stream_if_enabled` -- that the
executor and CLI call after generating data.  It short-circuits when
streaming is disabled or when Kafka is unreachable, so callers never have
to handle Kafka-specific exceptions.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

import polars as pl

__all__ = ["stream_if_enabled"]

_logger = logging.getLogger(__name__)


def stream_if_enabled(
    datasets: Mapping[str, pl.DataFrame],
    stream: bool = False,
) -> None:
    """Publish datasets to Kafka if both the flag and ``EDS_REALTIME`` are set.

    If streaming is disabled, or if Kafka cannot be reached, this function
    logs a warning (or nothing) and returns silently.  It never raises.

    Args:
        datasets: Dataset name to DataFrame mapping.
        stream: Whether the caller requested streaming.
    """
    if not stream:
        return

    try:
        from eds.infrastructure.kafka.producer import (  # noqa: PLC0415
            KafkaConfig,
            StreamingProducer,
        )
    except ImportError as exc:
        _logger.warning(
            "kafka-python is not installed; streaming disabled: %s", exc
        )
        return

    try:
        config = KafkaConfig.from_env()
        if not config.is_enabled:
            _logger.debug(
                "EDS_REALTIME is not set; streaming disabled"
            )
            return

        producer = StreamingProducer(config=config)
        producer.stream_datasets(datasets)
        producer.close()
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "Kafka streaming unavailable, continuing without it: %s",
            exc,
        )