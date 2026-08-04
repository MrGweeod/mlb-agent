"""
net.py — Hard wall-clock timeout wrapper for third-party API calls that don't
expose their own timeout knob.

The `statsapi` package's wrapper functions (player_stat_data, schedule,
boxscore_data, standings_data, ...) call requests.get() internally with no
timeout and no way to pass one in. A slow/hanging upstream response on any
one of these calls blocks the calling thread forever, with no exception and
no log output — exactly the silent-stall failure mode that took down the
parlay pipeline for 12 days starting 2026-07-23 (root cause confirmed via
live instrumented pipeline run on 2026-08-04: statsapi calls in
get_pitcher_ranks/get_team_offensive_ranks have no timeout, unlike the
already-bounded requests.get(timeout=15) calls in mlb_stats.py).
"""
import queue
import threading


def call_with_timeout(fn, *args, timeout=15, default=None, label=None, **kwargs):
    """
    Run fn(*args, **kwargs) in a daemon thread and enforce `timeout` seconds.

    Returns `default` and logs a clear error if the call raises or doesn't
    finish in time. Each call gets its own thread (rather than a shared pool)
    so a permanently-hung call can't exhaust a pool and block later calls.
    """
    result_q: "queue.Queue" = queue.Queue(maxsize=1)
    name = label or getattr(fn, "__name__", repr(fn))

    def _run():
        try:
            result_q.put(("ok", fn(*args, **kwargs)))
        except Exception as e:
            result_q.put(("err", e))

    threading.Thread(target=_run, daemon=True).start()
    try:
        status, value = result_q.get(timeout=timeout)
    except queue.Empty:
        print(f"  [net] TIMEOUT: {name} did not return within {timeout}s — continuing without it", flush=True)
        return default

    if status == "err":
        print(f"  [net] ERROR: {name}: {value}", flush=True)
        return default
    return value
