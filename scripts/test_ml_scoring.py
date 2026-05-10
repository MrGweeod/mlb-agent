"""Test full ML scoring pipeline with calibration."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.engine.ml_leg_scorer import score_legs_ml

sample_legs = [
    {
        "player_id": "12345",
        "player_name": "Test Hitter",
        "stat": "hits",
        "line": 0.5,
        "direction": "over",
        "odds": -110,
        "coverage_pct": 55.0,
    },
    {
        "player_id": "67890",
        "player_name": "Test Pitcher",
        "stat": "strikeouts",
        "line": 5.5,
        "direction": "over",
        "odds": -115,
        "coverage_pct": 60.0,
    },
    {
        "player_id": "11111",
        "player_name": "Power Hitter",
        "stat": "homeRuns",
        "line": 0.5,
        "direction": "over",
        "odds": +140,
        "coverage_pct": 35.0,
    },
]

print("Scoring sample legs with calibration...")
scored = score_legs_ml(sample_legs)

print()
for leg in scored:
    print(f"{leg['player_name']:<20} {leg['stat']:<15} {leg.get('composite_score', 'N/A'):.1f}%")

print("\n✓ ML scoring test complete")
