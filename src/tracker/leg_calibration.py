"""
leg_calibration.py — Full-pool calibration report from mlb_scored_legs.

Unlike calibration.py (which only covers parlay recommendation legs),
this reports on ALL scored legs including those that didn't make the cut.
This gives 300-400 resolved legs per day instead of 5-8 — enough for
meaningful calibration signals.

Queries:
  1. Coverage accuracy by bucket  — is coverage_pct well-calibrated?
  2. Prop type performance        — which stats are over/under-predicted?
  3. EV signal validation         — do positive-EV legs win more?
  4. Trend signal validation      — does trend_pass correlate with outcomes?

Run standalone:
    python -m src.tracker.leg_calibration

Or with a specific date:
    python -m src.tracker.leg_calibration 2026-04-19
"""
from __future__ import annotations

import sys
from src.utils.db import get_conn


def _load_scored_legs(run_dates: list[str] | str | None = None) -> list[dict]:
    """
    Load resolved scored legs, optionally filtered by run_date(s).

    Args:
        run_dates: A single date string, a list of date strings, or None for all dates.
    """
    conn = get_conn()
    cur = conn.cursor()
    if run_dates:
        if isinstance(run_dates, str):
            run_dates = [run_dates]
        placeholders = ", ".join(["%s"] * len(run_dates))
        cur.execute(
            f"""
            SELECT * FROM mlb_scored_legs
            WHERE result IN ('won', 'lost')
              AND run_date IN ({placeholders})
            ORDER BY run_date, id
            """,
            run_dates,
        )
    else:
        cur.execute(
            """
            SELECT * FROM mlb_scored_legs
            WHERE result IN ('won', 'lost')
            ORDER BY run_date, id
            """
        )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def _predicted_win_prob(leg: dict) -> float | None:
    """
    Return the model's predicted win probability for this leg.

    coverage_pct stores P(over) as a percentage. For an "over" leg, the
    predicted win probability IS coverage_pct / 100. For an "under" leg,
    the predicted win probability is 1 - coverage_pct / 100.
    """
    cov = leg.get("coverage_pct")
    if cov is None:
        return None
    p_over = cov / 100.0
    return p_over if leg.get("direction", "over") == "over" else 1.0 - p_over


def _coverage_by_bucket(legs: list[dict]) -> None:
    """
    Print coverage calibration by predicted-win-probability bucket.

    Uses direction-adjusted win probability so over and under legs are
    treated correctly: for 'over', pred_win = coverage_pct/100;
    for 'under', pred_win = 1 - coverage_pct/100.
    """
    cov_legs = [(l, _predicted_win_prob(l)) for l in legs]
    cov_legs = [(l, p) for l, p in cov_legs if p is not None]
    if not cov_legs:
        print("  No coverage_pct data available.")
        return

    buckets = [
        ("<50%",  0.00, 0.50),
        ("50-55%", 0.50, 0.55),
        ("55-60%", 0.55, 0.60),
        ("60-65%", 0.60, 0.65),
        ("65-70%", 0.65, 0.70),
        ("70%+",   0.70, 1.01),
    ]

    print(f"\n  {'Bucket':<10} {'Predicted':>10} {'Actual':>10} {'Count':>7}  {'Error':>9}")
    print(f"  {'-'*52}")
    for label, low, high in buckets:
        bucket = [(l, p) for l, p in cov_legs if low <= p < high]
        if not bucket:
            continue
        predicted_avg = sum(p for _, p in bucket) / len(bucket) * 100
        actual = sum(1 for l, _ in bucket if l["result"] == "won") / len(bucket) * 100
        error = predicted_avg - actual
        flag = " ← OVERCONFIDENT" if error > 5 else (" ← underconfident" if error < -5 else "")
        print(f"  {label:<10} {predicted_avg:>9.1f}% {actual:>9.1f}% {len(bucket):>7}  {error:>+8.1f}%{flag}")


def _prop_type_performance(legs: list[dict]) -> None:
    """
    Print hit rate vs predicted win probability by prop stat type.

    Uses direction-adjusted win probability so over and under legs compare
    fairly — a 'strikeouts over 0.5' at coverage_pct=60 predicts 60% win,
    while 'strikeouts under 0.5' at the same coverage_pct predicts 40% win.
    Separates over and under so the overconfidence signal is not diluted.
    """
    from collections import defaultdict

    by_stat: dict[str, list] = defaultdict(list)
    for l in legs:
        stat = l.get("stat", "unknown")
        by_stat[stat].append(l)

    # Show over legs only — these are what the model scores (coverage_pct = P(over))
    over_only = {s: [l for l in ls if l.get("direction", "over") == "over"]
                 for s, ls in by_stat.items()}

    print(f"\n  {'Stat':<14} {'Pred (over)':>12} {'Actual':>10} {'Count':>7}  {'Error':>9}")
    print(f"  {'-'*58}")
    for stat in sorted(over_only):
        stat_legs = [l for l in over_only[stat] if l.get("coverage_pct") is not None]
        if not stat_legs:
            continue
        predicted = sum(l["coverage_pct"] for l in stat_legs) / len(stat_legs)
        actual = sum(1 for l in stat_legs if l["result"] == "won") / len(stat_legs) * 100
        error = predicted - actual
        flag = " ← OVERCONFIDENT" if error > 5 else (" ← underconfident" if error < -5 else "")
        print(f"  {stat:<14} {predicted:>11.1f}% {actual:>9.1f}% {len(stat_legs):>7}  {error:>+8.1f}%{flag}")


def _ev_signal_validation(legs: list[dict]) -> None:
    """Print hit rate by EV bucket — positive EV should win more."""
    ev_legs = [l for l in legs if l.get("ev_per_unit") is not None]
    if not ev_legs:
        print("  No ev_per_unit data available.")
        return

    buckets = [
        ("Strong -EV (<-10%)",   None,  -0.10),
        ("Weak -EV (-10% to 0%)", -0.10, 0.0),
        ("Weak +EV (0% to 10%)",  0.0,   0.10),
        ("Strong +EV (>10%)",     0.10,  None),
    ]

    print(f"\n  {'EV Bucket':<26} {'Hit Rate':>9} {'Count':>7}")
    print(f"  {'-'*46}")
    for label, low, high in buckets:
        if low is None:
            bucket = [l for l in ev_legs if l["ev_per_unit"] <= high]
        elif high is None:
            bucket = [l for l in ev_legs if l["ev_per_unit"] > low]
        else:
            bucket = [l for l in ev_legs if low < l["ev_per_unit"] <= high]
        if not bucket:
            continue
        hit_rate = sum(1 for l in bucket if l["result"] == "won") / len(bucket)
        print(f"  {label:<26} {hit_rate:>9.1%} {len(bucket):>7}")

    # Check direction of signal
    strong_pos = [l for l in ev_legs if l["ev_per_unit"] > 0.10]
    strong_neg = [l for l in ev_legs if l["ev_per_unit"] <= -0.10]
    if strong_pos and strong_neg:
        pos_rate = sum(1 for l in strong_pos if l["result"] == "won") / len(strong_pos)
        neg_rate = sum(1 for l in strong_neg if l["result"] == "won") / len(strong_neg)
        if pos_rate > neg_rate:
            print(f"\n  ✓ EV signal is CORRECT: strong +EV hits at {pos_rate:.1%} vs {neg_rate:.1%}")
        else:
            print(f"\n  ✗ EV signal is INVERTED: strong +EV hits at {pos_rate:.1%} vs {neg_rate:.1%}")


def _trend_signal_validation(legs: list[dict]) -> None:
    """Print hit rate by trend_pass — should correlate if trend has signal."""
    trend_legs = [l for l in legs if l.get("trend_pass") is not None]
    if not trend_legs:
        print("  No trend_pass data available.")
        return

    pass_legs = [l for l in trend_legs if l["trend_pass"]]
    fail_legs = [l for l in trend_legs if not l["trend_pass"]]

    print(f"\n  {'Trend':<16} {'Hit Rate':>9} {'Count':>7}")
    print(f"  {'-'*36}")
    if pass_legs:
        rate = sum(1 for l in pass_legs if l["result"] == "won") / len(pass_legs)
        print(f"  {'Passing':<16} {rate:>9.1%} {len(pass_legs):>7}")
    if fail_legs:
        rate = sum(1 for l in fail_legs if l["result"] == "won") / len(fail_legs)
        print(f"  {'Failing':<16} {rate:>9.1%} {len(fail_legs):>7}")

    if pass_legs and fail_legs:
        pass_rate = sum(1 for l in pass_legs if l["result"] == "won") / len(pass_legs)
        fail_rate = sum(1 for l in fail_legs if l["result"] == "won") / len(fail_legs)
        diff = pass_rate - fail_rate
        if abs(diff) < 0.03:
            print(f"\n  ✗ Trend signal has NO predictive value ({diff:+.1%} gap)")
        elif diff > 0:
            print(f"\n  ✓ Trend signal is predictive ({diff:+.1%} passing vs failing)")
        else:
            print(f"\n  ✗ Trend signal is INVERTED ({diff:+.1%} gap)")


def print_leg_calibration_report(run_dates: list[str] | str | None = None) -> None:
    """Run all four calibration queries and print a health-check report."""
    legs = _load_scored_legs(run_dates)

    if isinstance(run_dates, list):
        date_label = ", ".join(run_dates)
    else:
        date_label = run_dates or "all dates"
    print("\n" + "=" * 60)
    print(f"  SCORED-LEG CALIBRATION REPORT  ({date_label})")
    print("=" * 60)

    if not legs:
        print("\n  No resolved scored legs found.")
        if run_dates:
            print(f"  (run outcome_resolver.py for {date_label} first)")
        print("=" * 60)
        return

    wins = sum(1 for l in legs if l["result"] == "won")
    print(f"\n  Legs resolved : {len(legs)}")
    print(f"  Overall hit rate : {wins}/{len(legs)} = {wins/len(legs):.1%}")

    print("\n  — 1. COVERAGE ACCURACY BY BUCKET —")
    _coverage_by_bucket(legs)

    print("\n  — 2. PROP TYPE PERFORMANCE —")
    _prop_type_performance(legs)

    print("\n  — 3. EV SIGNAL VALIDATION —")
    _ev_signal_validation(legs)

    print("\n  — 4. TREND SIGNAL VALIDATION —")
    _trend_signal_validation(legs)

    print("\n" + "=" * 60)


if __name__ == "__main__":
    # Usage:
    #   python -m src.tracker.leg_calibration                    # all resolved legs
    #   python -m src.tracker.leg_calibration 2026-04-17         # one date
    #   python -m src.tracker.leg_calibration 2026-04-17 2026-04-18  # multiple dates
    args = sys.argv[1:]
    print_leg_calibration_report(args if args else None)
