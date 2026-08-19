"""Tests for Kafka streaming infrastructure."""

from __future__ import annotations

import builtins
import os
import sys
from collections.abc import Mapping
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from eds.infrastructure.kafka.consumer import (
    BillingConsumer,
    ConsumerConfig,
    EncounterConsumer,
    PatientConsumer,
    VitalsConsumer,
    get_consumer,
    run_consumer,
)
from eds.infrastructure.kafka.producer import KafkaConfig, StreamingProducer, stream_datasets
from eds.infrastructure.kafka.streaming import stream_if_enabled


pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")


class TestKafkaConfig:
    """Tests for KafkaConfig."""

    def test_from_env_defaults(self) -> None:
        config = KafkaConfig.from_env()
        assert config.bootstrap_servers == "localhost:9092"
        assert config.topic_prefix == ""
        assert config.realtime is False

    def test_from_env_with_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker1:9092,broker2:9092")
        monkeypatch.setenv("EDS_KAFKA_TOPIC_PREFIX", "test.prefix")
        monkeypatch.setenv("EDS_REALTIME", "1")
        config = KafkaConfig.from_env()
        assert config.bootstrap_servers == "broker1:9092,broker2:9092"
        assert config.topic_prefix == "test.prefix"
        assert config.realtime is True

    def test_is_enabled_false_by_default(self) -> None:
        config = KafkaConfig.from_env()
        assert config.is_enabled is False

    def test_is_enabled_when_realtime_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EDS_REALTIME", "1")
        config = KafkaConfig.from_env()
        assert config.is_enabled is True


class TestConsumerConfig:
    """Tests for ConsumerConfig."""

    def test_from_env_defaults(self) -> None:
        config = ConsumerConfig.from_env()
        assert config.bootstrap_servers == "localhost:9092"
        assert config.topic_prefix == ""
        assert config.group_id == "eds-consumers"

    def test_from_env_with_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker:9092")
        monkeypatch.setenv("EDS_KAFKA_TOPIC_PREFIX", "prefix")
        monkeypatch.setenv("EDS_CONSUMER_GROUP_ID", "my-group")
        config = ConsumerConfig.from_env()
        assert config.bootstrap_servers == "broker:9092"
        assert config.topic_prefix == "prefix"
        assert config.group_id == "my-group"

    def test_topic_for_no_prefix(self) -> None:
        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            topic_prefix="",
            group_id="test",
        )
        assert config.topic_for("patients") == "patients"

    def test_topic_for_with_prefix(self) -> None:
        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            topic_prefix="my.prefix",
            group_id="test",
        )
        assert config.topic_for("patients") == "my.prefix.patients"

    def test_topics_for_tuple(self) -> None:
        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            topic_prefix="p",
            group_id="test",
        )
        assert config.topics_for(("a", "b")) == ["p.a", "p.b"]

    def test_topics_for_dict(self) -> None:
        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            topic_prefix="",
            group_id="test",
        )
        assert config.topics_for({"x": 1, "y": 2}) == ["x", "y"]


class TestStreamingProducer:
    """Tests for StreamingProducer."""

    def test_lazy_initialization(self) -> None:
        config = KafkaConfig(
            bootstrap_servers="localhost:9092",
            topic_prefix="",
            realtime=True,
        )
        producer = StreamingProducer(config=config)
        assert producer.is_ready is False

    def test_topic_for_no_prefix(self) -> None:
        config = KafkaConfig(
            bootstrap_servers="localhost:9092",
            topic_prefix="",
            realtime=False,
        )
        producer = StreamingProducer(config=config)
        assert producer._topic_for("patients") == "patients"

    def test_topic_for_with_prefix(self) -> None:
        config = KafkaConfig(
            bootstrap_servers="localhost:9092",
            topic_prefix="test",
            realtime=False,
        )
        producer = StreamingProducer(config=config)
        assert producer._topic_for("patients") == "test.patients"

    def test_send_dataset_skips_empty(self) -> None:
        config = KafkaConfig(
            bootstrap_servers="localhost:9092",
            topic_prefix="",
            realtime=True,
        )
        producer = StreamingProducer(config=config)
        empty_df = pl.DataFrame(schema={"id": pl.Int64()})
        producer.send_dataset("empty", empty_df)
        assert producer.is_ready is False

    def test_stream_datasets(self) -> None:
        config = KafkaConfig(
            bootstrap_servers="localhost:9092",
            topic_prefix="",
            realtime=True,
        )
        producer = StreamingProducer(config=config)
        mock_kafka_producer = MagicMock()
        with patch.object(producer, "_get_producer", return_value=mock_kafka_producer):
            df = pl.DataFrame({"id": [1, 2], "name": ["a", "b"]})
            producer.stream_datasets({"patients": df})
        assert mock_kafka_producer.send.call_count == 2
        mock_kafka_producer.flush.assert_called_once()

    def test_stream_datasets_skips_empty(self) -> None:
        config = KafkaConfig(
            bootstrap_servers="localhost:9092",
            topic_prefix="",
            realtime=True,
        )
        producer = StreamingProducer(config=config)
        mock_kafka_producer = MagicMock()
        with patch.object(producer, "_get_producer", return_value=mock_kafka_producer):
            df = pl.DataFrame({"id": [1], "name": ["a"]})
            empty_df = pl.DataFrame(schema={"id": pl.Int64()})
            producer.stream_datasets({"patients": df, "empty": empty_df})
        assert mock_kafka_producer.send.call_count == 1

    def test_close(self) -> None:
        config = KafkaConfig(
            bootstrap_servers="localhost:9092",
            topic_prefix="",
            realtime=True,
        )
        producer = StreamingProducer(config=config)
        mock_producer = MagicMock()
        producer._producer = mock_producer
        producer.close()
        assert producer._producer is None
        mock_producer.close.assert_called_once()

    def test_stream_datasets_function(self) -> None:
        config = KafkaConfig(
            bootstrap_servers="localhost:9092",
            topic_prefix="",
            realtime=True,
        )
        mock_producer = MagicMock()
        with patch('eds.infrastructure.kafka.producer.StreamingProducer', return_value=mock_producer):
            df = pl.DataFrame({"id": [1]})
            stream_datasets({"x": df}, config=config)
        mock_producer.stream_datasets.assert_called_once_with({"x": df})
        mock_producer.close.assert_called_once()


class TestStreamIfEnabled:
    """Tests for stream_if_enabled wrapper."""

    def test_no_stream_flag(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("DEBUG"):
            stream_if_enabled({"x": pl.DataFrame()}, stream=False)
        assert "EDS_REALTIME is not set" not in caplog.text

    def test_kafka_import_error(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        import eds.infrastructure.kafka.streaming as streaming_module
        monkeypatch.delattr(streaming_module, "StreamingProducer", raising=False)
        monkeypatch.delattr(streaming_module, "KafkaConfig", raising=False)

        original_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "eds.infrastructure.kafka.producer" or name.startswith("eds.infrastructure.kafka.producer"):
                raise ImportError("No module named 'kafka'")
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=mock_import):
            with caplog.at_level("WARNING"):
                stream_if_enabled({"x": pl.DataFrame()}, stream=True)
        assert "kafka-python is not installed" in caplog.text

    def test_realtime_not_set(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.delenv("EDS_REALTIME", raising=False)
        with caplog.at_level("DEBUG"):
            stream_if_enabled({"x": pl.DataFrame()}, stream=True)
        assert "EDS_REALTIME is not set" in caplog.text

    def test_streaming_unavailable(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("EDS_REALTIME", "1")
        with patch('eds.infrastructure.kafka.producer.StreamingProducer', side_effect=Exception("no broker")):
            with caplog.at_level("WARNING"):
                stream_if_enabled({"x": pl.DataFrame()}, stream=True)
        assert "Kafka streaming unavailable" in caplog.text


class TestConsumers:
    """Tests for Kafka consumer classes."""

    def test_encounter_consumer_topics(self) -> None:
        consumer = EncounterConsumer()
        assert "encounters" in consumer.topics
        assert "lab_results" in consumer.topics

    def test_billing_consumer_topics(self) -> None:
        consumer = BillingConsumer()
        assert "billing" in consumer.topics
        assert "claims" in consumer.topics

    def test_vitals_consumer_topics(self) -> None:
        consumer = VitalsConsumer()
        assert "vitals" in consumer.topics

    def test_patient_consumer_topics(self) -> None:
        consumer = PatientConsumer()
        assert "patients" in consumer.topics
        assert "immunizations" in consumer.topics

    def test_get_consumer_valid(self) -> None:
        consumer = get_consumer("encounters")
        assert isinstance(consumer, EncounterConsumer)

    def test_get_consumer_invalid(self) -> None:
        with pytest.raises(ValueError, match="unknown consumer"):
            get_consumer("invalid")

    def test_consumer_lazy_initialization(self) -> None:
        consumer = PatientConsumer()
        assert consumer.is_ready is False

    def test_run_consumer_keyboard_interrupt(self) -> None:
        consumer = PatientConsumer()
        consumer.consume = MagicMock(side_effect=KeyboardInterrupt)
        with patch('builtins.print') as mock_print:
            run_consumer(consumer)
        mock_print.assert_any_call("\nStopping PatientConsumer.", file=sys.stderr)
