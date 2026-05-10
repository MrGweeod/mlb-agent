"""
scripts/calibrate_model.py — Post-hoc calibration analysis and deployment.

Evaluates three recalibration strategies on top of the composite_score outputs
already stored in mlb_training_data (90K+ resolved samples):

  1. Platt Scaling   — isotonic regression on composite_score → P(hit)
  2. Beta Calibration — logistic regression on logit(composite_score)
  3. Stat-Specific   — per-stat isotonic regression

Picks the winner by Brier score, retrains on the full dataset, and saves:
  models/calibrator.pkl              (global strategies)
  models/stat_specific_calibrator.pkl (stat-specific strategy)
  models/calibration_integration.py  (copy-paste integration snippet)

Also prints a full before/after validation report.

Usage:
    cd /home/gweeod/mlb-agent
    python scripts/calibrate_model.py
"""
import os
import sys
import pickle

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import train_test_split

from src.utils.db import get_conn

# Output paths
MODELS_DIR = os.path.join(os.path.dirname(__file__), "../models")
CALIBRATION_DIR = os.path.join(MODELS_DIR, "calibration")
os.makedirs(CALIBRATION_DIR, exist_ok=True)

# Use non-interactive backend for matplotlib (no display required)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ── Phase 1: Load & Explore ───────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    print("=" * 70)
    print("PHASE 1: LOADING DATA")
    print("=" * 70)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            composite_score,
            result,
            stat,
            direction,
            opponent_adjustment,
            trend_score,
            game_date,
            coverage_pct
        FROM mlb_training_data
        WHERE result IN ('hit', 'miss')
          AND composite_score IS NOT NULL
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    df = pd.DataFrame([dict(r) for r in rows])

    df["hit"] = (df["result"] == "hit").astype(int)
    df["game_date"] = pd.to_datetime(df["game_date"])

    print(f"Loaded {len(df):,} samples")
    print(f"Actual hit rate:     {df['hit'].mean():.1%}")
    print(f"Average prediction:  {df['composite_score'].mean():.1f}%")
    print(f"Prediction std:      {df['composite_score'].std():.1f}%")
    print(f"Date range:          {df['game_date'].min().date()} → {df['game_date'].max().date()}")
    return df


def initial_analysis(df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("PHASE 1b: INITIAL CALIBRATION ANALYSIS")
    print("=" * 70)

    # Brier + log loss on full dataset
    brier = brier_score_loss(df["hit"], df["composite_score"] / 100)
    ll    = log_loss(df["hit"], df["composite_score"] / 100)
    print(f"\nBaseline Brier Score: {brier:.4f}")
    print(f"Baseline Log Loss:    {ll:.4f}")

    print("\n--- Hit Rate by Stat ---")
    stat_stats = df.groupby("stat")["hit"].agg(["count", "mean"]).sort_values("count", ascending=False)
    stat_stats.columns = ["count", "hit_rate"]
    print(stat_stats.to_string())

    print("\n--- Hit Rate by Direction ---")
    dir_stats = df.groupby("direction")["hit"].agg(["count", "mean"])
    dir_stats.columns = ["count", "hit_rate"]
    print(dir_stats.to_string())

    print("\n--- Prediction Distribution by Stat ---")
    pred_stats = df.groupby("stat")["composite_score"].agg(["count", "mean", "std"])
    print(pred_stats.sort_values("count", ascending=False).to_string())

    print("\n--- Hit Rate by Stat × Direction (top 10) ---")
    cross = df.groupby(["stat", "direction"])["hit"].agg(["count", "mean"])
    cross.columns = ["count", "hit_rate"]
    print(cross.sort_values("count", ascending=False).head(10).to_string())

    print("\n--- Temporal Analysis ---")
    df["week"] = df["game_date"].dt.to_period("W")
    weekly = df.groupby("week").agg(
        samples=("hit", "count"),
        hit_rate=("hit", "mean"),
        avg_pred=("composite_score", "mean"),
    )
    print("Last 8 weeks:")
    print(weekly.tail(8).to_string())

    cutoff = pd.Timestamp("2026-04-15")
    recent = df[df["game_date"] >= cutoff]
    old    = df[df["game_date"] <  cutoff]
    print(f"\nRecent (≥ Apr 15): {len(recent):,} samples | "
          f"hit rate {recent['hit'].mean():.1%} | avg pred {recent['composite_score'].mean():.1f}%")
    print(f"Older  (< Apr 15): {len(old):,}    samples | "
          f"hit rate {old['hit'].mean():.1%} | avg pred {old['composite_score'].mean():.1f}%")

    # Calibration curve plot (before recalibration)
    prob_true, prob_pred = calibration_curve(
        df["hit"], df["composite_score"] / 100, n_bins=10, strategy="quantile"
    )
    plt.figure(figsize=(10, 6))
    plt.plot([0, 1], [0, 1], "k--", label="Perfect Calibration", linewidth=2)
    plt.plot(prob_pred, prob_true, "s-", label=f"Current Model (Brier: {brier:.4f})", linewidth=2)
    plt.xlabel("Predicted Probability")
    plt.ylabel("Actual Probability")
    plt.title("Calibration Curve — Before Recalibration")
    plt.legend()
    plt.grid(True, alpha=0.3)
    out = os.path.join(CALIBRATION_DIR, "calibration_before.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {out}")


# ── Phase 2: Evaluate Strategies ─────────────────────────────────────────────

def evaluate_strategies(df: pd.DataFrame) -> dict:
    print("\n" + "=" * 70)
    print("PHASE 2: EVALUATING RECALIBRATION STRATEGIES")
    print("=" * 70)

    train_df, val_df = train_test_split(
        df, test_size=0.2, random_state=42, stratify=df["hit"]
    )
    print(f"\nTrain: {len(train_df):,}  |  Validation: {len(val_df):,}")

    val_df = val_df.copy()
    brier_before = brier_score_loss(val_df["hit"], val_df["composite_score"] / 100)

    results = {"Original": brier_before}
    val_predictions = {}

    # ── Strategy 1: Isotonic Regression (Platt Scaling variant) ──────────────
    print("\n--- Strategy 1: Isotonic Regression ---")
    iso_reg = IsotonicRegression(out_of_bounds="clip")
    iso_reg.fit(train_df["composite_score"] / 100, train_df["hit"])
    val_df["recal_isotonic"] = iso_reg.predict(val_df["composite_score"] / 100) * 100
    brier_iso = brier_score_loss(val_df["hit"], val_df["recal_isotonic"] / 100)
    results["Isotonic Regression"] = brier_iso
    val_predictions["Isotonic Regression"] = "recal_isotonic"
    print(f"  Brier Before: {brier_before:.4f}")
    print(f"  Brier After:  {brier_iso:.4f}  ({(brier_before - brier_iso) / brier_before * 100:+.1f}%)")

    # ── Strategy 2: Beta Calibration (logistic on logit) ─────────────────────
    print("\n--- Strategy 2: Beta Calibration (Logistic on Logit) ---")
    # Clip to avoid log(0)
    clipped_train = train_df["composite_score"].clip(0.1, 99.9)
    clipped_val   = val_df["composite_score"].clip(0.1, 99.9)

    train_logit = np.log(clipped_train / (100 - clipped_train)).values.reshape(-1, 1)
    val_logit   = np.log(clipped_val   / (100 - clipped_val)).values.reshape(-1, 1)

    beta_cal = LogisticRegression(max_iter=1000)
    beta_cal.fit(train_logit, train_df["hit"])
    val_df["recal_beta"] = beta_cal.predict_proba(val_logit)[:, 1] * 100
    brier_beta = brier_score_loss(val_df["hit"], val_df["recal_beta"] / 100)
    results["Beta Calibration"] = brier_beta
    val_predictions["Beta Calibration"] = "recal_beta"
    print(f"  Brier Before: {brier_before:.4f}")
    print(f"  Brier After:  {brier_beta:.4f}  ({(brier_before - brier_beta) / brier_before * 100:+.1f}%)")

    # ── Strategy 3: Stat-Specific Isotonic ───────────────────────────────────
    print("\n--- Strategy 3: Stat-Specific Calibration ---")
    stat_calibrators: dict = {}
    val_df["recal_stat_specific"] = val_df["composite_score"].copy()

    # Identify stats with enough training samples
    stat_counts = train_df.groupby("stat").size()
    eligible_stats = stat_counts[stat_counts >= 100].index.tolist()
    print(f"  Eligible stats (≥100 train samples): {eligible_stats}")

    for stat in eligible_stats:
        stat_train = train_df[train_df["stat"] == stat]
        stat_val   = val_df[val_df["stat"] == stat]
        if len(stat_val) == 0:
            continue
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(stat_train["composite_score"] / 100, stat_train["hit"])
        stat_calibrators[stat] = iso
        val_df.loc[val_df["stat"] == stat, "recal_stat_specific"] = (
            iso.predict(stat_val["composite_score"] / 100) * 100
        )
        n_train_stat = len(stat_train)
        n_val_stat   = len(stat_val)
        print(f"    {stat:<20}: train={n_train_stat:,}  val={n_val_stat:,}")

    brier_stat = brier_score_loss(val_df["hit"], val_df["recal_stat_specific"] / 100)
    results["Stat-Specific"] = brier_stat
    val_predictions["Stat-Specific"] = "recal_stat_specific"
    print(f"  Brier Before: {brier_before:.4f}")
    print(f"  Brier After:  {brier_stat:.4f}  ({(brier_before - brier_stat) / brier_before * 100:+.1f}%)")

    # ── Comparison table ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STRATEGY COMPARISON (lower Brier score = better)")
    print("=" * 60)
    sorted_results = sorted(results.items(), key=lambda x: x[1])
    for name, score in sorted_results:
        improvement = (brier_before - score) / brier_before * 100 if name != "Original" else 0
        print(f"  {name:<28} Brier: {score:.4f}  ({improvement:+.1f}%)")
    print("=" * 60)

    best_strategy = sorted_results[0][0]
    print(f"\n  BEST STRATEGY: {best_strategy}")

    # ── Calibration comparison plot ───────────────────────────────────────────
    plt.figure(figsize=(12, 8))
    plt.plot([0, 1], [0, 1], "k--", label="Perfect Calibration", linewidth=2)

    # Original
    pt_orig, pp_orig = calibration_curve(val_df["hit"], val_df["composite_score"] / 100, n_bins=10)
    plt.plot(pp_orig, pt_orig, "o-",
             label=f"Original (Brier: {brier_before:.4f})", linewidth=2)

    # Isotonic
    pt_iso, pp_iso = calibration_curve(val_df["hit"], val_df["recal_isotonic"] / 100, n_bins=10)
    plt.plot(pp_iso, pt_iso, "s-",
             label=f"Isotonic (Brier: {brier_iso:.4f})", linewidth=2)

    # Beta
    pt_beta, pp_beta = calibration_curve(val_df["hit"], val_df["recal_beta"] / 100, n_bins=10)
    plt.plot(pp_beta, pt_beta, "^-",
             label=f"Beta Calibration (Brier: {brier_beta:.4f})", linewidth=2)

    # Stat-Specific
    pt_stat, pp_stat = calibration_curve(val_df["hit"], val_df["recal_stat_specific"] / 100, n_bins=10)
    plt.plot(pp_stat, pt_stat, "d-",
             label=f"Stat-Specific (Brier: {brier_stat:.4f})", linewidth=2)

    plt.xlabel("Predicted Probability", fontsize=12)
    plt.ylabel("Actual Probability", fontsize=12)
    plt.title("Calibration Curve Comparison — All Strategies", fontsize=14)
    plt.legend(fontsize=10)
    plt.grid(True, alpha=0.3)
    out = os.path.join(CALIBRATION_DIR, "calibration_comparison.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {out}")

    return {
        "best_strategy":    best_strategy,
        "brier_before":     brier_before,
        "results":          results,
        "stat_calibrators": stat_calibrators,
        "eligible_stats":   eligible_stats,
        "val_df":           val_df,
    }


# ── Phase 3: Retrain on Full Dataset ─────────────────────────────────────────

def retrain_final(df: pd.DataFrame, analysis: dict) -> tuple:
    best = analysis["best_strategy"]
    print("\n" + "=" * 70)
    print(f"PHASE 3: RETRAINING {best.upper()} ON FULL DATASET")
    print("=" * 70)

    final_calibrator = None

    if best == "Isotonic Regression":
        final_calibrator = IsotonicRegression(out_of_bounds="clip")
        final_calibrator.fit(df["composite_score"] / 100, df["hit"])
        calibrator_path = os.path.join(CALIBRATION_DIR, "calibrator.pkl")
        with open(calibrator_path, "wb") as f:
            pickle.dump({"type": "isotonic", "calibrator": final_calibrator}, f)
        print(f"  Saved isotonic calibrator → {calibrator_path}")

    elif best == "Beta Calibration":
        clipped = df["composite_score"].clip(0.1, 99.9)
        logit   = np.log(clipped / (100 - clipped)).values.reshape(-1, 1)
        final_calibrator = LogisticRegression(max_iter=1000)
        final_calibrator.fit(logit, df["hit"])
        calibrator_path = os.path.join(CALIBRATION_DIR, "calibrator.pkl")
        with open(calibrator_path, "wb") as f:
            pickle.dump({"type": "beta", "calibrator": final_calibrator}, f)
        print(f"  Saved beta calibrator → {calibrator_path}")

    elif best == "Stat-Specific":
        stat_calibrators: dict = {}
        for stat in df["stat"].unique():
            stat_df = df[df["stat"] == stat]
            if len(stat_df) < 100:
                continue
            iso = IsotonicRegression(out_of_bounds="clip")
            iso.fit(stat_df["composite_score"] / 100, stat_df["hit"])
            stat_calibrators[stat] = iso
            print(f"    Trained calibrator for {stat:<20}: {len(stat_df):,} samples")
        final_calibrator = stat_calibrators
        calibrator_path = os.path.join(CALIBRATION_DIR, "stat_specific_calibrator.pkl")
        with open(calibrator_path, "wb") as f:
            pickle.dump({"type": "stat_specific", "calibrator": final_calibrator}, f)
        print(f"  Saved stat-specific calibrators → {calibrator_path}")

    else:
        print(f"  Original model wins — no calibrator needed (Brier already optimal).")
        calibrator_path = None

    return final_calibrator, calibrator_path


# ── Phase 4: Integration Code ─────────────────────────────────────────────────

def generate_integration_code(best_strategy: str, calibrator_path: str) -> str:
    print("\n" + "=" * 70)
    print("PHASE 4: INTEGRATION CODE")
    print("=" * 70)

    if best_strategy == "Isotonic Regression":
        apply_fn = """\
    \"\"\"Apply isotonic calibration to composite_score (0–100) → calibrated score (0–100).\"\"\"
    cal = CALIBRATOR["calibrator"]
    return float(cal.predict([composite_score / 100])[0]) * 100"""

    elif best_strategy == "Beta Calibration":
        apply_fn = """\
    \"\"\"Apply beta (logistic on logit) calibration to composite_score (0–100).\"\"\"
    import numpy as np
    cal = CALIBRATOR["calibrator"]
    clipped = max(0.1, min(99.9, composite_score))
    logit = np.log(clipped / (100 - clipped))
    return float(cal.predict_proba([[logit]])[0][1]) * 100"""

    elif best_strategy == "Stat-Specific":
        apply_fn = """\
    \"\"\"Apply stat-specific isotonic calibration; falls back to identity for unknown stats.\"\"\"
    calibrators = CALIBRATOR["calibrator"]
    if stat in calibrators:
        return float(calibrators[stat].predict([composite_score / 100])[0]) * 100
    return composite_score  # unknown stat — pass through unchanged"""

    else:
        apply_fn = """\
    \"\"\"No calibration needed — original model is well-calibrated.\"\"\"
    return composite_score"""

    code = f'''\
# ── Calibration integration for src/engine/ml_leg_scorer.py ──────────────────
# Strategy: {best_strategy}
# Generated by: scripts/calibrate_model.py
# Calibrator:   {calibrator_path}

import pickle

# Load once at module level (alongside the main model load)
with open("{calibrator_path}", "rb") as _f:
    CALIBRATOR = pickle.load(_f)


def apply_calibration(composite_score: float, stat: str = None) -> float:
{apply_fn}


# ── Usage in score_legs_ml() ─────────────────────────────────────────────────
# After setting leg["composite_score"] = round(float(p) * 100, 2), add:
#
#   leg["composite_score"] = round(
#       apply_calibration(leg["composite_score"], leg.get("stat")), 2
#   )
'''

    integration_path = os.path.join(CALIBRATION_DIR, "calibration_integration.py")
    with open(integration_path, "w") as f:
        f.write(code)

    print(code)
    print(f"Saved: {integration_path}")
    return code


# ── Phase 5: Validation Report ────────────────────────────────────────────────

def validation_report(df: pd.DataFrame, final_calibrator, best_strategy: str) -> None:
    print("\n" + "=" * 80)
    print("PHASE 5: CALIBRATION VALIDATION REPORT")
    print("=" * 80)

    df = df.copy()

    # Apply best calibrator to full dataset
    if best_strategy == "Isotonic Regression":
        cal = final_calibrator if isinstance(final_calibrator, IsotonicRegression) \
              else final_calibrator["calibrator"]
        df["calibrated_score"] = cal.predict(df["composite_score"] / 100) * 100

    elif best_strategy == "Beta Calibration":
        cal = final_calibrator if not isinstance(final_calibrator, dict) \
              else final_calibrator["calibrator"]
        clipped = df["composite_score"].clip(0.1, 99.9)
        logit = np.log(clipped / (100 - clipped)).values.reshape(-1, 1)
        df["calibrated_score"] = cal.predict_proba(logit)[:, 1] * 100

    elif best_strategy == "Stat-Specific":
        calibrators = final_calibrator if isinstance(final_calibrator, dict) \
                      and "calibrator" not in final_calibrator \
                      else final_calibrator.get("calibrator", final_calibrator)
        df["calibrated_score"] = df["composite_score"].copy()
        for stat, iso in calibrators.items():
            mask = df["stat"] == stat
            if mask.sum() > 0:
                df.loc[mask, "calibrated_score"] = (
                    iso.predict(df.loc[mask, "composite_score"] / 100) * 100
                )
    else:
        df["calibrated_score"] = df["composite_score"].copy()

    # Overall metrics
    brier_before = brier_score_loss(df["hit"], df["composite_score"] / 100)
    brier_after  = brier_score_loss(df["hit"], df["calibrated_score"] / 100)
    ll_before    = log_loss(df["hit"], df["composite_score"] / 100)
    ll_after     = log_loss(df["hit"], df["calibrated_score"] / 100)

    print(f"\nOVERALL METRICS:")
    print(f"  Brier Score Before:    {brier_before:.4f}")
    print(f"  Brier Score After:     {brier_after:.4f}  "
          f"({(brier_before - brier_after) / brier_before * 100:+.1f}%)")
    print(f"  Log Loss Before:       {ll_before:.4f}")
    print(f"  Log Loss After:        {ll_after:.4f}  "
          f"({(ll_before - ll_after) / ll_before * 100:+.1f}%)")
    print(f"  Avg Prediction Before: {df['composite_score'].mean():.1f}%")
    print(f"  Avg Prediction After:  {df['calibrated_score'].mean():.1f}%")
    print(f"  Actual Hit Rate:       {df['hit'].mean() * 100:.1f}%")

    # Bucket-level comparison
    print(f"\n{'CALIBRATION BY PREDICTION BUCKET':}")
    print("-" * 85)
    print(f"{'Bucket':<12} {'Samples':>8} {'Before':>12} {'After':>12} {'Actual':>8} {'Δ Error':>10}")
    print("-" * 85)

    for bucket_start in range(30, 90, 5):
        bucket_end = bucket_start + 5
        mask = (df["composite_score"] >= bucket_start) & (df["composite_score"] < bucket_end)
        if mask.sum() < 30:
            continue
        before_pred = df.loc[mask, "composite_score"].mean()
        after_pred  = df.loc[mask, "calibrated_score"].mean()
        actual      = df.loc[mask, "hit"].mean() * 100
        before_err  = abs(before_pred - actual)
        after_err   = abs(after_pred  - actual)
        delta       = before_err - after_err  # positive = improvement

        print(f"  {bucket_start}-{bucket_end}%"
              f"{mask.sum():>10,}"
              f"   {before_pred:>5.1f}% ({before_err:+.1f})"
              f"   {after_pred:>5.1f}% ({after_err:+.1f})"
              f"   {actual:>5.1f}%"
              f"   {delta:>+6.1f}pp")

    print("-" * 85)

    # Per-stat breakdown
    print(f"\nCALIBRATION BY STAT:")
    print("-" * 70)
    print(f"  {'Stat':<20} {'N':>6} {'Before Brier':>14} {'After Brier':>13} {'Δ':>8}")
    print("-" * 70)
    for stat in sorted(df["stat"].unique()):
        mask = df["stat"] == stat
        if mask.sum() < 50:
            continue
        b_b = brier_score_loss(df.loc[mask, "hit"], df.loc[mask, "composite_score"] / 100)
        b_a = brier_score_loss(df.loc[mask, "hit"], df.loc[mask, "calibrated_score"] / 100)
        delta = (b_b - b_a) / b_b * 100
        print(f"  {stat:<20} {mask.sum():>6,}   {b_b:.4f}          {b_a:.4f}    {delta:>+.1f}%")
    print("-" * 70)

    # Final recommendation
    improvement_pct = (brier_before - brier_after) / brier_before * 100
    print(f"\nRECOMMENDATION:")
    if improvement_pct >= 5.0:
        print(f"  DEPLOY — Brier improvement {improvement_pct:.1f}% ≥ 5% threshold. "
              f"Calibrator is beneficial.")
    elif improvement_pct >= 2.0:
        print(f"  DEPLOY WITH MONITORING — Brier improvement {improvement_pct:.1f}%. "
              f"Marginal gain; watch live calibration.")
    else:
        print(f"  DO NOT DEPLOY — Brier improvement only {improvement_pct:.1f}% < 2% threshold. "
              f"Collect more data first (current model is already well-calibrated).")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    df       = load_data()
    initial_analysis(df)
    analysis = evaluate_strategies(df)

    best = analysis["best_strategy"]
    if best == "Original":
        print("\nOriginal model wins — no recalibration needed.")
        return

    final_calibrator, calibrator_path = retrain_final(df, analysis)

    if calibrator_path:
        generate_integration_code(best, calibrator_path)

    validation_report(df, final_calibrator, best)

    print("\n" + "=" * 80)
    print("DONE. Deliverables:")
    print(f"  Calibrator:    {calibrator_path}")
    print(f"  Integration:   {os.path.join(CALIBRATION_DIR, 'calibration_integration.py')}")
    print(f"  Plots:         {CALIBRATION_DIR}/calibration_*.png")
    print("=" * 80)


if __name__ == "__main__":
    main()
