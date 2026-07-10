"""
Tests for src/utils/time_utils.py

Covers:
  - Known UTC game_start_time strings convert to the correct ET wall-clock time
  - DST boundary: a date in EDT (summer) and a date in EST (winter) both convert correctly
  - The Item 1 ">1 hour out" decision produces the correct answer for known inputs
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.utils.time_utils import now_et, parse_game_start_et

_ET = ZoneInfo("America/New_York")
_UTC = timezone.utc


class TestParseGameStartEt:
    """parse_game_start_et: UTC ISO string → ET-aware datetime."""

    def test_space_separated_no_offset_edt(self):
        # "2026-07-10 22:40:00" stored as UTC → 6:40 PM EDT (UTC-4 in summer)
        result = parse_game_start_et("2026-07-10 22:40:00")
        assert result.tzinfo is not None
        assert result.hour == 18
        assert result.minute == 40
        assert result.year == 2026
        assert result.month == 7
        assert result.day == 10

    def test_iso_with_utc_offset_edt(self):
        # Same time with explicit +00:00 suffix
        result = parse_game_start_et("2026-07-10T22:40:00+00:00")
        assert result.hour == 18
        assert result.minute == 40

    def test_dst_summer_edt_offset(self):
        # During EDT (summer), UTC-4. Game at 23:05 UTC = 7:05 PM ET.
        result = parse_game_start_et("2026-07-15 23:05:00")
        assert result.hour == 19
        assert result.minute == 5
        # Confirm UTC offset is -4h in summer
        offset_hours = result.utcoffset().total_seconds() / 3600
        assert offset_hours == -4

    def test_dst_winter_est_offset(self):
        # During EST (winter), UTC-5. Game at 00:10 UTC on Jan 10 = 7:10 PM ET Jan 9.
        result = parse_game_start_et("2026-01-10 00:10:00")
        # Confirm UTC offset is -5h in winter
        offset_hours = result.utcoffset().total_seconds() / 3600
        assert offset_hours == -5
        assert result.hour == 19
        assert result.minute == 10
        assert result.day == 9  # rolled back a day

    def test_returns_aware_datetime(self):
        result = parse_game_start_et("2026-07-10 22:40:00")
        assert result.tzinfo is not None

    def test_invalid_string_raises(self):
        with pytest.raises((ValueError, Exception)):
            parse_game_start_et("not-a-date")


class TestNowEt:
    """now_et: returns timezone-aware ET datetime."""

    def test_returns_aware_datetime(self):
        result = now_et()
        assert result.tzinfo is not None

    def test_zone_is_et(self):
        result = now_et()
        # ZoneInfo key or pytz zone — check offset is -4 or -5
        offset_hours = result.utcoffset().total_seconds() / 3600
        assert offset_hours in (-4, -5)


class TestItemOneHourOutDecision:
    """
    Item 1's '>1 hour out' rebuild/reduce decision uses DB-side SQL
    (EXTRACT EPOCH FROM (game_start_time::timestamptz - now())).

    These tests validate the Python equivalent using parse_game_start_et
    to confirm the logic direction is correct for known inputs.
    """

    def _seconds_until(self, game_utc_str: str, fake_now_utc: datetime) -> float:
        """Mimic the DB EXTRACT(EPOCH FROM ...) comparison in Python."""
        game_et = parse_game_start_et(game_utc_str)
        game_utc = game_et.astimezone(_UTC)
        return (game_utc - fake_now_utc).total_seconds()

    def test_game_more_than_1hr_out(self):
        # Game at 22:40 UTC, "now" is 20:00 UTC → 2h 40m remaining → >1hr, should rebuild
        fake_now = datetime(2026, 7, 10, 20, 0, 0, tzinfo=_UTC)
        secs = self._seconds_until("2026-07-10 22:40:00", fake_now)
        assert secs > 3600, f"Expected >3600s, got {secs}"

    def test_game_less_than_1hr_out(self):
        # Game at 22:40 UTC, "now" is 22:10 UTC → 30m remaining → <1hr, should reduce
        fake_now = datetime(2026, 7, 10, 22, 10, 0, tzinfo=_UTC)
        secs = self._seconds_until("2026-07-10 22:40:00", fake_now)
        assert secs < 3600, f"Expected <3600s, got {secs}"

    def test_game_already_started(self):
        # Game at 22:40 UTC, "now" is 23:00 UTC → game started → negative seconds
        fake_now = datetime(2026, 7, 10, 23, 0, 0, tzinfo=_UTC)
        secs = self._seconds_until("2026-07-10 22:40:00", fake_now)
        assert secs < 0, f"Expected negative seconds for started game, got {secs}"

    def test_boundary_exactly_1hr(self):
        # Game at 22:40 UTC, "now" is 21:40 UTC → exactly 3600s
        fake_now = datetime(2026, 7, 10, 21, 40, 0, tzinfo=_UTC)
        secs = self._seconds_until("2026-07-10 22:40:00", fake_now)
        assert abs(secs - 3600) < 1, f"Expected ~3600s, got {secs}"
