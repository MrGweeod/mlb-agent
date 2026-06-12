# MLB Parlay Agent — Build Status
**Last Updated:** June 12, 2026 (Session 10 — Lineup Confirmation + CLV Tracking + Backtest Harness + Correlation Spec)

## Overall System Status: ✅ OPERATIONAL — SESSION 10 DEPLOYED
```
┌────────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM HEALTH DASHBOARD                                │
├────────────────────────────────────────────────────────────────────────────────┤
│ Prop Whitelist (Production):    ✅ HITS OVER 0.5 + SO OVER 0.5               │
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
│ T-45 Lineup Checks:             ✅ SCHEDULED AFTER 9AM PIPELINE              │
│ Four-State Annotation:          ✅ MISSING/CONFIRMED/OUT_OF_RANGE/SCRATCHED  │
│ CLR Run Type:                   ✅ BUILT — UPSTREAM-ONLY REPLACEMENT POOL    │
│ Slot Gate (soft, -8pts):        ✅ IN simple_scorer.py                       │
│ Batting Order Backfill:         ✅ 881/1031 LEGS (85.5%) JUNE 1-10          │
│ Hydrate Parser:                 ✅ VERIFIED 19/19 ON REAL GAME DATA          │
│ verify_lineup_layer.py:         ✅ ALL SECTIONS PASSING                      │
│ Live Annotation Mix:            ⚠️ NOT YET OBSERVED (first live slate pending)│
├────────────────────────────────────────────────────────────────────────────────┤
│ CLV TRACKING LAYER                                                             │
│ check_type Column:              ✅ ON mlb_pending_lineup_checks               │
│ closing_odds Column:            ✅ ON mlb_scored_legs                         │
│ CLV Rows Scheduled at T-1:      ✅ AFTER EVERY 9AM PIPELINE RUN              │
│ SGO Reuse:                      ✅ get_player_props() IMPORTED VERBATIM      │
│ compute_clv() Unit Tests:       ✅ 7/7 PASSING                               │
│ verify_clv.py:                  ✅ 10/10 (2 skipped — expected)              │
│ Live CLV Capture:               ⚠️ CLOCK STARTED JUNE 12 — NO DATA YET     │
│ First CLV Read:                 ⏳ ~JUNE 26 (2 weeks)                        │
├────────────────────────────────────────────────────────────────────────────────┤
│ SHADOW PIPELINE                                                                │
│ Shadow Pipeline:                ✅ RUNNING AFTER EVERY PRODUCTION RUN        │
│ Shadow Enrichment Rate:         ✅ 100%                                       │
│ Park Factor Signal:             ✅ VALIDATED + PERSISTING CORRECTLY           │
│ Shadow Resolution:              ✅ WIRED + ONGOING                            │
│ Prop-Specific Pitcher Routing:  ✅ WHIP→TB, K9→SO, ERA+K9+WHIP→HITS        │
│ Offense Stack Bonus:            ⚠️ SPEC READY — NOT YET BUILT               │
├────────────────────────────────────────────────────────────────────────────────┤
│ SCORING + SIGNALS                                                              │
│ Direction-Aware Coverage:       ✅ coverage_overall BASE SIGNAL               │
│ Consistency Signal:             ✅ GAP-BASED ±6/±4/±2/+2/+1                 │
│ WHIP Rank Signal (Hits Prod):   ✅ FIRING IN simple_scorer.py               │
│ K9 Rank Signal (SO Prod):       ✅ FIRING IN simple_scorer.py               │
│ Pitcher Ranks Pool:             ✅ 192 QUALIFIED STARTERS                    │
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
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🎯 June 12, 2026 (Session 10): Lineup Confirmation + CLV + Backtest + Correlation Spec

#### New: Lineup Confirmation Layer (5 phases)
Full event-driven lineup annotation and parlay resolution layer.

Migrations applied:
```sql
-- Lineup layer
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS batting_order integer;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS lineup_check_status text;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS lineup_checked_at timestamp without time zone;
ALTER TABLE mlb_parlay_legs_v2 ADD COLUMN IF NOT EXISTS batting_order integer;
ALTER TABLE mlb_parlay_legs_v2 ADD COLUMN IF NOT EXISTS lineup_check_status varchar;
ALTER TABLE mlb_parlay_legs_v2 ADD COLUMN IF NOT EXISTS lineup_checked_at timestamp with time zone;
ALTER TABLE mlb_parlay_recommendations_v2 ADD COLUMN IF NOT EXISTS superseded_by_batch_id varchar;
ALTER TABLE mlb_parlay_recommendations_v2 ADD COLUMN IF NOT EXISTS superseded_reason text;
CREATE TABLE IF NOT EXISTS mlb_pending_lineup_checks (...);
```

Files created: `sql/lineup_confirmation_migration.sql`, `src/apis/lineup_confirmation.py`, `src/pipelines/lineup_scheduler.py`, `scripts/backfill_batting_order.py`, `verify_lineup_layer.py`
Files modified: `src/web/server.py`, `src/engine/simple_scorer.py`, `main.py`

#### New: CLV Tracking Layer
Closing odds snapshot at T-1 for all scored legs. Reuses lineup scheduler with `check_type` discriminator.

Migrations applied:
```sql
ALTER TABLE mlb_pending_lineup_checks ADD COLUMN IF NOT EXISTS check_type text NOT NULL DEFAULT 'lineup';
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS closing_odds text;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS closing_odds_captured_at timestamp without time zone;
CREATE INDEX IF NOT EXISTS idx_pending_checks_type ON mlb_pending_lineup_checks (check_type, status, trigger_at);
```

Files created: `sql/clv_tracking_migration.sql`, `src/apis/clv_tracker.py`, `verify_clv.py`
Files modified: `src/apis/lineup_confirmation.py` (check_type dispatch), `main.py` (CLV_OFFSET_MINUTES, schedule_clv_checks)

#### New: Backtest Harness
`scripts/run_backtest.py` — read-only replay harness for June 1-10 window.

**Results (v2 — clean 533-leg production pool):**
| Variant | Leg Δ | Parlay Δ | Verdict |
|---|---|---|---|
| EV-sort | +0.0pp | -6.2pp | Discard |
| Slot gate | -0.0pp | -9.7pp | Discard |
| Combined | -0.1pp | -8.6pp | Discard |

Root cause: pool-thinning. 533 production legs + 4-leg minimum + construction constraints → filtering drops parlays from 191 to 43-49.

#### New: Correlation Restructure Spec
`CORRELATION_RESTRUCTURE_SPEC.md` — offense stack bonus for shadow pipeline. Ready for Claude Code.

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

# Shadow whitelist:
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

---

## Performance Metrics (June 1-10, production pool)

### Production Baseline (533 resolved legs, 191 parlays)
| Prop | Win Rate | Avg Odds | Breakeven | Edge |
|---|---|---|---|---|
| Hits over | 59.9% | -202 | 66.9% | **-7.0pp** |
| SO over | 65.2% | -166 | 62.4% | **+2.8pp** |
| Parlay win rate | 22.5% | +458 | 17.9% | **+4.6pp** |

### Diagnostic Findings (June 12)
| Test | Result |
|---|---|
| Adverse selection | Disconfirmed — selected legs match pool win rates |
| Score signal | Healthy — monotonic 63.7% → 68.5% across score buckets |
| Same-game correlation | Positive — 20.0% vs 12.6% win rate with/without same-game pair |
| EV-sort on clean pool | +0.0pp leg improvement — coverage_overall not discriminating within validated pool |
| Slot gate on clean pool | -0.0pp leg improvement — hypothesis contradicted (slots 6-9 > slots 1-5) |

---

## Pending Code Changes

| Item | File | Priority |
|---|---|---|
| Build offense stack bonus | `src/engine/enriched_scorer.py`, `run_enriched_pipeline.py` | **Highest** — spec ready |
| Add 84% coverage ceiling | `main.py` | High — trap confirmed |
| Apply stack_bonus_migration.sql | Supabase | With stack bonus build |
| verify_common.py refactor | `verify_lineup_layer.py`, `verify_clv.py` | Low |
| TB under promotion to production | `main.py` | Medium — after WHIP validation (late June) |
| Dead ERA cleanup in `simple_scorer.py` | `simple_scorer.py` | Low |
| Health check threshold update | `server.py` | Low |
| `won_with_void` outcome tracking | `parlay_outcome_resolver.py` | Low |

---

**Build Status:** ✅ HEALTHY
**Last Deployment:** June 12, 2026 — Lineup confirmation + CLV tracking layers live
**Next Review:** June 13, 2026 — Monitor CLV capture + lineup annotation on first live slate
