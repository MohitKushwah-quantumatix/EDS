"""Tests for cron_runner scheduling logic."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cron_runner import (
    _normalize_domain_configs,
    _parse_date_range,
    _wait_until_daily_time,
)


# ── _normalize_domain_configs ─────────────────────────────────────────


class TestNormalizeDomainConfigs:
    def test_legacy_single_domain(self):
        config = {
            "domain": "retail",
            "project_dir": "my-shop",
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
        }
        result = _normalize_domain_configs(config)
        assert len(result) == 1
        assert result[0]["domain"] == "retail"

    def test_multi_domain_list(self):
        config = {
            "domains": [
                {
                    "domain": "retail",
                    "project_dir": "my-shop",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-03",
                },
                {
                    "domain": "healthcare",
                    "project_dir": "my-hospital",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-03",
                },
            ]
        }
        result = _normalize_domain_configs(config)
        assert len(result) == 2
        assert result[0]["domain"] == "retail"
        assert result[1]["domain"] == "healthcare"

    def test_multi_domain_preserves_keys(self):
        config = {
            "domains": [
                {"domain": "retail", "seed": 42, "cron_daily_time": "08:00"},
            ]
        }
        result = _normalize_domain_configs(config)
        assert result[0]["seed"] == 42
        assert result[0]["cron_daily_time"] == "08:00"


# ── _parse_date_range ─────────────────────────────────────────────────


class TestParseDateRange:
    def test_string_dates(self):
        dc = {"start_date": "2026-01-01", "end_date": "2026-01-05"}
        s, e, interval, daily = _parse_date_range(dc)
        assert s == date(2026, 1, 1)
        assert e == date(2026, 1, 5)
        assert interval is None
        assert daily is None

    def test_date_objects(self):
        dc = {"start_date": date(2026, 1, 1), "end_date": date(2026, 1, 5)}
        s, e, interval, daily = _parse_date_range(dc)
        assert s == date(2026, 1, 1)
        assert e == date(2026, 1, 5)

    def test_scheduling_settings(self):
        dc = {
            "start_date": "2026-01-01",
            "end_date": "2026-01-05",
            "cron_interval_minutes": 30,
            "cron_daily_time": "08:30",
        }
        s, e, interval, daily = _parse_date_range(dc)
        assert interval == 30
        assert daily == "08:30"

    def test_missing_scheduling_defaults_none(self):
        dc = {"start_date": "2026-01-01", "end_date": "2026-01-05"}
        _, _, interval, daily = _parse_date_range(dc)
        assert interval is None
        assert daily is None

    def test_invalid_date_raises(self):
        dc = {"start_date": "not-a-date", "end_date": "2026-01-05"}
        with pytest.raises(Exception):
            _parse_date_range(dc)


# ── _wait_until_daily_time ────────────────────────────────────────────


class TestWaitUntilDailyTime:
    def test_future_time_returns_positive_seconds(self):
        fixed_now = datetime(2026, 1, 1, 12, 0, 0)
        daily_time = "12:30"
        wait = _wait_until_daily_time(daily_time, now=fixed_now)
        assert wait == 30 * 60

    def test_past_time_returns_zero(self):
        fixed_now = datetime(2026, 1, 1, 13, 0, 0)
        daily_time = "12:30"
        wait = _wait_until_daily_time(daily_time, now=fixed_now)
        assert wait == 0

    def test_exact_now_returns_zero(self):
        fixed_now = datetime(2026, 1, 1, 12, 30, 0)
        daily_time = "12:30"
        wait = _wait_until_daily_time(daily_time, now=fixed_now)
        assert wait == 0

    def test_midnight_cross_day(self):
        fixed_now = datetime(2026, 1, 1, 23, 30, 0)
        daily_time = "00:15"
        wait = _wait_until_daily_time(daily_time, now=fixed_now)
        assert wait == 0
