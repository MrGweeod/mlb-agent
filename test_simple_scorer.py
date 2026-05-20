"""Quick test of simple scorer with sample data"""
from src.engine.simple_scorer import score_legs

# Sample legs with real database field names
test_legs = [
    {
        "player_name": "Test Player A",
        "stat": "hits",
        "direction": "over",
        "line": 0.5,
        "position": "SS",
        "coverage_vs_hand": 72.0,
        "coverage_overall": 68.0,
        "coverage_recent_10": 80.0,   # Hot streak (+8 delta)
        "pitcher_era": 5.2,           # Weak pitcher
        "pitcher_k9": 6.5,
        "lineup_consistency": 0.85,
    },
    {
        "player_name": "Test Player B",
        "stat": "strikeouts",
        "direction": "over",
        "line": 4.5,
        "position": "P",
        "coverage_vs_hand": None,
        "coverage_overall": 65.0,
        "coverage_recent_10": 60.0,   # Cold streak (-5 delta, not quite -15)
        "pitcher_era": None,
        "pitcher_k9": 11.2,           # High-K pitcher
        "lineup_consistency": 0.90,
    },
    {
        "player_name": "Test Player C",
        "stat": "hits",
        "direction": "under",
        "line": 0.5,
        "position": "RF",
        "coverage_vs_hand": 75.0,
        "coverage_overall": 70.0,
        "coverage_recent_10": 72.0,
        "pitcher_era": 2.8,           # Ace pitcher — under gets +5
        "pitcher_k9": 9.8,
        "lineup_consistency": 0.45,   # Platoon risk — penalty
    },
]

# Score all legs
scored = score_legs(test_legs)

# Display results
print("\nSCORING TEST RESULTS")
print("=" * 80)

for leg in scored:
    breakdown = leg["score_breakdown"]
    print(f"\nPlayer: {leg['player_name']}")
    print(f"Prop:   {leg['stat']} {leg['direction']} {leg['line']}")
    print(f"Score:  {breakdown['final_score']:.1f}  (base={breakdown['base_coverage']:.1f}, split={breakdown['used_split']})")

print("\n" + "=" * 80)
print("Expected approximate scores:")
print("  Player A (hot, weak pitcher, split):  ~84  (72+3+4+5)")
print("  Player B (cold < threshold, high-K):  ~70  (65+5)  [recent -5 delta < -15 threshold]")
print("  Player C (ace-under, platoon risk):   ~78  (75+3+5-5)")
print("\n✅ Test complete")
