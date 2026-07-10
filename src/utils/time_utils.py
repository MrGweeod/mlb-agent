"""
time_utils.py — Canonical timezone helpers for the MLB Parlay Agent.

All game_start_time values are stored as UTC ISO strings (e.g. "2026-07-10 22:40:00"
or "2026-07-10T22:40:00+00:00"). Any comparison against "now" must go through these
helpers so UTC→ET conversion is never scattered or missed.

Uses zoneinfo (stdlib, Python 3.9+) as the single timezone library — do not mix in pytz.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    """Current time in America/New_York, timezone-aware."""
    return datetime.now(_ET)


def parse_game_start_et(raw_utc: str) -> datetime:
    """Parse a UTC ISO timestamp string (as stored in game_start_time) and
    return it converted to America/New_York, timezone-aware.

    Accepts both formats written by the pipeline:
      - "2026-07-10 22:40:00"          (space-separated, no offset — assumed UTC)
      - "2026-07-10T22:40:00+00:00"    (ISO 8601 with UTC offset)
    """
    raw = str(raw_utc).strip()

    # Try fromisoformat first — handles both "T" and " " separators in Python 3.11+,
    # and handles "+00:00" offset strings correctly in 3.7+.
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"parse_game_start_et: cannot parse game_start_time value: {raw!r}")

    if dt.tzinfo is None:
        # No offset present — the pipeline stores these as UTC, so attach UTC explicitly.
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        # Normalize any explicit offset to proper UTC (handles +00:00 and any other offset).
        dt = dt.astimezone(timezone.utc)

    return dt.astimezone(_ET)
