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

_HERE            = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH       = os.path.join(_HERE, "../../models/leg_scorer_v2.pkl")
CALIBRATOR_PATH  = os.path.join(_HERE, "../../models/stat_specific_calibrator.pkl")

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

class CalibratedModel:
    """
    Platt-scaled wrapper around a pre-trained GradientBoostingClassifier.

    Defined at module level here (not in train_ml_model.py) so pickle can
    locate the class when loading the saved model — pickle stores the fully-
    qualified class path, which must resolve at load time.
    """
    def __init__(self, base_model, calibrator):
        self.base_model = base_model
        self.calibrator = calibrator

    def predict_proba(self, X):
        base_probs = self.base_model.predict_proba(X)[:, 1].reshape(-1, 1)
        calibrated = self.calibrator.predict_proba(base_probs)[:, 1]
        return np.column_stack([1 - calibrated, calibrated])

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


_cached: dict | None = None
_calibrator: dict | None = None


class _CompatUnpickler(pickle.Unpickler):
    """
    Redirect __main__.CalibratedModel → src.engine.ml_leg_scorer.CalibratedModel.

    The model was saved while train_ml_model.py was running as __main__, so
    pickle stored the class as __main__.CalibratedModel.  At inference time
    __main__ is server.py (or whatever entry point is used), which doesn't have
    the class.  This shim intercepts that lookup and returns the correct class.
    """
    def find_class(self, module: str, name: str):
        if name == "CalibratedModel":
            return CalibratedModel
        return super().find_class(module, name)


def _compat_load(file_obj):
    return _CompatUnpickler(file_obj).load()


def _load_calibrator() -> dict:
    global _calibrator
    if _calibrator is not None:
        return _calibrator
    path = os.path.abspath(CALIBRATOR_PATH)
    if not os.path.exists(path):
        print(f"  [ml_scorer] WARNING: calibrator not found at {path}, skipping calibration")
        _calibrator = {}
        return _calibrator
    with open(path, "rb") as f:
        _calibrator = pickle.load(f)
    stat_count = len(_calibrator.get("calibrator", {}))
    print(f"  [ml_scorer] Calibrator loaded with {stat_count} stat types from {path}")
    return _calibrator


def apply_calibration(composite_score: float, stat: str = "") -> float:
    """Apply stat-specific isotonic calibration; falls back to identity for unknown stats."""
    cal = _load_calibrator()
    calibrators = cal.get("calibrator", {})
    if stat in calibrators:
        return round(float(calibrators[stat].predict([composite_score / 100])[0]) * 100, 2)
    return composite_score


def apply_temporary_scoring_adjustments(scored_legs: list[dict]) -> list[dict]:
    """
    Three-part temporary fix until model retraining (May 11, 2026).

    Based on diagnostic analysis of 124 parlays (4,400 legs):

    1. Direction bias: Unders overscored by 26pp, overs underscored by 18pp
       - Root cause: Model overfit to direction feature (77% importance)
       - Data: Unders score 66.9% avg but win 40.7%, overs score 40.3% but win 58.9%

    2. Odds signal: Long-odds props contain market information model doesn't capture
       - Root cause: Model assigns same score to +100 and +160 props
       - Data: Selected unders +155 avg odds (29.4% win), rejected unders +107 (39.5% win)
       - Only penalize unders - overs at long odds perform well (70.2% win rate)

    3. Same-game bias: Multiple props from same game overscored
       - Root cause: Calibrator not accounting for correlation
       - Data: Same-game legs 69.2% score → 41.7% win, isolated 64.7% → 46.1% win

    Remove this function after:
    - Direction-split calibrator deployed (14 calibrators: 7 stats × 2 directions)
    - Base model retrained with balanced direction sampling + odds as feature

    Args:
        scored_legs: List of leg dicts with composite_score already populated

    Returns:
        scored_legs: Same list with adjusted composite_scores
    """
    # Count game frequencies for same-game adjustment
    game_counts: dict = {}
    for leg in scored_legs:
        game_key = (leg.get("team", ""), leg.get("run_date", ""))
        game_counts[game_key] = game_counts.get(game_key, 0) + 1

    adjusted_count = 0
    direction_adjustments: list[float] = []
    odds_adjustments: list[float] = []
    game_adjustments: list[float] = []

    for leg in scored_legs:
        original_score = leg.get("composite_score", 0)
        adjusted_score = original_score

        direction = leg.get("direction", "").lower()
        odds = leg.get("odds", 0)
        game_key = (leg.get("team", ""), leg.get("run_date", ""))

        # Convert odds from TEXT to int for numeric comparisons
        # (Database stores odds as TEXT: '-110', '+150', etc.)
        if isinstance(odds, str):
            try:
                odds = int(odds)
            except (ValueError, TypeError):
                odds = 0

        # Adjustment #1: Direction bias
        if direction == "over":
            adjusted_score = min(adjusted_score + 18, 95)
            direction_adjustments.append(+18)
        elif direction == "under":
            adjusted_score = max(adjusted_score - 26, 5)
            direction_adjustments.append(-26)

        # Adjustment #2: Odds signal (only for unders - overs perform well at all odds)
        if direction == "under":
            if odds >= 150:
                adjusted_score = max(adjusted_score - 15, 5)
                odds_adjustments.append(-15)
            elif odds >= 120:
                adjusted_score = max(adjusted_score - 8, 5)
                odds_adjustments.append(-8)

        # Adjustment #3: Same-game bias
        if game_counts[game_key] >= 2:
            adjusted_score = max(adjusted_score - 20, 5)
            game_adjustments.append(-20)

        if adjusted_score != original_score:
            leg["composite_score"] = round(adjusted_score, 2)
            adjusted_count += 1

    print(f"  [ml_scorer] Applied temporary adjustments to {adjusted_count}/{len(scored_legs)} legs")
    if direction_adjustments:
        avg_dir = sum(direction_adjustments) / len(direction_adjustments)
        n_over = len([x for x in direction_adjustments if x > 0])
        n_under = len([x for x in direction_adjustments if x < 0])
        print(f"    Direction: avg {avg_dir:+.1f}pp ({n_over} overs boosted, {n_under} unders penalized)")
    if odds_adjustments:
        print(f"    Odds signal: {len(odds_adjustments)} long-odds unders penalized")
    if game_adjustments:
        print(f"    Same-game: {len(game_adjustments)} legs from concentrated games penalized")

    return scored_legs


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
        _cached = _compat_load(f)
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
        # pitcher_quality scale (from batter's perspective):
        #   0-30:  Elite pitcher (ERA < 2.5) - bad matchup for batter
        #   30-70: Average pitcher (ERA 2.5-4.5)
        #   70-100: Poor pitcher (ERA 4.5-6.0+) - good matchup for batter
        pitcher_id  = leg.get("pitcher_id")
        pitcher_era = leg.get("pitcher_era")
        if pitcher_id is not None and pitcher_era is not None and float(pitcher_era) > 0:
            pitcher_quality = max(0.0, min(100.0, ((float(pitcher_era) - 2.0) / 4.0) * 100))
            print(f"  [ml_debug] player={leg.get('player_name')}, pitcher_era={float(pitcher_era):.2f}, pitcher_quality={pitcher_quality:.1f}")
        else:
            pitcher_quality = 50.0
        opponent_offense   = 0.0

    line      = float(leg.get("line") or leg.get("best_line") or 0.5)
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
    if not legs:
        return legs
    try:
        saved = _load_model()
        print(f"  [ml_scorer] Loaded model from {os.path.abspath(MODEL_PATH)}")
        X     = np.array([_extract_features(leg) for leg in legs], dtype=np.float32)
        probs = saved["model"].predict_proba(X)[:, 1]
        for leg, p in zip(legs, probs):
            leg["composite_score"] = round(float(p) * 100, 2)
            leg["composite_score"] = apply_calibration(
                leg["composite_score"], leg.get("stat", "")
            )
        scores = [leg["composite_score"] for leg in legs]
        print(
            f"  [ml_scorer] Scored {len(legs)} legs | "
            f"avg={sum(scores)/len(scores):.1f} | "
            f"min={min(scores):.1f} | max={max(scores):.1f}"
        )
        apply_temporary_scoring_adjustments(legs)
    except FileNotFoundError as exc:
        print(f"  [ml_scorer] ERROR: {exc}")
        for leg in legs:
            leg.setdefault("composite_score", 50.0)
    except Exception as exc:
        print(f"  [ml_scorer] Batch scoring failed ({exc}); falling back per-leg")
        saved = _load_model()
        failures = 0
        for leg in legs:
            try:
                features = np.array([_extract_features(leg)], dtype=np.float32)
                p = float(saved["model"].predict_proba(features)[0, 1])
                leg["composite_score"] = apply_calibration(
                    round(p * 100, 2), leg.get("stat", "")
                )
            except Exception:
                leg.setdefault("composite_score", 50.0)
                failures += 1
        if failures:
            print(f"  [ml_scorer] {failures} legs fell back to composite_score=50.0")
        apply_temporary_scoring_adjustments(legs)
    return legs
