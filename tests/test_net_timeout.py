"""
tests/test_net_timeout.py

Regression test for the 2026-07-23 -> 2026-08-04 parlay pipeline stall.

Root cause: get_pitcher_ranks()/get_team_offensive_ranks() (and several other
call sites) call the third-party `statsapi` package's wrapper functions
(statsapi.get, statsapi.player_stat_data, statsapi.schedule, ...), which call
requests.get() internally with no timeout and no way to pass one in. A
slow/hanging upstream response blocks the calling thread forever, with no
exception and no log output.

Fix: src/utils/net.py's call_with_timeout() runs the call in a daemon thread
and enforces a wall-clock timeout, returning a default value and logging
clearly instead of hanging.
"""
import time

from src.utils.net import call_with_timeout


class TestCallWithTimeout:
    def test_fast_call_returns_value(self):
        """A call that finishes well within the timeout returns its result."""
        result = call_with_timeout(lambda: 42, timeout=1, default="fallback")
        assert result == 42

    def test_hanging_call_returns_default_within_timeout(self):
        """
        A call that never returns (simulating the unbounded statsapi.get()
        hang) must not block the caller past `timeout` seconds — this is
        exactly the failure mode that stalled the pipeline silently at
        [7/8] Computing trend signals for 12 days.
        """
        def _hangs_forever():
            time.sleep(3600)
            return "should never get here"

        start = time.time()
        result = call_with_timeout(_hangs_forever, timeout=0.5, default=None)
        elapsed = time.time() - start

        assert result is None
        assert elapsed < 2.0, f"call_with_timeout took {elapsed:.2f}s, expected to bound at ~0.5s"

    def test_raising_call_returns_default_not_exception(self):
        """An exception inside the wrapped call is caught and logged, not raised."""
        def _boom():
            raise ValueError("upstream API error")

        result = call_with_timeout(_boom, timeout=1, default="fallback")
        assert result == "fallback"

    def test_default_defaults_to_none(self):
        def _boom():
            raise RuntimeError("x")

        assert call_with_timeout(_boom, timeout=1) is None

    def test_args_and_kwargs_are_passed_through(self):
        def _add(a, b, c=0):
            return a + b + c

        result = call_with_timeout(_add, 1, 2, timeout=1, c=3)
        assert result == 6
