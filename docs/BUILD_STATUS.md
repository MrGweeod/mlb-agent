# MLB Parlay Agent — Build Status
**Last Updated:** June 8, 2026 (Session 6 — Performance Review + Manual Regen Diversity Fix)

## Overall System Status: ✅ OPERATIONAL — SESSION 6 DEPLOYED
```
┌────────────────────────────────────────────────────────────────────────────┐
│                        SYSTEM HEALTH DASHBOARD                             │
├────────────────────────────────────────────────────────────────────────────┤
│ Prop Whitelist:              ✅ HITS O/U 0.5 + SO OVER 0.5 ONLY          │
│ Single Flat Pool:            ✅ 65% COVERAGE, -250 TO +150 ODDS           │
│ Parlay Structure:            ✅ 4-LEG, +400 TO +700 TARGET                │
│ Parlay Builder Sort:         ✅ COMPOSITE SCORE DESC (was odds DESC)      │
│ MAX_CANDIDATES:              ✅ 50 (was 15)                               │
│ B&B Pruning Bounds:          ✅ suffix_dec_sorted (valid any order)       │
│ Manual Regen Exclusion:      ✅ PRIOR-RUN PLAYERS EXCLUDED                │
│ Manual Regen Fallback:       ✅ FULL POOL IF < 4 LEGS AFTER EXCLUSION    │
│ Bug 1 Fixed (enrich_legs):   ✅ BATTER SO LEGS FULLY ENRICHED            │
│ Pitcher IP Threshold:        ✅ 3 STARTS / 3.0 IP/START (was 50 IP)      │
│ Pitcher Ranks Pool:          ✅ 192 QUALIFIED (was ~20-25)                │
│ Opp Pitcher Ranks→Hitters:   ✅ era_rank, k9_rank, whip_rank ATTACHED    │
│ K9 Rank in simple_scorer:    ✅ FIRING FOR BATTER SO PROPS               │
│ Enriched Scorer Base Signal: ✅ coverage_overall (was coverage_vs_hand)  │
│ Enriched +3 Bonus Removed:   ✅ REMOVED                                  │
│ ERA Rank Scoring (Enriched): ✅ REMOVED PENDING REVALIDATION             │
│ K9 Rank in enriched_scorer:  ✅ pitcher_ranks LOOKUP (was raw float)     │
│ Shadow Resolution:           ✅ BACKFILLED + ONGOING WIRED UP            │
│ Park Factor Signal:          ✅ VALIDATED (30pp spread)                  │
│ Coverage Gate:               ✅ 65% MINIMUM (70% FOR HITS UNDER)         │
│ Odds Cap:                    ✅ -250 HARD CAP PER LEG                    │
│ Player Diversity (intra):    ✅ MAX 1 PER PLAYER PER PARLAY              │
│ Player Diversity (regen):    ✅ PRIOR-RUN EXCLUSION ON MANUAL RUNS       │
│ Max Legs Per Game:           ✅ 2                                         │
│ Shadow Pipeline:             ✅ FULLY WIRED + RESOLVED                   │
│ Training Data:               ✅ LOGGING (94K+ ROWS)                      │
│ Database Logging:            ✅ STABLE                                    │
│ Web UI:                      ✅ FUNCTIONAL                               │
│ Deployment:                  ✅ LIVE (Railway auto-deploy)               │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🎯 June 8, 2026: Manual Regen Player Exclusion
**Commit:** `cd52b3a`

**Problem:** Hitting Regenerate Now repeatedly returned the same high-score players from the prior run. June 4 data showed Matt Olson in 5 of 7 manual parlays — when Olson went 0-for-day every manual parlay lost. The automated pipeline runs had the same saturation problem across the day's auto runs.

**Fix:** In `run_pipeline()` (`main.py`), when `source == "manual"`:
- Queries `mlb_parlay_legs_v2` for distinct player names from the most recent `batch_id` today
- Filters those players out of `qualifying_legs` before calling `build_parlays()`
- Fallback: if fewer than 4 legs remain after exclusion, uses full pool and logs the fallback
- Automated pipeline runs (9am, 12pm, 5:30pm): completely unaffected

**Behavior notes:**
- First manual regen of the day (no prior batch) → full pool, no exclusion
- Subsequent manual regens → excludes players from the immediately prior run (auto or manual)
- Hitting Regenerate twice quickly → second run excludes players from first run

---

### 🎯 June 5, 2026: Opposing Pitcher Rank Signals → Hitter Legs + K9 Rank in Scorer
**Commit:** `e67896e`

- `_attach_pitcher_rank_signals()` now attaches `opp_pitcher_era_rank`, `opp_pitcher_k9_rank`, `opp_pitcher_whip_rank` to all hitter legs via `opposing_pitcher_id`
- `simple_scorer.py` batter SO props use `opp_pitcher_k9_rank` (±5) with raw K9 fallback
- Unit test: elite K pitcher (rank ≤8) → +5, weak K pitcher (rank ≥23) → -5, no rank → 0

---

### 🎯 June 5, 2026: Full Signal Pipeline Fixes + Parlay Builder Corrections
**Commit:** `1ab63c2`

1. **`pitcher_stats.py`** — IP threshold: `ip < 50` → per-start (3+ starts, 3.0 IP/start). Pool: ~20-25 → 192.
2. **`enrich_legs.py`** — Bug 1: position-first pitcher prop detection. Batter SO legs now fully enriched.
3. **`enriched_scorer.py`** — Removed unjustified +3 handedness bonus.
4. **`enriched_scorer.py`** — Base signal standardized to `coverage_overall` always.
5. **`enriched_scorer.py`** — ERA rank scoring removed pending revalidation.
6. **`enriched_scorer.py`** — Batter SO uses `k9_rank` from `pitcher_ranks` directly.
7. **`parlay_builder.py`** — Score-sort + MAX_CANDIDATES 50 + `suffix_dec_sorted` pruning fix.

---

### 🐛 June 5, 2026: Shadow Pipeline Resolution Backfill
**Method:** Direct SQL bulk UPDATE

- 1,240 rows backfilled across May 26–June 4
- Morning resolver now writes to `mlb_scored_legs_enriched` ongoing

---

## Component Status

### **1. Prop Whitelist** ✅ ENFORCED

```python
ALLOWED_PROPS = {
    ("hits",       "over",  0.5),
    ("hits",       "under", 0.5),   # 70% gate
    ("strikeouts", "over",  0.5),   # hitter only
}
```

### **2. Scoring System** ✅ PRODUCTION + SHADOW

**`simple_scorer.py` — Production:**
- Base: `coverage_overall`
- `coverage_vs_hand`: delta ±3 cap (30% weight)
- Consistency: gap-based ±6/±4/±2/+2/+1
- Hits props: raw `pitcher_era` ±5 (pending revalidation)
- SO props: `opp_pitcher_k9_rank` → ±5 (raw K9 fallback)
- Lineup stability: -5 if `lineup_consistency < 0.50`

**`enriched_scorer.py` — Shadow:**
- Base: `coverage_overall`
- `coverage_vs_hand`: delta ±3 cap (30% weight)
- Consistency: same as production
- ERA rank: stored, NOT applied (pending revalidation)
- SO props: `k9_rank` from `pitcher_ranks` → ±5
- Park factor: ±5 (validated — 30pp spread)
- Opponent coverage: delta ±8 cap (25% weight)

### **3. Parlay Construction** ✅ SINGLE FLAT POOL

| Parameter | Value |
|---|---|
| Pool sort | `composite_score` DESC |
| MAX_CANDIDATES | 50 |
| B&B pruning | `suffix_dec_sorted` |
| Coverage floor | 65% `composite_score` |
| Odds range | -250 to +150 per leg |
| Legs per parlay | 4 |
| Target odds | +400 to +700 |
| Max legs per game | 2 |
| Player diversity (intra-parlay) | 1 per parlay |
| Player diversity (manual regen) | Excludes prior-run players |

### **4. Pitcher Signal Pipeline** ✅ FULLY FIXED

| Component | Status |
|---|---|
| Qualified pitcher pool | ✅ 192 (per-start filter) |
| Batter SO `pitcher_k9` | ✅ Populated (Bug 1 fixed) |
| Hitter `opp_pitcher_k9_rank` | ✅ Attached |
| K9 signal in scorer | ✅ Firing |
| SO enrichment rate | ⚠️ ~40% (60% NaN pitcher) |

### **5. Shadow Pipeline** ✅ FULLY OPERATIONAL

| Component | Status |
|---|---|
| Resolution backfill | ✅ 1,240 rows May 26–June 4 |
| Ongoing resolution | ✅ Wired |
| Park factor signal | ✅ Validated |
| ERA rank signal | ⚠️ Needs revalidation |

---

## Performance Metrics

### June 4, 2026 (Pre-Session 5 Baseline)
| Source | Parlays | Won | Win Rate |
|---|---|---|---|
| auto_9am | 3 | 1 | 33.3% |
| auto_12pm | 4 | 2 | 50.0% |
| auto_530pm | 2 | 0 | 0% |
| manual | 7 | 0 | 0% |

---

## Pending Code Changes

| Item | File | Priority |
|---|---|---|
| Lineup confirmation gate | `main.py`, `enrich_legs.py` | High — Volpe void demonstrated impact |
| SO enrichment NaN investigation | `enrich_legs.py` | High — ~60% of SO legs missing K9 signal |
| ERA rank re-evaluation | `enriched_scorer.py` | High — after 7 days clean data |
| Hits under pool investigation | `main.py` coverage gate | Medium |
| Manual regen fallback threshold review | `main.py` | Medium — monitor logs |
| Health check threshold update | `server.py` | Low |
| `won_with_void` outcome tracking | `parlay_outcome_resolver.py` | Low |
| Dead ERA cleanup in `simple_scorer.py` | `simple_scorer.py` | Low |

---

**Build Status:** ✅ HEALTHY
**Last Deployment:** June 8, 2026 — Manual regen player exclusion (`cd52b3a`)
**Next Review:** June 9, 2026 (Monitor exclusion logs + SO enrichment rates)
