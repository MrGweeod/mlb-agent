"""
Test dynamic rank normalization in _calculate_enriched_score().
Ensures rank adjustments scale with the actual pitcher pool size (192 entries),
not the old hardcoded midpoint of 15.5.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.engine.enriched_scorer import _calculate_enriched_score

# Build a mock pitcher_ranks dict with 192 entries (rank 1 through 192)
pitcher_ranks = {i: {"era_rank": i, "k9_rank": i, "whip_rank": i} for i in range(1, 193)}

POOL_SIZE = 192
MIDPOINT = (POOL_SIZE + 1) / 2.0  # 96.5


def make_leg(stat: str, direction: str, era_rank: int, k9_rank: int, whip_rank: int) -> dict:
    return {
        "stat": stat,
        "direction": direction,
        "coverage_overall": 60.0,
        "coverage_pct": 60.0,
        "best_line": 0.5,
        "player_id": None,
        "pitcher_id": None,
        "opp_pitcher_era_rank": era_rank,
        "opp_pitcher_k9_rank": k9_rank,
        "opp_pitcher_whip_rank": whip_rank,
    }


def call(stat, direction, era_rank, k9_rank, whip_rank):
    leg = make_leg(stat, direction, era_rank, k9_rank, whip_rank)
    result = _calculate_enriched_score(
        leg=leg,
        season=2026,
        pitcher_ranks=pitcher_ranks,
        ballpark_factors={},
        opp_team_id=None,
        home_team_abbr=None,
    )
    return result


print("=" * 60)
print(f"Pool size: {POOL_SIZE}, midpoint: {MIDPOINT}")
print("=" * 60)

# ── hits/over ──────────────────────────────────────────────────────────────────
r1_hits_over   = call("hits", "over",  era_rank=1,   k9_rank=1,   whip_rank=1)
r96_hits_over  = call("hits", "over",  era_rank=96,  k9_rank=96,  whip_rank=96)
r192_hits_over = call("hits", "over",  era_rank=192, k9_rank=192, whip_rank=192)

print("\nhits/over:")
print(f"  rank-1   era_adj={r1_hits_over['era_adj']:+.1f}  k9_adj={r1_hits_over['k9_adj']:+.1f}  whip_adj={r1_hits_over['whip_adj']:+.1f}")
print(f"  rank-96  era_adj={r96_hits_over['era_adj']:+.1f}  k9_adj={r96_hits_over['k9_adj']:+.1f}  whip_adj={r96_hits_over['whip_adj']:+.1f}")
print(f"  rank-192 era_adj={r192_hits_over['era_adj']:+.1f}  k9_adj={r192_hits_over['k9_adj']:+.1f}  whip_adj={r192_hits_over['whip_adj']:+.1f}")

# ── hits/under ─────────────────────────────────────────────────────────────────
r1_hits_under   = call("hits", "under", era_rank=1,   k9_rank=1,   whip_rank=1)
r192_hits_under = call("hits", "under", era_rank=192, k9_rank=192, whip_rank=192)

print("\nhits/under:")
print(f"  rank-1   era_adj={r1_hits_under['era_adj']:+.1f}  k9_adj={r1_hits_under['k9_adj']:+.1f}  whip_adj={r1_hits_under['whip_adj']:+.1f}")
print(f"  rank-192 era_adj={r192_hits_under['era_adj']:+.1f}  k9_adj={r192_hits_under['k9_adj']:+.1f}  whip_adj={r192_hits_under['whip_adj']:+.1f}")

# ── strikeouts/over ────────────────────────────────────────────────────────────
r1_so_over   = call("strikeouts", "over", era_rank=1,   k9_rank=1,   whip_rank=1)
r96_so_over  = call("strikeouts", "over", era_rank=96,  k9_rank=96,  whip_rank=96)
r192_so_over = call("strikeouts", "over", era_rank=192, k9_rank=192, whip_rank=192)

print("\nstrikeouts/over:")
print(f"  rank-1   k9_adj={r1_so_over['k9_adj']:+.1f}")
print(f"  rank-96  k9_adj={r96_so_over['k9_adj']:+.1f}")
print(f"  rank-192 k9_adj={r192_so_over['k9_adj']:+.1f}")

print("\n" + "=" * 60)
print("ASSERTIONS")
print("=" * 60)

# rank-1 (elite pitcher) → negative era_adj for hits/over
assert r1_hits_over["era_adj"] < 0, (
    f"rank-1 era_adj should be negative (elite pitcher), got {r1_hits_over['era_adj']}"
)

# rank-192 (weak pitcher) → positive era_adj for hits/over
assert r192_hits_over["era_adj"] > 0, (
    f"rank-192 era_adj should be positive (weak pitcher), got {r192_hits_over['era_adj']}"
)

# rank-96 (midpoint) should be near zero — not hitting the cap
assert abs(r96_hits_over["era_adj"]) < 2.0, (
    f"rank-96 era_adj should be near 0 (midpoint), not capped. Got {r96_hits_over['era_adj']}"
)
assert abs(r96_hits_over["k9_adj"]) < 2.0, (
    f"rank-96 k9_adj should be near 0 (midpoint), not capped. Got {r96_hits_over['k9_adj']}"
)
assert abs(r96_hits_over["whip_adj"]) < 2.0, (
    f"rank-96 whip_adj should be near 0 (midpoint), not capped. Got {r96_hits_over['whip_adj']}"
)

# rank-1 era_adj for hits/over should be at or near -2.0 (extreme end of 192-pool)
assert r1_hits_over["era_adj"] <= -1.9, (
    f"rank-1 era_adj should be at/near -2.0 cap (best pitcher in 192-pool), got {r1_hits_over['era_adj']}"
)

# rank-192 era_adj for hits/over should hit the cap (worst pitcher)
assert r192_hits_over["era_adj"] >= 2.0, (
    f"rank-192 era_adj should hit +2.0 cap (worst pitcher), got {r192_hits_over['era_adj']}"
)

# Key proof of fix: with old hardcoded 15.5 midpoint, rank-96 would have been capped at +2.0.
# With dynamic midpoint (96.5), rank-96 should be near 0.
assert abs(r96_hits_over["era_adj"]) < 0.1, (
    f"rank-96 era_adj should be ~0 with dynamic midpoint, got {r96_hits_over['era_adj']} "
    f"(old hardcoded formula would have returned +2.0)"
)

# SO/over: rank-1 (elite K pitcher) → strongly negative k9_adj
assert r1_so_over["k9_adj"] < 0, (
    f"rank-1 k9_adj for SO/over should be negative (elite K pitcher), got {r1_so_over['k9_adj']}"
)
assert r192_so_over["k9_adj"] > 0, (
    f"rank-192 k9_adj for SO/over should be positive (weak K pitcher), got {r192_so_over['k9_adj']}"
)
assert abs(r96_so_over["k9_adj"]) < 5.0, (
    f"rank-96 k9_adj for SO/over should be near 0, not at cap. Got {r96_so_over['k9_adj']}"
)

print("All assertions passed.")
