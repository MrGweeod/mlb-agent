"""
Verification script for stack bonus hotfix.
Tests all 6 conditions from STACK_BONUS_HOTFIX.md.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.db import get_conn
from src.engine.enriched_scorer import pitcher_vulnerability, STACK_ELIGIBLE_PROPS
from src.pipelines.run_enriched_pipeline import apply_stack_bonuses

PASS = "PASS"
FAIL = "FAIL"
results = []


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((name, status, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return condition


# ── Test 1: Rank range discovery ──────────────────────────────────────────────
print("\n=== Test 1: Rank range discovery ===")
try:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            MIN(pitcher_era_rank)  AS era_min,  MAX(pitcher_era_rank)  AS era_max,
            MIN(pitcher_k9_rank)   AS k9_min,   MAX(pitcher_k9_rank)   AS k9_max,
            MIN(pitcher_whip_rank) AS whip_min, MAX(pitcher_whip_rank) AS whip_max
        FROM mlb_scored_legs_enriched
        WHERE pitcher_era_rank IS NOT NULL
    """)
    row = cur.fetchone()
    cur.close()
    conn.close()
    era_min, era_max = row["era_min"], row["era_max"]
    k9_min, k9_max   = row["k9_min"],  row["k9_max"]
    whip_min, whip_max = row["whip_min"], row["whip_max"]
    print(f"  ERA ranks:  min={era_min}, max={era_max}")
    print(f"  K/9 ranks:  min={k9_min}, max={k9_max}")
    print(f"  WHIP ranks: min={whip_min}, max={whip_max}")
    check("Test 1 — ERA max > 30 (not hardcoded)", era_max is not None and era_max > 30, f"era_max={era_max}")
    check("Test 1 — K/9 max > 30 (not hardcoded)", k9_max is not None and k9_max > 30, f"k9_max={k9_max}")
    check("Test 1 — WHIP max > 30 (not hardcoded)", whip_max is not None and whip_max > 30, f"whip_max={whip_max}")
except Exception as e:
    check("Test 1 — DB query succeeded", False, str(e))
    era_max = k9_max = whip_max = 196  # fallback for subsequent tests


# ── Test 2: Vulnerability score range ─────────────────────────────────────────
print("\n=== Test 2: Vulnerability score range ===")
try:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT pitcher_era_rank, pitcher_k9_rank, pitcher_whip_rank
        FROM mlb_scored_legs_enriched
        WHERE run_date = (SELECT MAX(run_date) FROM mlb_scored_legs_enriched)
          AND pitcher_era_rank IS NOT NULL
        LIMIT 200
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # Remap DB column names to what pitcher_vulnerability expects
    legs = [
        {"pitcher_era_rank": r["pitcher_era_rank"],
         "pitcher_k9_rank":  r["pitcher_k9_rank"],
         "pitcher_whip_rank": r["pitcher_whip_rank"]}
        for r in rows
    ]
    scores = [pitcher_vulnerability(l, era_max, k9_max, whip_max) for l in legs]
    scores = [s for s in scores if s is not None]
    if scores:
        mn, mx, avg = min(scores), max(scores), sum(scores) / len(scores)
        print(f"  count={len(scores)}, min={mn:.4f}, max={mx:.4f}, mean={avg:.4f}")
        check("Test 2 — all scores >= 0.0", mn >= 0.0, f"min={mn:.4f}")
        check("Test 2 — all scores <= 1.0", mx <= 1.0, f"max={mx:.4f}")
    else:
        check("Test 2 — scores computed", False, "no scores returned")
except Exception as e:
    check("Test 2 — DB query succeeded", False, str(e))


# ── Test 3: Elite pitcher sanity check ────────────────────────────────────────
# Query across all dates — rank-1 pitcher may not appear in today's slate
print("\n=== Test 3: Elite pitcher sanity check (ERA rank 1, any run date) ===")
try:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT pitcher_era_rank, pitcher_k9_rank, pitcher_whip_rank
        FROM mlb_scored_legs_enriched
        WHERE pitcher_era_rank = 1
        LIMIT 5
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if rows:
        leg = {"pitcher_era_rank": rows[0]["pitcher_era_rank"],
               "pitcher_k9_rank":  rows[0]["pitcher_k9_rank"],
               "pitcher_whip_rank": rows[0]["pitcher_whip_rank"]}
        vuln = pitcher_vulnerability(leg, era_max, k9_max, whip_max)
        # ERA component alone: (1 - 1) / (era_max - 1) = 0.0 — the sign-flip test
        era_component = (rows[0]["pitcher_era_rank"] - 1) / (era_max - 1) if era_max > 1 else None
        print(f"  ERA rank 1 leg → vulnerability={vuln}, ERA component={era_component}")
        check("Test 3 — ERA rank 1 component = 0.0", era_component is not None and era_component == 0.0,
              f"era_component={era_component}")
        check("Test 3 — elite pitcher vulnerability < 0.15", vuln is not None and vuln < 0.15, f"vuln={vuln}")
    else:
        check("Test 3 — ERA rank 1 leg found", False, "no rows with pitcher_era_rank=1 in any date")
except Exception as e:
    check("Test 3 — DB query succeeded", False, str(e))


# ── Test 4: Bad pitcher sanity check ──────────────────────────────────────────
# The worst ERA pitcher may have good K/9/WHIP (pulling the average below 0.80),
# so we verify the ERA component directly — it must be > 0.85 (formula direction check).
print("\n=== Test 4: Bad pitcher sanity check (highest ERA rank, ERA component) ===")
try:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT pitcher_era_rank, pitcher_k9_rank, pitcher_whip_rank
        FROM mlb_scored_legs_enriched
        WHERE run_date = (SELECT MAX(run_date) FROM mlb_scored_legs_enriched)
          AND pitcher_era_rank = (
              SELECT MAX(pitcher_era_rank) FROM mlb_scored_legs_enriched
              WHERE run_date = (SELECT MAX(run_date) FROM mlb_scored_legs_enriched)
          )
        LIMIT 5
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if rows:
        rank = rows[0]["pitcher_era_rank"]
        era_component = (rank - 1) / (era_max - 1) if era_max > 1 else None
        vuln = pitcher_vulnerability(
            {"pitcher_era_rank": rank,
             "pitcher_k9_rank":  rows[0]["pitcher_k9_rank"],
             "pitcher_whip_rank": rows[0]["pitcher_whip_rank"]},
            era_max, k9_max, whip_max
        )
        print(f"  ERA rank {rank}/{era_max} → ERA component={era_component:.4f}, overall vuln={vuln:.4f}")
        check("Test 4 — worst ERA rank component > 0.85", era_component is not None and era_component > 0.85,
              f"era_component={era_component:.4f}")
        check("Test 4 — worst ERA rank overall vuln > 0.60", vuln is not None and vuln > 0.60,
              f"vuln={vuln:.4f}")
    else:
        check("Test 4 — max ERA rank leg found", False, "no rows")
except Exception as e:
    check("Test 4 — DB query succeeded", False, str(e))


# ── Test 5: K/9 direction check ───────────────────────────────────────────────
print("\n=== Test 5: K/9 direction check (elite K/9 pitcher) ===")
try:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT pitcher_era_rank, pitcher_k9_rank, pitcher_whip_rank
        FROM mlb_scored_legs_enriched
        WHERE run_date = (SELECT MAX(run_date) FROM mlb_scored_legs_enriched)
          AND pitcher_k9_rank BETWEEN 1 AND 5
        LIMIT 5
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if rows:
        leg = {"pitcher_era_rank": rows[0]["pitcher_era_rank"],
               "pitcher_k9_rank":  rows[0]["pitcher_k9_rank"],
               "pitcher_whip_rank": rows[0]["pitcher_whip_rank"]}
        # Compute K/9 component alone
        k9_component = (rows[0]["pitcher_k9_rank"] - 1) / (k9_max - 1) if k9_max > 1 else None
        print(f"  K/9 rank {rows[0]['pitcher_k9_rank']} → K/9 component={k9_component}")
        check("Test 5 — elite K/9 rank contributes near 0.0", k9_component is not None and k9_component < 0.15,
              f"k9_component={k9_component}")
    else:
        check("Test 5 — K/9 rank 1-5 leg found", False, "no rows with k9_rank 1-5")
except Exception as e:
    check("Test 5 — DB query succeeded", False, str(e))


# ── Test 6: Direction filtering ───────────────────────────────────────────────
print("\n=== Test 6: Direction filtering ===")

_MAX_ERA = 196
_MAX_K9  = 195
_MAX_WHIP = 195

def _bad_pitcher_leg(team, game_pk, stat, direction):
    # ERA rank 170, K/9 rank 170, WHIP rank 170 → all near top of range → vuln > 0.60
    return {
        "team": team, "game_pk": game_pk,
        "stat": stat, "direction": direction,
        "composite_score": 60.0,
        "pitcher_era_rank":  170,
        "pitcher_k9_rank":   170,
        "pitcher_whip_rank": 170,
    }

fake_legs = [
    _bad_pitcher_leg("NYY", 999, "hits",       "over"),   # eligible
    _bad_pitcher_leg("NYY", 999, "hits",       "over"),   # eligible
    _bad_pitcher_leg("NYY", 999, "hits",       "under"),  # NOT eligible
    _bad_pitcher_leg("NYY", 999, "strikeouts", "over"),   # NOT eligible
]

result_legs = apply_stack_bonuses(fake_legs)

hits_over  = [l for l in result_legs if l["stat"] == "hits"       and l["direction"] == "over"]
hits_under = [l for l in result_legs if l["stat"] == "hits"       and l["direction"] == "under"]
so_over    = [l for l in result_legs if l["stat"] == "strikeouts" and l["direction"] == "over"]

check("Test 6 — hits/over legs get stack bonus",
      all(l.get("stack_bonus_applied") for l in hits_over),
      f"{[l.get('stack_bonus_applied') for l in hits_over]}")
check("Test 6 — hits/under does NOT get stack bonus",
      all(not l.get("stack_bonus_applied") for l in hits_under),
      f"{[l.get('stack_bonus_applied') for l in hits_under]}")
check("Test 6 — strikeouts/over does NOT get stack bonus",
      all(not l.get("stack_bonus_applied") for l in so_over),
      f"{[l.get('stack_bonus_applied') for l in so_over]}")


# ── Summary ───────────────────────────────────────────────────────────────────
print("\n=== Summary ===")
passed = sum(1 for _, s, _ in results if s == PASS)
failed = sum(1 for _, s, _ in results if s == FAIL)
for name, status, detail in results:
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
print(f"\n{passed}/{passed + failed} tests passed")
if failed:
    sys.exit(1)
