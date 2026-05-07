"""
parlay_features.py — Feature extraction for parlay-level ML model.

Extracts features from mlb_parlay_recommendations_v2 + mlb_parlay_legs_v2
for use in training a future parlay-outcome ML model.
"""
from __future__ import annotations

import math

from src.utils.db import get_conn

_PITCHER_STATS = frozenset({"strikeouts", "inningsPitched", "hitsAllowed", "earnedRuns"})


def extract_parlay_features(parlay_id: int) -> dict:
    """
    Extract ML features for a single parlay.

    Args:
        parlay_id: Row id from mlb_parlay_recommendations_v2.

    Returns:
        Dict of features suitable for ML training, including 'outcome' as the
        target variable.
    """
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM mlb_parlay_recommendations_v2 WHERE id = %s",
        (parlay_id,),
    )
    parlay = dict(cur.fetchone())

    cur.execute(
        "SELECT * FROM mlb_parlay_legs_v2 WHERE parlay_id = %s",
        (parlay_id,),
    )
    legs = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    if not legs:
        return {}

    coverages = [l["coverage"] for l in legs if l.get("coverage") is not None]
    evs = [l["ev"] for l in legs if l.get("ev") is not None]

    def _mean(vals):
        return sum(vals) / len(vals) if vals else None

    def _std(vals):
        if len(vals) < 2:
            return 0.0
        m = _mean(vals)
        return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))

    # Same-game correlation risk
    game_ids = [l["game_id"] for l in legs if l.get("game_id") is not None]
    unique_games = len(set(game_ids))
    legs_same_game = len(game_ids) - unique_games

    num_overs = sum(1 for l in legs if (l.get("direction") or "").lower() == "over")
    num_unders = len(legs) - num_overs
    num_pitcher_props = sum(1 for l in legs if l.get("stat") in _PITCHER_STATS)
    num_batter_props = len(legs) - num_pitcher_props

    unique_players = len(set(l["player_id"] for l in legs if l.get("player_id")))
    diversity_score = unique_players / len(legs) if legs else 0.0
    correlation_risk = legs_same_game / len(legs) if legs else 0.0

    return {
        "parlay_id":          parlay_id,
        "avg_leg_coverage":   round(_mean(coverages), 4) if coverages else None,
        "min_leg_coverage":   round(min(coverages), 4) if coverages else None,
        "max_leg_coverage":   round(max(coverages), 4) if coverages else None,
        "std_leg_coverage":   round(_std(coverages), 4) if coverages else None,
        "avg_leg_ev":         round(_mean(evs), 4) if evs else None,
        "num_legs":           len(legs),
        "legs_same_game":     legs_same_game,
        "total_odds":         parlay["total_odds"],
        "has_strikeout_over": int(
            any(l.get("stat") == "strikeouts" and (l.get("direction") or "").lower() == "over" for l in legs)
        ),
        "has_hits_under": int(
            any(l.get("stat") == "hits" and (l.get("direction") or "").lower() == "under" for l in legs)
        ),
        "num_overs":          num_overs,
        "num_unders":         num_unders,
        "num_pitcher_props":  num_pitcher_props,
        "num_batter_props":   num_batter_props,
        "diversity_score":    round(diversity_score, 4),
        "correlation_risk":   round(correlation_risk, 4),
        "outcome":            parlay["outcome"],  # target variable
    }


def extract_all_parlay_features(
    min_date: str | None = None,
    outcome_filter: str | None = None,
) -> list[dict]:
    """
    Extract features for all parlays matching the filters.

    Args:
        min_date: Only parlays on or after this date ('YYYY-MM-DD').
        outcome_filter: Only parlays with this outcome ('won'/'lost'/'void').

    Returns:
        List of feature dicts, one per parlay.
    """
    conn = get_conn()
    cur = conn.cursor()

    where_clauses = []
    params: list = []
    if min_date:
        where_clauses.append("run_date >= %s")
        params.append(min_date)
    if outcome_filter:
        where_clauses.append("outcome = %s")
        params.append(outcome_filter)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    cur.execute(f"SELECT id FROM mlb_parlay_recommendations_v2 {where_sql} ORDER BY run_date", params)
    parlay_ids = [r["id"] for r in cur.fetchall()]
    cur.close()
    conn.close()

    print(f"[parlay_features] Extracting features for {len(parlay_ids)} parlay(s)...")
    return [extract_parlay_features(pid) for pid in parlay_ids]


def test_feature_extraction() -> None:
    """Test feature extraction on the most recent parlay in v2 table."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM mlb_parlay_recommendations_v2 ORDER BY created_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        print("[parlay_features] No parlays found in v2 table yet")
        return

    features = extract_parlay_features(row["id"])
    print("Feature extraction test:")
    for k, v in features.items():
        print(f"  {k}: {v}")
