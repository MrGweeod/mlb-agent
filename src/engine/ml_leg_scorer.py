"""
src/engine/ml_leg_scorer.py — ML-based leg scoring using the v2 model.

Loads models/leg_scorer_v2.pkl (trained by scripts/train_ml_model.py) and
scores legs using the new coverage-based feature set introduced April 29, 2026.

At inference time the real coverage fields computed by coverage.py are used:
  Hitters: coverage_overall, coverage_vs_hand, coverage_recent_10
  Pitchers: coverage_overall, coverage_recent_5, pitcher_quality, opponent_offense

Sets leg['composite_score'] = predicted P(hit) * 100  (0–100 scale).

Usage:
    from src.engine.ml_leg_scorer import score_legs_ml
    score_legs_ml(legs)   # mutates in-place, returns the list
"""
from __future__ import annotations

import os
import pickle

import numpy as np

_HERE       = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH  = os.path.join(_HERE, "../../models/leg_scorer_v2.pkl")

_PITCHER_STATS = frozenset({"inningsPitched", "hitsAllowed", "earnedRuns"})

_STAT_CATEGORIES = [
    "hits",
    "rbi",
    "walks",
    "totalBases",
    "strikeouts",
    "homeRuns",
    "stolenBases",
    "runsScored",
    "hitsAllowed",
    "earnedRuns",
    "inningsPitched",
]

_cached: dict | None = None


def _load_model() -> dict:
    global _cached
    if _cached is not None:
        return _cached
    path = os.path.abspath(MODEL_PATH)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"ML v2 model not found at {path}. "
            "Run: python scripts/train_ml_model.py"
        )
    with open(path, "rb") as f:
        _cached = pickle.load(f)
    return _cached


def _extract_features(leg: dict) -> list[float]:
    """
    Build feature vector from a live pipeline leg dict.

    Uses actual coverage fields when present; falls back to coverage_pct
    proxies for legs that pre-date the April 29 refactor.
    """
    stat       = leg.get("stat", "")
    is_pitcher = (
        stat in _PITCHER_STATS
        or leg.get("position", "") in {"SP", "RP", "P", "TWP"}
    )
    cov_pct = float(leg.get("coverage_pct") or 0.0)

    def _f(key, default):
        v = leg.get(key)
        return float(v) if v is not None else float(default)

    coverage_overall = _f("coverage_overall", cov_pct)

    if is_pitcher:
        coverage_vs_hand   = 0.0
        coverage_recent_10 = 0.0
        coverage_recent_5  = _f("coverage_recent_5",  cov_pct * 0.95)
        pitcher_quality    = _f("pitcher_quality",     50.0)
        opponent_offense   = _f("opponent_offense",    50.0)
    else:
        coverage_vs_hand   = _f("coverage_vs_hand",   cov_pct)
        coverage_recent_10 = _f("coverage_recent_10", cov_pct * 0.9)
        coverage_recent_5  = 0.0
        pitcher_quality    = 0.0
        opponent_offense   = 0.0

    line      = _f("line", 0.5)
    direction = 1.0 if leg.get("direction") == "over" else 0.0
    stat_oh   = [1.0 if stat == cat else 0.0 for cat in _STAT_CATEGORIES]

    return [
        coverage_overall,
        coverage_vs_hand,
        coverage_recent_10,
        coverage_recent_5,
        pitcher_quality,
        opponent_offense,
        line,
        direction,
    ] + stat_oh


def score_legs_ml(legs: list[dict]) -> list[dict]:
    """
    Set composite_score = P(hit) * 100 for every leg in-place.

    Falls back to composite_score=50.0 for individual legs that fail.
    Returns the same list (mutated).
    """
    try:
        saved = _load_model()
        X     = np.array([_extract_features(leg) for leg in legs], dtype=np.float32)
        probs = saved["model"].predict_proba(X)[:, 1]
        for leg, p in zip(legs, probs):
            leg["composite_score"] = round(float(p) * 100, 2)
    except FileNotFoundError as exc:
        print(f"[ml_leg_scorer] {exc}")
        for leg in legs:
            leg.setdefault("composite_score", 50.0)
    except Exception as exc:
        print(f"[ml_leg_scorer] Batch scoring failed ({exc}); falling back per-leg")
        saved = _load_model()
        for leg in legs:
            try:
                features = np.array([_extract_features(leg)], dtype=np.float32)
                p = float(saved["model"].predict_proba(features)[0, 1])
                leg["composite_score"] = round(p * 100, 2)
            except Exception:
                leg.setdefault("composite_score", 50.0)
    return legs
