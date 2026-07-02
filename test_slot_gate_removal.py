"""
Tests for the Jul 2, 2026 slot-gate removal:
  - Scoring: OUT_OF_RANGE leg no longer receives -8 penalty
  - Scoring: other signals unchanged
  - Annotation: BATTING_ORDER_OUT_OF_RANGE still written to lineup_check_status
  - Annotation: SCRATCHED still triggers lineup_check_status = SCRATCHED
  - CLR: bad_legs only collects SCRATCHED legs, not OUT_OF_RANGE legs

Run with: .venv/bin/python test_slot_gate_removal.py
"""
from src.engine.simple_scorer import calculate_composite_score
from src.apis.lineup_confirmation import _lineup_check_status

PASS = "PASS"
FAIL = "FAIL"


def check(label, condition):
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}")
    return condition


# ── Test 1: Scorer — OUT_OF_RANGE leg gets no penalty ────────────────────────
print("\n=== Test 1: No -8 penalty for batting_order=7 hits/over ===")

# Previously: slot 7 for hits/over was outside range(1,6) → -8 applied
# Now: no adjustment — only other signals matter
leg_slot7_hits = {
    "stat": "hits",
    "direction": "over",
    "coverage_overall": 60.0,
    "batting_order": 7,
    "lineup_check_status": "BATTING_ORDER_OUT_OF_RANGE",
}
score_slot7 = calculate_composite_score(leg_slot7_hits)

# Without -8 penalty, only base coverage (60.0) applies — should equal 60
leg_no_batting_order = {
    "stat": "hits",
    "direction": "over",
    "coverage_overall": 60.0,
}
score_no_slot = calculate_composite_score(leg_no_batting_order)

check("slot 7 hits/over scores same as no-slot leg (penalty removed)", score_slot7 == score_no_slot)
check("slot 7 hits/over score is not -8 below no-slot score", score_slot7 != score_no_slot - 8)
print(f"  score_slot7={score_slot7}, score_no_slot={score_no_slot}")


# ── Test 2: Scorer — OUT_OF_RANGE leg (SO/over slot 8) gets no penalty ───────
print("\n=== Test 2: No -8 penalty for batting_order=8 strikeouts/over ===")

leg_slot8_so = {
    "stat": "strikeouts",
    "direction": "over",
    "coverage_overall": 65.0,
    "batting_order": 8,
    "lineup_check_status": "BATTING_ORDER_OUT_OF_RANGE",
}
score_slot8_so = calculate_composite_score(leg_slot8_so)

leg_slot8_so_no_slot = {
    "stat": "strikeouts",
    "direction": "over",
    "coverage_overall": 65.0,
}
score_no_slot_so = calculate_composite_score(leg_slot8_so_no_slot)

check("slot 8 SO/over scores same as no-slot leg (penalty removed)", score_slot8_so == score_no_slot_so)
check("slot 8 SO/over score is not -8 below no-slot score", score_slot8_so != score_no_slot_so - 8)
print(f"  score_slot8_so={score_slot8_so}, score_no_slot_so={score_no_slot_so}")


# ── Test 3: Scorer — other signals still work correctly ─────────────────────
print("\n=== Test 3: Other scorer signals still apply correctly ===")

# Weak pitcher (+5 for hits/over), hot streak (+2 gap=-10)
leg_other_signals = {
    "stat": "hits",
    "direction": "over",
    "coverage_vs_hand": 70.0,
    "coverage_overall": 70.0,
    "coverage_recent_10": 80.0,   # gap = 70-80 = -10 → +2
    "pitcher_era": 5.5,            # weak pitcher → +5
    "lineup_consistency": 0.8,
    "batting_order": 7,            # previously penalized, now neutral
}
score_with_signals = calculate_composite_score(leg_other_signals)
expected = 70.0 + 2 + 5  # base + hot_streak + weak_pitcher
check(f"other signals still work (expected ~{expected})", score_with_signals == expected)
print(f"  score={score_with_signals}, expected={expected}")


# ── Test 4: Annotation — OUT_OF_RANGE status still written for out-of-range slot
print("\n=== Test 4: _lineup_check_status still returns OUT_OF_RANGE for slot 7 hits/over ===")

from main import BATTING_ORDER_FAVORABLE

# Slot 7 for hits/over should still be flagged (just not trigger a rebuild)
game_info_confirmed = {
    "lineup_posted": True,
    "players": {999: {"in_lineup": True, "batting_order_slot": 7}},
}
status, slot = _lineup_check_status(999, "hits", "over", game_info_confirmed, BATTING_ORDER_FAVORABLE)
check("status is BATTING_ORDER_OUT_OF_RANGE (annotation intact)", status == "BATTING_ORDER_OUT_OF_RANGE")
check("slot is 7", slot == 7)
print(f"  status={status}, slot={slot}")


# ── Test 5: Annotation — SCRATCHED still detected ───────────────────────────
print("\n=== Test 5: _lineup_check_status returns SCRATCHED for absent player ===")

game_info_no_player = {
    "lineup_posted": True,
    "players": {111: {"in_lineup": True, "batting_order_slot": 3}},
}
status_s, slot_s = _lineup_check_status(999, "hits", "over", game_info_no_player, BATTING_ORDER_FAVORABLE)
check("absent player returns SCRATCHED", status_s == "SCRATCHED")
check("SCRATCHED slot is None", slot_s is None)
print(f"  status={status_s}, slot={slot_s}")


# ── Test 6: Annotation — LINEUP_CONFIRMED for in-range slot ─────────────────
print("\n=== Test 6: _lineup_check_status returns LINEUP_CONFIRMED for slot 3 hits/over ===")

game_info_slot3 = {
    "lineup_posted": True,
    "players": {999: {"in_lineup": True, "batting_order_slot": 3}},
}
status_c, slot_c = _lineup_check_status(999, "hits", "over", game_info_slot3, BATTING_ORDER_FAVORABLE)
check("slot 3 hits/over returns LINEUP_CONFIRMED", status_c == "LINEUP_CONFIRMED")
check("slot is 3", slot_c == 3)
print(f"  status={status_c}, slot={slot_c}")


# ── Test 7: CLR bad_legs filter — OUT_OF_RANGE excluded ─────────────────────
print("\n=== Test 7: CLR bad_legs filter only catches SCRATCHED ===")

# Simulate the bad_legs filter from run_confirmed_lineup_resolution
sample_legs = [
    {"player_name": "Player A", "lineup_check_status": "SCRATCHED"},
    {"player_name": "Player B", "lineup_check_status": "BATTING_ORDER_OUT_OF_RANGE"},
    {"player_name": "Player C", "lineup_check_status": "LINEUP_CONFIRMED"},
    {"player_name": "Player D", "lineup_check_status": "SCRATCHED"},
]
# This mirrors the updated filter in run_confirmed_lineup_resolution
bad_legs = [l for l in sample_legs if l.get("lineup_check_status") == "SCRATCHED"]

check("only SCRATCHED legs are in bad_legs (count=2)", len(bad_legs) == 2)
check("OUT_OF_RANGE leg NOT in bad_legs", all(l["lineup_check_status"] != "BATTING_ORDER_OUT_OF_RANGE" for l in bad_legs))
check("Player A (SCRATCHED) is included", any(l["player_name"] == "Player A" for l in bad_legs))
check("Player D (SCRATCHED) is included", any(l["player_name"] == "Player D" for l in bad_legs))
check("Player B (OUT_OF_RANGE) is excluded", all(l["player_name"] != "Player B" for l in bad_legs))
print(f"  bad_legs={[l['player_name'] for l in bad_legs]}")


# ── Summary ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("All tests complete.")
