"""
scripts/train_ml_model.py — Train ML leg scorer v2 on mlb_training_data.

Trains on ALL resolved samples (result IN ('hit','miss'), ~76K rows) using
the new coverage-based feature set introduced April 29, 2026.

Feature set (17 features):
  Numeric (7):
    coverage_overall   — full-season base rate (= coverage_pct in training data)
    coverage_vs_hand   — hitters: coverage_pct proxy; pitchers: 0.0
    coverage_recent_10 — hitters: coverage_pct * 0.9 proxy; pitchers: 0.0
    coverage_recent_5  — pitchers: coverage_pct * 0.95 proxy; hitters: 0.0
    pitcher_quality    — pitchers: 50.0 (no rank in training table); hitters: 0.0
    opponent_offense   — pitchers: 50.0 (no rank in training table); hitters: 0.0
    line               — prop line value

  Categorical (encoded):
    direction          — binary (over=1, under=0)
    stat               — one-hot across _STAT_CATEGORIES

Output: models/leg_scorer_v2.pkl

Usage:
    python scripts/train_ml_model.py
    python scripts/train_ml_model.py --retrain   # force even if v2 already exists
"""
import argparse
import os
import pickle
import sys

# Allow running from the project root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

MODEL_PATH = os.path.join(os.path.dirname(__file__), "../models/leg_scorer_v2.pkl")

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

_FEATURE_NAMES = [
    "coverage_overall",
    "coverage_vs_hand",
    "coverage_recent_10",
    "coverage_recent_5",
    "pitcher_quality",
    "opponent_offense",
    "line",
    "direction",
] + _STAT_CATEGORIES


def _extract_features(row: dict) -> list[float]:
    """
    Build feature vector from a training-data row or live pipeline leg dict.

    Training-data rows (mlb_training_data) only have coverage_pct, so proxies
    are applied. Live inference uses the actual coverage fields computed by
    coverage.py and leg_scorer.py.
    """
    stat        = row.get("stat", "")
    is_pitcher  = stat in _PITCHER_STATS
    cov_pct     = float(row.get("coverage_pct") or 0.0)

    def _f(key, default):
        v = row.get(key)
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
    direction = 1.0 if row.get("direction") == "over" else 0.0
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


def train(retrain: bool = False) -> None:
    model_path = os.path.abspath(MODEL_PATH)

    if os.path.exists(model_path) and not retrain:
        print(f"[train_ml_model] Model already exists at {model_path}")
        print("  Pass --retrain to force retraining.")
        return

    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report, roc_auc_score

    from src.utils.db import get_conn

    print("[train_ml_model] Fetching training data from mlb_training_data...")
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT
            coverage_pct,
            line,
            direction,
            stat,
            result
        FROM mlb_training_data
        WHERE result IN ('hit', 'miss')
        ORDER BY id
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    print(f"[train_ml_model] Loaded {len(rows):,} training samples")

    X = np.array([_extract_features(dict(r)) for r in rows], dtype=np.float32)
    y = np.array([1 if r["result"] == "hit" else 0 for r in rows], dtype=np.int8)

    hit_pct = 100.0 * y.mean()
    print(
        f"[train_ml_model] Feature matrix: {X.shape}  |  "
        f"hits: {y.sum():,} / {len(y):,} = {hit_pct:.1f}%"
    )

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    print("\n[train_ml_model] Training GradientBoostingClassifier...")
    model = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.1,
        subsample=0.8,
        min_samples_leaf=30,
        random_state=42,
        verbose=1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    auc    = roc_auc_score(y_test, y_prob)

    print("\n=== Model Evaluation ===")
    print(classification_report(y_test, y_pred, target_names=["miss", "hit"]))
    print(f"ROC AUC: {auc:.4f}")

    importances = model.feature_importances_
    print("\nFeature importances (top 10):")
    ranked = sorted(zip(_FEATURE_NAMES, importances), key=lambda x: x[1], reverse=True)
    for name, imp in ranked[:10]:
        print(f"  {name:<22}: {imp:.4f}")

    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    payload = {
        "model":           model,
        "feature_names":   _FEATURE_NAMES,
        "stat_categories": _STAT_CATEGORIES,
        "auc":             round(auc, 4),
        "n_train":         len(X_train),
        "hit_rate":        round(float(hit_pct), 2),
    }
    with open(model_path, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

    size_kb = os.path.getsize(model_path) / 1024
    print(f"\n[train_ml_model] Model saved → {model_path}  ({size_kb:.0f} KB)")
    print(f"  AUC={auc:.4f}  n_train={len(X_train):,}  hit_rate={hit_pct:.1f}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Train MLB leg-scorer v2 on coverage-based features."
    )
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="Force retraining even if models/leg_scorer_v2.pkl already exists.",
    )
    args = parser.parse_args()
    train(retrain=args.retrain)
