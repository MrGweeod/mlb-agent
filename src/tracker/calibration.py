"""
calibration.py — Model performance and calibration report.

Answers the core question: are the model's predictions actually accurate?

Metrics:
  - Leg hit rate: what % of recommended legs actually won
  - Parlay hit rate: what % of recommended parlays hit
  - Bayes calibration: does P(over)=0.65 actually win ~65%?
  - Bayes vs coverage: is P(over) more predictive than historical coverage %?
  - EV accuracy: do positive-EV legs win more than negative-EV legs?

Run standalone:  python -m src.tracker.calibration
"""
from __future__ import annotations

import math
from src.utils.db import get_conn


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_resolved_legs() -> list[dict]:
    """All recommendation legs with known outcomes (won or lost)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT rl.*, r.date
        FROM mlb_recommendation_legs rl
        JOIN mlb_recommendations r ON rl.recommendation_id = r.id
        WHERE rl.result IN ('won', 'lost')
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def _load_resolved_parlays() -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM mlb_recommendations WHERE status IN ('won', 'lost')"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


# ── Metrics ───────────────────────────────────────────────────────────────────

def _brier_score(legs: list[dict], prob_key: str) -> float | None:
    """Mean squared error between predicted probability and binary outcome."""
    scored = [l for l in legs if l.get(prob_key) is not None]
    if not scored:
        return None
    return sum((l[prob_key] - (1 if l["result"] == "won" else 0)) ** 2 for l in scored) / len(scored)


def _calibration_buckets(legs: list[dict], prob_key: str, n_buckets: int = 5) -> list[dict]:
    """
    Split legs into equal-width probability buckets and compute actual win rate per bucket.
    Returns list of {low, high, predicted_mid, actual_rate, count}.
    """
    scored = [l for l in legs if l.get(prob_key) is not None]
    if not scored:
        return []

    width = 1.0 / n_buckets
    buckets = []
    for i in range(n_buckets):
        low = i * width
        high = low + width
        bucket_legs = [l for l in scored if low <= l[prob_key] < high]
        if not bucket_legs:
            continue
        actual_rate = sum(1 for l in bucket_legs if l["result"] == "won") / len(bucket_legs)
        predicted_mid = sum(l[prob_key] for l in bucket_legs) / len(bucket_legs)
        buckets.append({
            "range": f"{low:.0%}–{high:.0%}",
            "predicted_avg": predicted_mid,
            "actual_rate": actual_rate,
            "count": len(bucket_legs),
        })
    return buckets


# ── Report ────────────────────────────────────────────────────────────────────

def print_calibration_report() -> None:
    legs = _load_resolved_legs()
    parlays = _load_resolved_parlays()

    print("\n" + "=" * 56)
    print("  MODEL CALIBRATION REPORT")
    print("=" * 56)

    if not legs:
        print("\n  No resolved legs yet — run the outcome resolver after games complete.")
        print("=" * 56)
        return

    # ── Overall leg hit rate ─────────────────────────────────────────────────
    wins = sum(1 for l in legs if l["result"] == "won")
    print(f"\n  Legs resolved : {len(legs)}")
    print(f"  Leg hit rate  : {wins}/{len(legs)} = {wins/len(legs):.1%}")

    # ── Parlay hit rate ──────────────────────────────────────────────────────
    if parlays:
        p_wins = sum(1 for p in parlays if p["status"] == "won")
        print(f"  Parlay hit rate: {p_wins}/{len(parlays)} = {p_wins/len(parlays):.1%}")

    # ── Bayes vs coverage Brier scores ───────────────────────────────────────
    bayes_legs = [l for l in legs if l.get("p_over") is not None]
    brier_bayes = _brier_score(legs, "p_over")
    brier_cov = _brier_score(
        [{**l, "_cov_prob": l["coverage_pct"] / 100} for l in legs if l.get("coverage_pct") is not None],
        "_cov_prob"
    )

    print(f"\n  {'Predictor':<22} {'Brier Score':>12}  (lower = better)")
    print(f"  {'-'*40}")
    if brier_bayes is not None:
        print(f"  {'Bayesian P(over)':<22} {brier_bayes:>12.4f}  (n={len(bayes_legs)})")
    if brier_cov is not None:
        cov_legs = [l for l in legs if l.get("coverage_pct") is not None]
        print(f"  {'Historical coverage %':<22} {brier_cov:>12.4f}  (n={len(cov_legs)})")
    if brier_bayes and brier_cov:
        improvement = (brier_cov - brier_bayes) / brier_cov * 100
        better = "Bayes" if brier_bayes < brier_cov else "Coverage"
        print(f"\n  → {better} is better by {abs(improvement):.1f}%")

    # ── Bayes calibration by bucket ──────────────────────────────────────────
    if bayes_legs:
        print(f"\n  Bayesian calibration (P(over) buckets):")
        print(f"  {'Range':<10} {'Predicted':>10} {'Actual':>10} {'Count':>7}  {'Gap':>8}")
        print(f"  {'-'*52}")
        for b in _calibration_buckets(bayes_legs, "p_over"):
            gap = b["actual_rate"] - b["predicted_avg"]
            flag = " ← overconfident" if gap < -0.08 else (" ← underconfident" if gap > 0.08 else "")
            print(f"  {b['range']:<10} {b['predicted_avg']:>9.1%} {b['actual_rate']:>10.1%} "
                  f"{b['count']:>7}  {gap:>+8.1%}{flag}")

    # ── EV accuracy ──────────────────────────────────────────────────────────
    ev_legs = [l for l in legs if l.get("ev_per_unit") is not None]
    if ev_legs:
        pos_ev = [l for l in ev_legs if l["ev_per_unit"] > 0]
        neg_ev = [l for l in ev_legs if l["ev_per_unit"] <= 0]
        pos_wins = sum(1 for l in pos_ev if l["result"] == "won") if pos_ev else 0
        neg_wins = sum(1 for l in neg_ev if l["result"] == "won") if neg_ev else 0
        print(f"\n  EV accuracy:")
        if pos_ev:
            print(f"    Positive EV legs : {pos_wins}/{len(pos_ev)} won = {pos_wins/len(pos_ev):.1%}")
        if neg_ev:
            print(f"    Negative EV legs : {neg_wins}/{len(neg_ev)} won = {neg_wins/len(neg_ev):.1%}")

    print("\n" + "=" * 56)


if __name__ == "__main__":
    print_calibration_report()
