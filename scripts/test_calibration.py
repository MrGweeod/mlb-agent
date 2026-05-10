"""Quick smoke-test for the stat-specific calibrator."""
import pickle, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CAL_PATH = os.path.join(os.path.dirname(__file__), "../models/stat_specific_calibrator.pkl")

print("Loading calibrator...")
with open(CAL_PATH, "rb") as f:
    cal = pickle.load(f)

calibrators = cal.get("calibrator", {})
print(f"Calibrator contains {len(calibrators)} stat types:")
for stat in sorted(calibrators.keys()):
    print(f"  - {stat}")

test_cases = [
    ("hits", 50.0),
    ("strikeouts", 60.0),
    ("totalBases", 45.0),
    ("homeRuns", 30.0),
    ("stolenBases", 40.0),
]

print("\nCalibration output:")
for stat, raw in test_cases:
    if stat in calibrators:
        cal_val = float(calibrators[stat].predict([raw / 100])[0]) * 100
        print(f"  {stat:<15} {raw:.1f}% → {cal_val:.1f}%")
    else:
        print(f"  {stat:<15} not in calibrator (passthrough {raw:.1f}%)")

print("\n✓ Calibration test complete")
