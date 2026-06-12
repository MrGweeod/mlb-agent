# MLB Parlay Agent — Build Status
**Last Updated:** June 13, 2026 (Session 11 — Bug Fixes, Shadow Audit, Pipeline Congruence)

## Overall System Status: ✅ OPERATIONAL — SESSION 11 DEPLOYED
```
┌────────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM HEALTH DASHBOARD                                │
├────────────────────────────────────────────────────────────────────────────────┤
│ Prop Whitelist (Production):    ✅ HITS O/U 0.5 + SO OVER 0.5               │
│ Prop Whitelist (Coverage):      ✅ + TOTALBASES UNDER 1.5 (shadow only)      │
│ Coverage Gate (Overs):          ✅ 65% FLOOR                                  │
│ Coverage Gate (Unders):         ✅ 40% FLOOR                                  │
│ Coverage Ceiling (85%+):        ⚠️ NOT YET IMPLEMENTED (trap confirmed)      │
│ Builder Score Floor (Overs):    ✅ 65.0 MIN_COV_POOL                         │
│ Builder Score Floor (Unders):   ✅ 40.0 MIN_COV_POOL_UNDER                  │
│ Parlay Structure:               ✅ 4-LEG, +400 TO +700 TARGET                │
│ Parlay Builder Sort:            ✅ COMPOSITE SCORE DESC                      │
│ MAX_CANDIDATES:                 ✅ 50                                         │
│ Manual Regen Exclusion:         ✅ WORKING                                    │
│ Manual Regen Fallback:          ✅ FULL POOL IF < 4 LEGS AFTER EXCLUSION    │
│ Odds Cap:                       ✅ -250 HARD CAP PER LEG                    │
│ Player Diversity (intra):       ✅ MAX 1 PER PLAYER PER PARLAY              │
│ Max Legs Per Game:              ✅ 2                                          │
├────────────────────────────────────────────────────────────────────────────────┤
│ LINEUP CONFIRMATION LAYER                                                      │
│ Scheduler Table:                ✅ mlb_pending_lineup_checks LIVE             │
│ Drain Cron (1-min):             ✅ RUNNING IN server.py                      │
│ main.py Wiring:                 ✅ DEPLOYED JUNE 13 (was missing since S10)  │
│ T-45 Lineup Checks:             ✅ 11 ROWS WRITTEN FOR TONIGHT'S SLATE      │
│ T-1 CLV Checks:                 ✅ 11 ROWS WRITTEN FOR TONIGHT'S SLATE      │
│ Four-State Annotation:          ✅ MISSING/CONFIRMED/OUT_OF_RANGE/SCRATCHED  │
│ CLR Run Type:                   ✅ BUILT — UPSTREAM-ONLY REPLACEMENT POOL    │
│ Slot Gate (soft, -8pts):        ✅ IN simple_scorer.py                       │
│ Batting Order Backfill:         ✅ 881/1031 LEGS (85.5%) JUNE 1-10          │
│ Hydrate Parser:                 ✅ VERIFIED 19/19 ON REAL GAME DATA          │
│ Live Annotation Mix:            ⚠️ FIRST LIVE CHECK FIRES TONIGHT 6:25PM ET │
├────────────────────────────────────────────────────────────────────────────────┤
│ CLV TRACKING LAYER                                                             │
│ check_type Column:              ✅ ON mlb_pending_lineup_checks               │
│ closing_odds Column:            ✅ ON mlb_scored_legs                         │
│ CLV Rows Scheduled at T-1:      ✅ 11 ROWS WRITTEN FOR TONIGHT'S SLATE      │
│ First Live Capture:             ⚠️ FIRES TONIGHT 6:39PM ET — UNVERIFIED     │
│ SGO Reuse:                      ✅ get_player_props() IMPORTED VERBATIM      │
│ compute_clv() Unit Tests:       ✅ 7/7 PASSING                               │
│ First CLV Read:                 ⏳ ~JUNE 26 (2 weeks of data needed)         │
├────────────────────────────────────────────────────────────────────────────────┤
│ SHADOW PIPELINE                                                                │
│ Shadow Pipeline:                ✅ RUNNING AFTER EVERY PRODUCTION RUN        │
│ Shadow Enrichment Rate:         ✅ 100%                                       │
│ Park Factor Signal:             ✅ VALIDATED + PERSISTING CORRECTLY           │
│ Shadow Resolution:              ✅ WIRED + ONGOING                            │
│ Prop-Specific Pitcher Routing:  ✅ WHIP→TB, K9→SO, ERA+K9+WHIP→HITS        │
│ K/9 Direction (SO Over):        ✅ FIXED JUNE 13 (was inverted since build)  │
│ Historical Backfill:            ✅ 72 LEGS CORRECTED (JUNE 9-12)             │
│ 7-Day Comparison Window:        ⚠️ TAINTED — DISCARD. CLOCK RESETS TODAY    │
│ Offense Stack Bonus:            ✅ BUILT + 3 BUGS FIXED — SHADOW ONLY       │
│ Stack Bonus Verification:       ✅ 13/13 TESTS PASS                          │
│ Stack Promotion Criteria:       ⏳ NEED 7 CLEAN SHADOW DAYS (from June 13)  │
├────────────────────────────────────────────────────────────────────────────────┤
│ SCORING + SIGNALS                                                              │
│ Direction-Aware Coverage:       ✅ coverage_overall BASE SIGNAL               │
│ Consistency Signal:             ✅ GAP-BASED ±6/±4/±2/+2/+1                 │
│ WHIP Rank Signal (Hits Prod):   ✅ FIRING IN simple_scorer.py               │
│ K9 Rank Signal (SO Prod):       ✅ FIRING IN simple_scorer.py               │
│ K9 Direction (Enriched):        ✅ FIXED JUNE 13 (inverted since June 9)    │
│ Pitcher Ranks Pool:             ✅ 201 QUALIFIED STARTERS (as of June 13)   │
│ Rank Normalization:             ✅ DYNAMIC MAX RANK — no hardcoded 30        │
│ Pitcher Rank Population:        ✅ 85.5% ERA/K9/WHIP RANKS, 98% RAW ERA    │
│ coverage_vs_hand Fallback:      ✅ FALLS BACK TO coverage_overall            │
├────────────────────────────────────────────────────────────────────────────────┤
│ TRAINING DATA                                                                  │
│ Training Data Volume:           ✅ 94K+ ROWS                                  │
│ coverage_overall:               ✅ PERSISTED                                  │
│ coverage_recent_10:             ✅ PERSISTED                                  │
│ pitcher_era_rank:               ✅ PERSISTED                                  │
│ pitcher_k9_rank:                ✅ PERSISTED                                  │
│ pitcher_whip_rank:              ✅ PERSISTED                                  │
│ whip_adj / k9_adj / era_adj:    ✅ PERSISTED                                 │
│ coverage_recent_5:              ✅ DEPRECATED — REMOVED                      │
│ Clean Data Cutoff:              ✅ APRIL 27, 2026                            │
├────────────────────────────────────────────────────────────────────────────────┤
│ INFRASTRUCTURE                                                                 │
│ Database Logging:               ✅ STABLE                                     │
│ Web UI:                         ✅ FUNCTIONAL                                 │
│ Deployment:                     ✅ LIVE (Railway auto-deploy)                │
│ FK Crash (rec_logger):          ✅ FIXED — DEPRECATED LOGGER REMOVED        │
│ Abandoned ML Model (health chk):⚠️ STILL LOADING — 3min pause per run       │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🎯 June 13, 2026 (Session 11): Stack Bonus Bugs + K/9 Fix + main.py Deploy

#### Fix: Stack Bonus 3-Bug Hotfix
Three correctness bugs found and fixed before first pipeline run.

**Bug 1 — Rank scale hardcoded to 1-30 (actual: 1-196):**
All `pitcher_vulnerability()` normalization formulas used `/29.0` — producing scores of -5.69 to +6.72. Fixed to dynamic max rank computed from the scored leg pool at runtime.

**Bug 2 — K/9 direction inverted in `pitcher_vulnerability()`:**
`(30 - k9_rank) / 29` gave rank 1 (elite) a vulnerability of 1.0. Fixed: all three stats now use `(rank - 1) / (max_rank - 1)`.

**Bug 3 — Stack eligibility direction-blind:**
All (stat, direction) combinations counted toward stacks and received the bonus. Fixed: `STACK_ELIGIBLE_PROPS = {("hits", "over")}` — only props where a vulnerable pitcher helps the bet qualify.

Files modified: `src/engine/enriched_scorer.py`, `src/pipelines/run_enriched_pipeline.py`
Files created: `sql/stack_bonus_migration.sql` (applied), `scripts/verify_stack_bonus.py`
Commit: `409f5d6`

#### Fix: K/9 Direction Inverted in Enriched Scorer
The K/9 signal for SO over in `_calculate_enriched_score()` was also inverted — separate from the stack bonus bug. `(15.5 - k9_rank) / 2.9` boosted SO over legs facing elite K pitchers (wrong direction). Fixed to `(k9_rank - 15.5) / 2.9`.

Impact: 100% of shadow parlay legs over the 7-day window were SO over. All were anti-selected for the full window. 7-day shadow comparison invalid — discard.

Files modified: `src/engine/enriched_scorer.py`
Files created: `scripts/backfill_k9_adj_june.py`
Commits: `34751c2`, `f834177`

Historical backfill: 72 SO over legs in `mlb_scored_legs_enriched` (June 9-12) had `composite_score` corrected. Score delta: ~+10 points per leg (full -5→+5 flip). June 5-8 untouched (no `pitcher_k9_rank` data for those dates).

#### Fix: main.py Session 10 Changes Never Deployed
`log_slate_start_times()`, `CLV_OFFSET_MINUTES`, `LINEUP_CHECK_OFFSET_MINUTES`, and `BATTING_ORDER_FAVORABLE` constants were committed locally but never pushed. Railway had been running pre-Session-10 `main.py` since June 12.

Resolution: Committed and pushed. `log_slate_start_times()` called manually via Claude Code. 22 pending check rows written for tonight's slate.

---

### 🎯 June 12, 2026 (Session 10): Lineup Confirmation + CLV + Backtest + Correlation Spec

See prior session handoff for full detail. Key items that are now confirmed deployed:
- Lineup confirmation layer (5 phases) — all migrations applied
- CLV tracking layer — all migrations applied
- Batting order backfill 881/1031 (85.5%)
- Backtest harness (EV-sort and slot gate both discard on clean 533-leg pool)
- Stack bonus spec written

---

## Component Status

### **1. Prop Whitelist**
```python
# Production coverage + scoring (main.py ALLOWED_PROPS):
ALLOWED_PROPS = {
    ("hits",       "over",  0.5),
    ("hits",       "under", 0.5),
    ("strikeouts", "over",  0.5),   # hitter only
    ("totalBases", "under", 1.5),   # shadow validation only
}

# Production parlays:
production_legs = [l for l in qualifying_legs if l.get("stat") != "totalBases"]

# Shadow whitelist (same as ALLOWED_PROPS):
_SHADOW_WHITELIST = {
    ("hits", "over", 0.5),
    ("hits", "under", 0.5),
    ("strikeouts", "over", 0.5),
    ("totalBases", "under", 1.5),
}
```

### **2. Coverage Gates**
| Direction | Gate | Status |
|---|---|---|
| Over | `coverage_overall >= 65%` | ✅ Active |
| Under | `coverage_overall >= 40%` | ✅ Active |
| All | `coverage_overall <= 84%` | ⚠️ NOT YET IMPLEMENTED |

### **3. Lineup Confirmation Config**
```python
LINEUP_CHECK_OFFSET_MINUTES      = 45    # T-45 primary check
LINEUP_CHECK_SECOND_PASS         = False # flip True if lineups not posted at T-45
LINEUP_CHECK_SECOND_PASS_OFFSET  = 15
LINEUP_DRAIN_INTERVAL_MINUTES    = 1
CLV_OFFSET_MINUTES               = 1     # T-1 closing odds snapshot
BATTING_ORDER_FAVORABLE = {
    ("hits",       "over"):  range(1, 6),
    ("strikeouts", "over"):  range(1, 7),
    ("totalBases", "under"): range(1, 10),
    ("hits",       "under"): range(1, 10),
}
```

### **4. Parlay Construction**
| Parameter | Value |
|---|---|
| Pool sort | `composite_score` DESC |
| MAX_CANDIDATES | 50 |
| Score floor (overs) | 65.0 |
| Score floor (unders) | 40.0 |
| Odds range | -250 to +150 per leg |
| Legs per parlay | 4 |
| Target odds | +400 to +700 |
| Max legs per game | 2 |
| Player diversity (intra) | 1 per parlay |
| Player diversity (manual regen) | Excludes prior-run players ✅ |

### **5. Source Types**
| Source | Description |
|---|---|
| `auto_9am` | Morning automated pipeline |
| `auto_12pm` | Midday automated pipeline |
| `auto_530pm` | Evening automated pipeline |
| `manual` | Manual regenerate (excludes prior-run players) |
| `confirmed_lineup_resolution` | Auto-rebuild after scratch/out-of-range detection |

### **6. Stack Bonus Config (Shadow Only)**
```python
STACK_VULNERABILITY_THRESHOLD = 0.60   # bottom ~40% of actual rank pool
STACK_BONUS                   = 4.0    # points added per eligible stack leg
STACK_MIN_LEGS                = 2      # minimum same-team legs to qualify
STACK_ELIGIBLE_PROPS = {
    ("hits", "over"),   # only prop where vulnerable pitcher helps the bet
}
```

---

## Performance Metrics

### Production Baseline (June 1-10, clean 533-leg pool)
| Prop | Win Rate | Avg Odds | Breakeven | Edge |
|---|---|---|---|---|
| Hits over | 59.9% | -202 | 66.9% | **-7.0pp** ⚠️ |
| SO over | 65.2% | -166 | 62.4% | **+2.8pp** ✅ |
| Hits under | 39.2% | ~-150 | 40.0% | **-0.8pp** ⚠️ |
| Parlay (4-leg) | 22.5% | +458 | 17.9% | **+4.6pp** ✅ |

### Shadow Pipeline Status
7-day comparison (June 5-12) is invalid due to inverted K/9 signal. **Discard entirely.** Clean shadow vs production comparison starts June 13.

### Diagnostic Findings (June 12-13)
| Test | Result |
|---|---|
| Adverse selection | Disconfirmed — selected legs match pool win rates |
| Score signal (production) | Healthy — monotonic 63.7% → 68.5% across score buckets |
| Same-game correlation | Positive — 20.0% vs 12.6% win rate with/without same-game pair |
| Shadow 7-day underperformance | Explained by inverted K/9 signal — not signal quality |
| Pipeline congruence | Confirmed — identical leg pools, correct TB exclusion |

---

## Pending Code Changes

| Item | File | Priority |
|---|---|---|
| Add 84% coverage ceiling | `main.py` | **High** — trap confirmed, one-line fix |
| Remove abandoned ML model from health check | `scripts/training_health_check.py` | Medium — 3min pause per run |
| TB under promotion to production | `main.py` | Medium — after WHIP validation (late June) |
| verify_common.py refactor | `verify_lineup_layer.py`, `verify_clv.py` | Low |
| Dead ERA cleanup in `simple_scorer.py` | `simple_scorer.py` | Low |
| Health check threshold update | `server.py` | Low |
| `won_with_void` outcome tracking | `parlay_outcome_resolver.py` | Low |

---

**Build Status:** ✅ HEALTHY
**Last Deployment:** June 13, 2026 — Stack bonus (3 bugs fixed) + K/9 direction fix + main.py lineup/CLV wiring
**Next Review:** June 14, 2026 — Verify lineup annotation + CLV capture from tonight's games
