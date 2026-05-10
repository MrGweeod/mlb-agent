"""Compare original vs calibrated scores against actual outcomes."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.utils.db import get_conn as get_connection
from src.engine.ml_leg_scorer import score_legs_ml

conn = get_connection()
cur = conn.cursor()

cur.execute("""
    SELECT
        player_id, player_name, stat, line, direction, odds,
        coverage_pct,
        composite_score AS original_score, result
    FROM mlb_training_data
    WHERE game_date = '2026-05-09'
      AND result IN ('hit', 'miss')
    LIMIT 30
""")
rows = cur.fetchall()
cur.close()
conn.close()

if not rows:
    print("No rows found for 2026-05-09 — trying most recent resolved rows...")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT player_id, player_name, stat, line, direction, odds,
               coverage_pct,
               composite_score AS original_score, result
        FROM mlb_training_data
        WHERE result IN ('hit', 'miss')
        ORDER BY game_date DESC
        LIMIT 30
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

if not rows:
    print("No resolved rows found.")
    sys.exit(1)

legs = [dict(r) for r in rows]
original_scores = [l["original_score"] for l in legs]
results_bin = [1 if l["result"] == "hit" else 0 for l in legs]

# Re-score with calibration (score_legs_ml uses calibrator now)
rescored = score_legs_ml([dict(l) for l in legs])
calibrated_scores = [l["composite_score"] for l in rescored]

print(f"\n{'Player':<22} {'Stat':<14} {'Orig':>6} {'Cal':>6} {'Result'}")
print("-" * 65)
for orig, cal_leg, res in zip(legs, rescored, results_bin):
    print(
        f"{orig['player_name'][:21]:<22} "
        f"{orig['stat']:<14} "
        f"{orig['original_score']:>5.1f}% "
        f"{cal_leg['composite_score']:>5.1f}%  "
        f"{'HIT' if res else 'miss'}"
    )

print("-" * 65)
print(f"\nOriginal avg:    {sum(original_scores)/len(original_scores):.1f}%")
print(f"Calibrated avg:  {sum(calibrated_scores)/len(calibrated_scores):.1f}%")
print(f"Actual hit rate: {sum(results_bin)/len(results_bin)*100:.1f}%")
print(f"\nSample size: {len(legs)} legs")
print("✓ Validation complete")
