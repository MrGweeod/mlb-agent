"""
src/engine/ml_scorer.py — ML-based leg scoring using gradient boosting.

Trains on mlb_training_data (49,222 calibrated samples) to predict P(hit).
The model is trained once, saved to models/leg_scorer_v1.pkl, and loaded
at prediction time — no DB connection required after training.

Feature set (all available in the calibrated training subset):
  Numeric (5):
    coverage_pct          — heuristic Bayesian coverage (0-100)
    composite_score       — current weighted heuristic score (0-100)
    opponent_adjustment   — pitcher quality adjustment (-1 to +1)
    trend_score           — recent form score (-2 to +5)
    pa_last_10            — plate appearances / IP in last 10 games
    line                  — prop line value

  Categorical (encoded):
    direction             — binary (over=1, under=0)
    stat                  — one-hot across all stat categories

Usage:
    # Train:
    python -m src.engine.ml_scorer --retrain

    # Predict at inference time:
    from src.engine.ml_scorer import score_legs_ml
    legs = score_legs_ml(legs)  # adds ml_hit_probability to each leg
"""
from __future__ import annotations

import argparse
import os
import pickle

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_HERE, "../../models/leg_scorer_v1.pkl")

# All stat values present in training data, in a fixed order for one-hot encoding.
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
]

_NUMERIC_FEATURES = [
    "coverage_pct",
    "composite_score",
    "opponent_adjustment",
    "trend_score",
    "pa_last_10",
    "line",
]

_FEATURE_NAMES = _NUMERIC_FEATURES + ["direction"] + _STAT_CATEGORIES


# ── Feature extraction ────────────────────────────────────────────────────────

def _extract_features(row: dict) -> list[float]:
    """
    Convert a row dict (from DB or pipeline leg dict) into a flat feature vector.

    Numeric features are imputed with their training-set medians on missing values:
      coverage_pct        → 26.3  (training median)
      composite_score     → 33.0
      opponent_adjustment → 0.0
      trend_score         → 0.5
      pa_last_10          → 3.4
      line                → 0.5

    direction is binary (over=1, under=0).
    stat is one-hot over _STAT_CATEGORIES (unknown stats → all zeros).
    """
    def _f(key, default):
        v = row.get(key)
        return float(v) if v is not None else float(default)

    numeric = [
        _f("coverage_pct", 26.3),
        _f("composite_score", 33.0),
        _f("opponent_adjustment", 0.0),
        _f("trend_score", 0.5),
        _f("pa_last_10", 3.4),
        _f("line", 0.5),
    ]

    direction = 1.0 if row.get("direction") == "over" else 0.0

    stat = row.get("stat", "")
    stat_oh = [1.0 if stat == cat else 0.0 for cat in _STAT_CATEGORIES]

    return numeric + [direction] + stat_oh


# ── Training ──────────────────────────────────────────────────────────────────

def train_model(retrain: bool = False) -> None:
    """
    Fetch training data from mlb_training_data and train a GradientBoostingClassifier.

    Only rows with composite_score IS NOT NULL and result IN ('hit','miss') are used
    (49,222 samples). Features with <1% null rate are median-imputed.

    Saves the fitted model + metadata to models/leg_scorer_v1.pkl.

    Args:
        retrain: If False and the model file already exists, skip training.
    """
    model_path = os.path.abspath(MODEL_PATH)

    if os.path.exists(model_path) and not retrain:
        print(f"[ml_scorer] Model already exists at {model_path}")
        print("  Pass --retrain to force retraining.")
        return

    # Lazy import — only needed at training time
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report, roc_auc_score
    from sklearn.calibration import CalibratedClassifierCV

    from src.utils.db import get_conn

    print("[ml_scorer] Fetching training data from mlb_training_data...")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            coverage_pct,
            composite_score,
            opponent_adjustment,
            trend_score,
            pa_last_10,
            line,
            direction,
            stat,
            result
        FROM mlb_training_data
        WHERE composite_score IS NOT NULL
          AND result IN ('hit', 'miss')
        ORDER BY id
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    print(f"[ml_scorer] Loaded {len(rows):,} training samples")

    X = np.array([_extract_features(dict(r)) for r in rows], dtype=np.float32)
    y = np.array([1 if r["result"] == "hit" else 0 for r in rows], dtype=np.int8)

    hit_pct = 100.0 * y.mean()
    print(f"[ml_scorer] Feature matrix: {X.shape}  |  "
          f"hits: {y.sum():,} / {len(y):,} = {hit_pct:.1f}%")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    print("\n[ml_scorer] Training GradientBoostingClassifier...")
    base = GradientBoostingClassifier(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=4,
        subsample=0.8,
        min_samples_leaf=50,
        random_state=42,
        verbose=1,
    )
    # Isotonic calibration wraps the GBC to produce reliable P(hit) estimates
    model = CalibratedClassifierCV(base, cv=3, method="isotonic")
    model.fit(X_train, y_train)

    # ── Evaluation ────────────────────────────────────────────────────────────
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_prob)

    print("\n=== Model Evaluation ===")
    print(classification_report(y_test, y_pred, target_names=["miss", "hit"]))
    print(f"ROC AUC: {auc:.4f}")

    # Feature importances from the underlying GBC estimators (averaged across folds)
    importances = np.zeros(len(_FEATURE_NAMES))
    for cal in model.calibrated_classifiers_:
        importances += cal.estimator.feature_importances_
    importances /= len(model.calibrated_classifiers_)

    print("\nFeature importances (top 10):")
    ranked = sorted(zip(_FEATURE_NAMES, importances), key=lambda x: x[1], reverse=True)
    for name, imp in ranked[:10]:
        print(f"  {name:<22}: {imp:.4f}")

    # ── Save ─────────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    payload = {
        "model":          model,
        "feature_names":  _FEATURE_NAMES,
        "stat_categories": _STAT_CATEGORIES,
        "auc":            round(auc, 4),
        "n_train":        len(X_train),
        "hit_rate":       round(float(hit_pct), 2),
    }
    with open(model_path, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

    size_kb = os.path.getsize(model_path) / 1024
    print(f"\n[ml_scorer] Model saved → {model_path}  ({size_kb:.0f} KB)")
    print(f"  AUC={auc:.4f}  n_train={len(X_train):,}  hit_rate={hit_pct:.1f}%")


# ── Inference ─────────────────────────────────────────────────────────────────

_cached: dict | None = None  # module-level cache so we load the pkl once per process


def _load_model() -> dict:
    global _cached
    if _cached is not None:
        return _cached
    model_path = os.path.abspath(MODEL_PATH)
    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"ML model not found at {model_path}. "
            "Run: python -m src.engine.ml_scorer --retrain"
        )
    with open(model_path, "rb") as f:
        _cached = pickle.load(f)
    return _cached


def predict_hit_probability(leg: dict) -> float:
    """
    Return P(hit) for one leg using the trained ML model.

    Accepts both pipeline leg dicts (keys: coverage_pct, composite_score, …)
    and training-data row dicts — field names are identical.

    Returns:
        float in [0.0, 1.0]
    """
    saved = _load_model()
    features = np.array([_extract_features(leg)], dtype=np.float32)
    prob = float(saved["model"].predict_proba(features)[0, 1])
    return prob


def score_legs_ml(legs: list[dict]) -> list[dict]:
    """
    Add ``ml_hit_probability`` to every leg in-place.

    Failures for individual legs fall back to 0.5 (neutral) so the pipeline
    is never blocked by a single bad leg.

    Returns the same list (mutated).
    """
    try:
        saved = _load_model()
        X = np.array([_extract_features(leg) for leg in legs], dtype=np.float32)
        probs = saved["model"].predict_proba(X)[:, 1]
        for leg, p in zip(legs, probs):
            leg["ml_hit_probability"] = round(float(p), 4)
    except FileNotFoundError:
        # Model not trained yet — skip silently, callers can check for the key
        for leg in legs:
            leg.setdefault("ml_hit_probability", None)
    except Exception as exc:
        print(f"[ml_scorer] Warning: batch ML scoring failed ({exc}); falling back per-leg")
        for leg in legs:
            try:
                leg["ml_hit_probability"] = round(predict_hit_probability(leg), 4)
            except Exception:
                leg["ml_hit_probability"] = 0.5
    return legs


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Train the MLB leg-scoring ML model on mlb_training_data."
    )
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="Force retraining even if models/leg_scorer_v1.pkl already exists.",
    )
    args = parser.parse_args()
    train_model(retrain=args.retrain)
