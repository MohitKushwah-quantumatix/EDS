"""Tests for ScheduleConfig validation and cron expression builder."""

from __future__ import annotations

from datetime import date

import pytest

from eds_loader.config import ScheduleConfig
from eds_loader._scheduler import build_cron_expression, should_run_today


# ---------------------------------------------------------------------------
# ScheduleConfig validation
# ---------------------------------------------------------------------------

class TestScheduleConfigValidation:

    def test_requires_time_or_cron(self):
        with pytest.raises(Exception, match="requires either 'time'"):
            ScheduleConfig(timezone="UTC")

    def test_both_time_and_cron_rejected(self):
        with pytest.raises(Exception, match="set either 'time' or 'cron'"):
            ScheduleConfig(time="02:00", cron="0 2 * * *", timezone="UTC")

    def test_valid_time_style(self):
        cfg = ScheduleConfig(time="02:00", timezone="UTC")
        assert cfg.time == "02:00"
        assert cfg.frequency == "daily"

    def test_valid_cron_style(self):
        cfg = ScheduleConfig(cron="0 2 * * 1-5", timezone="UTC")
        assert cfg.cron == "0 2 * * 1-5"

    def test_invalid_time_format(self):
        with pytest.raises(Exception, match="out of range"):
            ScheduleConfig(time="25:00", timezone="UTC")

    def test_invalid_time_minutes(self):
        with pytest.raises(Exception, match="out of range"):
            ScheduleConfig(time="02:99", timezone="UTC")

    def test_invalid_timezone(self):
        with pytest.raises(Exception, match="Unknown timezone"):
            ScheduleConfig(time="02:00", timezone="InvalidZone/NotReal")

    def test_valid_timezone_kolkata(self):
        cfg = ScheduleConfig(time="02:00", timezone="Asia/Kolkata")
        assert cfg.timezone == "Asia/Kolkata"

    def test_weekly_requires_on_day(self):
        with pytest.raises(Exception, match="requires 'on_day'"):
            ScheduleConfig(time="02:00", timezone="UTC", frequency="weekly")

    def test_weekly_valid(self):
        cfg = ScheduleConfig(
            time="02:00", timezone="UTC", frequency="weekly", on_day="Monday"
        )
        assert cfg.on_day == "Monday"

    def test_invalid_on_day(self):
        with pytest.raises(Exception, match="must be a weekday name"):
            ScheduleConfig(
                time="02:00", timezone="UTC", frequency="weekly", on_day="Funday"
            )

    def test_monthly_requires_on_date(self):
        with pytest.raises(Exception, match="requires 'on_date'"):
            ScheduleConfig(time="02:00", timezone="UTC", frequency="monthly")

    def test_monthly_valid(self):
        cfg = ScheduleConfig(
            time="02:00", timezone="UTC", frequency="monthly", on_date=1
        )
        assert cfg.on_date == 1

    def test_monthly_on_date_out_of_range(self):
        with pytest.raises(Exception):
            ScheduleConfig(
                time="02:00", timezone="UTC", frequency="monthly", on_date=29
            )

    def test_invalid_skip_day(self):
        with pytest.raises(Exception, match="not a valid weekday"):
            ScheduleConfig(
                time="02:00", timezone="UTC", skip_days=["Funday"]
            )

    def test_invalid_start_date(self):
        with pytest.raises(Exception, match="YYYY-MM-DD"):
            ScheduleConfig(time="02:00", timezone="UTC", start_date="01/09/2026")

    def test_invalid_skip_date(self):
        with pytest.raises(Exception, match="YYYY-MM-DD"):
            ScheduleConfig(time="02:00", timezone="UTC", skip_dates=["not-a-date"])

    def test_start_date_after_end_date(self):
        with pytest.raises(Exception, match="must be before end_date"):
            ScheduleConfig(
                time="02:00",
                timezone="UTC",
                start_date="2026-12-31",
                end_date="2026-01-01",
            )

    def test_valid_full_config(self):
        cfg = ScheduleConfig(
            time="02:00",
            timezone="Asia/Kolkata",
            frequency="daily",
            start_date="2026-09-01",
            end_date="2026-12-31",
            skip_weekends=True,
            skip_dates=["2026-10-02", "2026-10-24"],
            retry_on_failure=True,
            retry_after_minutes=30,
            max_retries=2,
        )
        assert cfg.skip_weekends is True
        assert len(cfg.skip_dates) == 2


# ---------------------------------------------------------------------------
# build_cron_expression
# ---------------------------------------------------------------------------

class TestBuildCronExpression:

    def test_daily(self):
        cfg = ScheduleConfig(time="02:00", timezone="UTC", frequency="daily")
        assert build_cron_expression(cfg) == "0 2 * * *"

    def test_daily_non_zero_minute(self):
        cfg = ScheduleConfig(time="06:30", timezone="UTC", frequency="daily")
        assert build_cron_expression(cfg) == "30 6 * * *"

    def test_every_other_day(self):
        cfg = ScheduleConfig(time="02:00", timezone="UTC", frequency="every_other_day")
        assert build_cron_expression(cfg) == "0 2 */2 * *"

    def test_weekly_monday(self):
        cfg = ScheduleConfig(
            time="02:00", timezone="UTC", frequency="weekly", on_day="Monday"
        )
        assert build_cron_expression(cfg) == "0 2 * * 1"

    def test_weekly_friday(self):
        cfg = ScheduleConfig(
            time="14:00", timezone="UTC", frequency="weekly", on_day="Friday"
        )
        assert build_cron_expression(cfg) == "0 14 * * 5"

    def test_monthly(self):
        cfg = ScheduleConfig(
            time="03:00", timezone="UTC", frequency="monthly", on_date=15
        )
        assert build_cron_expression(cfg) == "0 3 15 * *"

    def test_monthly_first(self):
        cfg = ScheduleConfig(
            time="02:00", timezone="UTC", frequency="monthly", on_date=1
        )
        assert build_cron_expression(cfg) == "0 2 1 * *"

    def test_passthrough_cron(self):
        """When cron is explicitly set, it is returned unchanged."""
        cfg = ScheduleConfig(cron="0 2 * * 1-5", timezone="UTC")
        assert build_cron_expression(cfg) == "0 2 * * 1-5"

    def test_midnight(self):
        cfg = ScheduleConfig(time="00:00", timezone="UTC")
        assert build_cron_expression(cfg) == "0 0 * * *"


# ---------------------------------------------------------------------------
# should_run_today
# ---------------------------------------------------------------------------

class TestShouldRunToday:

    def _cfg(self, **kwargs):
        return ScheduleConfig(time="02:00", timezone="UTC", **kwargs)

    def test_ok_by_default(self):
        cfg = self._cfg()
        ok, reason = should_run_today(cfg, today=date(2026, 8, 26))  # Wednesday
        assert ok is True
        assert reason == "OK"

    def test_before_start_date(self):
        cfg = self._cfg(start_date="2026-09-01")
        ok, reason = should_run_today(cfg, today=date(2026, 8, 26))
        assert ok is False
        assert "before start_date" in reason

    def test_on_start_date(self):
        cfg = self._cfg(start_date="2026-09-01")
        ok, _ = should_run_today(cfg, today=date(2026, 9, 1))
        assert ok is True

    def test_after_end_date(self):
        cfg = self._cfg(end_date="2026-08-25")
        ok, reason = should_run_today(cfg, today=date(2026, 8, 26))
        assert ok is False
        assert "after end_date" in reason

    def test_on_end_date(self):
        cfg = self._cfg(end_date="2026-08-26")
        ok, _ = should_run_today(cfg, today=date(2026, 8, 26))
        assert ok is True

    def test_skip_date(self):
        cfg = self._cfg(skip_dates=["2026-10-02"])
        ok, reason = should_run_today(cfg, today=date(2026, 10, 2))
        assert ok is False
        assert "skip_dates" in reason

    def test_non_skip_date(self):
        cfg = self._cfg(skip_dates=["2026-10-02"])
        ok, _ = should_run_today(cfg, today=date(2026, 10, 3))
        assert ok is True

    def test_skip_weekends_saturday(self):
        cfg = self._cfg(skip_weekends=True)
        ok, reason = should_run_today(cfg, today=date(2026, 8, 29))  # Saturday
        assert ok is False
        assert "skip_weekends" in reason

    def test_skip_weekends_sunday(self):
        cfg = self._cfg(skip_weekends=True)
        ok, reason = should_run_today(cfg, today=date(2026, 8, 30))  # Sunday
        assert ok is False
        assert "skip_weekends" in reason

    def test_skip_weekends_weekday(self):
        cfg = self._cfg(skip_weekends=True)
        ok, _ = should_run_today(cfg, today=date(2026, 8, 31))  # Monday
        assert ok is True

    def test_skip_specific_day(self):
        cfg = self._cfg(skip_days=["Wednesday"])
        ok, reason = should_run_today(cfg, today=date(2026, 8, 26))  # Wednesday
        assert ok is False
        assert "Wednesday" in reason

    def test_skip_specific_day_other_day(self):
        cfg = self._cfg(skip_days=["Wednesday"])
        ok, _ = should_run_today(cfg, today=date(2026, 8, 25))  # Tuesday
        assert ok is True

    def test_combined_rules_skip_date_wins(self):
        """skip_dates checked before skip_weekends."""
        cfg = self._cfg(
            start_date="2026-01-01",
            end_date="2026-12-31",
            skip_weekends=True,
            skip_dates=["2026-08-26"],
        )
        ok, reason = should_run_today(cfg, today=date(2026, 8, 26))  # Wednesday but in skip_dates
        assert ok is False
        assert "skip_dates" in reason
