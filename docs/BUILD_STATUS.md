# MLB Parlay Agent — Build Status
**Last Updated:** June 9, 2026 (Session 9 — Performance Analysis + Data Pipeline Gaps + TB Under + Bug Fixes)

## Overall System Status: ✅ OPERATIONAL — SESSION 9 DEPLOYED
```
┌────────────────────────────────────────────────────────────────────────────┐
│                        SYSTEM HEALTH DASHBOARD                             │
├────────────────────────────────────────────────────────────────────────────┤
│ Prop Whitelist (Production):  ✅ HITS O/U 0.5 + SO OVER 0.5              │
│ Prop Whitelist (Coverage):    ✅ + TOTALBASES UNDER 1.5 (shadow only)    │
│ Coverage Gate (Overs):        ✅ 65% FLOOR                                │
│ Coverage Gate (Unders):       ✅ 40% FLOOR                                │
│ Coverage Ceiling (85%+):      ⚠️ NOT YET IMPLEMENTED (trap confirmed)    │
│ Builder Score Floor (Overs):  ✅ 65.0 MIN_COV_POOL                       │
│ Builder Score Floor (Unders): ✅ 40.0 MIN_COV_POOL_UNDER                 │
│ TB Under in Coverage Pipeline:✅ 113 LEGS TODAY, AVG SCORE 60.8          │
│ TB Under in Production Parlays:⚠️ EXCLUDED — PENDING SHADOW VALIDATION  │
│ WHIP Rank Signal (TB Shadow): ✅ 95.6% POPULATION RATE                   │
│ WHIP Rank Signal (Hits Prod): ✅ FIRING IN SIMPLE_SCORER                 │
│ K9 Rank Signal (SO Prod):     ✅ FIRING IN SIMPLE_SCORER                 │
│ Pitcher Signal Routing:       ✅ PROP-SPECIFIC IN ENRICHED_SCORER        │
│ Parlay Structure:             ✅ 4-LEG, +400 TO +700 TARGET              │
│ Parlay Builder Sort:          ✅ COMPOSITE SCORE DESC                    │
│ MAX_CANDIDATES:               ✅ 50                                       │
│ Manual Regen Exclusion:       ✅ FIXED — WORKING (was broken since 6/8)  │
│ Manual Regen Fallback:        ✅ FULL POOL IF < 4 LEGS AFTER EXCLUSION  │
│ Shadow Pipeline:              ✅ RUNNING AFTER EVERY PRODUCTION RUN      │
│ Shadow Enrichment Rate:       ✅ 100% (was 52%)                          │
│ FK Crash (rec_logger):        ✅ FIXED — DEPRECATED LOGGER REMOVED      │
│ Training Data — coverage_overall: ✅ NOW PERSISTED                       │
│ Training Data — coverage_recent_10: ✅ NOW PERSISTED                     │
│ Training Data — pitcher_era_rank: ✅ NOW PERSISTED                       │
│ Training Data — pitcher_k9_rank:  ✅ NOW PERSISTED                       │
│ Training Data — pitcher_whip_rank: ✅ NOW PERSISTED                      │
│ Training Data — whip_adj/k9_adj/era_adj: ✅ NOW PERSISTED               │
│ coverage_recent_5:            ✅ DEPRECATED — REMOVED FROM ALL INSERTS  │
│ coverage_vs_hand Fallback:    ✅ FALLS BACK TO coverage_overall          │
│ Enrich Failures Logged:       ✅ [enrich_legs] FAILURE MESSAGES ACTIVE  │
│ Pitcher Ranks Pool:           ✅ 192 QUALIFIED                           │
│ Opp Pitcher Ranks→Hitters:    ✅ era_rank, k9_rank, whip_rank ATTACHED  │
│ Consistency Signal:           ✅ GAP-BASED ±6/±4/±2/+2/+1              │
│ Direction-Aware Coverage:     ✅ coverage_overall BASE SIGNAL            │
│ Park Factor Signal (Shadow):  ✅ VALIDATED + PERSISTING CORRECTLY        │
│ Shadow Resolution:            ✅ WIRED + ONGOING                         │
│ Odds Cap:                     ✅ -250 HARD CAP PER LEG                  │
│ Player Diversity (intra):     ✅ MAX 1 PER PLAYER PER PARLAY            │
│ Player Diversity (regen):     ✅ PRIOR-RUN EXCLUSION ON MANUAL RUNS     │
│ Max Legs Per Game:            ✅ 2                                        │
│ Training Data Volume:         ✅ 94K+ ROWS                               │
│ Database Logging:             ✅ STABLE                                   │
│ Web UI:                       ✅ FUNCTIONAL                              │
│ Deployment:                   ✅ LIVE (Railway auto-deploy)              │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🎯 June 9, 2026 (Session 9): Training Data Gaps + TB Under + Bug Fixes

#### Fix: 6 Training Data Pipeline Gaps
All pitcher rank signals, coverage_overall, and coverage_recent_10 were never being written to mlb_training_data. Fixed across db.py, coverage.py, main.py, and run_enriched_pipeline.py.

Required migrations applied:
```sql
ALTER TABLE mlb_training_data ADD COLUMN IF NOT EXISTS coverage_overall double precision;
ALTER TABLE mlb_training_data ADD COLUMN IF NOT EXISTS coverage_recent_10 double precision;
ALTER TABLE mlb_training_data ADD COLUMN IF NOT EXISTS whip_adj double precision;
ALTER TABLE mlb_training_data ADD COLUMN IF NOT EXISTS k9_adj double precision;
ALTER TABLE mlb_training_data ADD COLUMN IF NOT EXISTS era_adj double precision;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS pitcher_k9_rank integer;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS pitcher_whip_rank integer;
ALTER TABLE mlb_scored_legs_enriched ADD COLUMN IF NOT EXISTS pitcher_era_rank integer;
ALTER TABLE mlb_scored_legs_enriched ADD COLUMN IF NOT EXISTS pitcher_k9_rank integer;
ALTER TABLE mlb_scored_legs_enriched ADD COLUMN IF NOT EXISTS pitcher_whip_rank integer;
```

#### Feat: Prop-Specific Pitcher Signal Routing (Shadow)
`enriched_scorer.py` now routes pitcher signals by prop type:
- `totalBases under 1.5`: WHIP rank only (±5)
- `strikeouts over 0.5`: K/9 rank only (±5), continuous formula replacing bucket thresholds
- `hits over/under 0.5`: ERA + K/9 + WHIP combined (±2 each, ±6 max)

#### Feat: Total Bases Under 1.5 in Coverage Pipeline
Added to ALLOWED_PROPS in main.py. Excluded from production parlays via `production_legs` filter before build_parlays(). Flows through coverage → scoring → mlb_scored_legs → shadow pipeline only.

#### Fix: Deprecated Recommendation Logger FK Crash
`recommendation_logger.py` was writing to renamed legacy table on every run. Removed import and call from main.py entirely.

#### Fix: Manual Regen Exclusion (RealDictCursor Bug)
`row[0]` → `row["player_name"]`. Exclusion was silently failing since June 8. First confirmed working run: 20 players excluded, completely fresh parlay set generated.

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

# Production parlays (production_legs filter before build_parlays()):
production_legs = [l for l in qualifying_legs if l.get("stat") != "totalBases"]

# Shadow pipeline whitelist (run_enriched_pipeline.py):
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

### **3. Training Data Columns (Post Session 9)**
| Column | Status |
|---|---|
| `coverage_pct` | ✅ Always populated |
| `coverage_overall` | ✅ Now populated (new) |
| `coverage_recent_10` | ✅ Now populated (new) |
| `coverage_vs_hand` | ✅ Now populated (fallback fixed) |
| `pitcher_era_rank` | ✅ Now populated (new) |
| `pitcher_k9_rank` | ✅ Now populated (new) |
| `pitcher_whip_rank` | ✅ Now populated (new) |
| `whip_adj` | ✅ Now populated (new) |
| `k9_adj` | ✅ Now populated (new) |
| `era_adj` | ✅ Now populated (new) |
| `composite_score` | ✅ Always populated |
| `coverage_recent_5` | ✅ Deprecated — removed |

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
| Player diversity (manual regen) | Excludes prior-run players ✅ WORKING |

---

## Performance Metrics

### Era Comparison (558 resolved parlays)
| Era | Resolved | Win Rate | Avg Odds | vs Breakeven |
|---|---|---|---|---|
| 1 — High odds (pre anchor/swing) | 508 | 6.5% | +1263 | ~-0.8pp |
| 2 — Anchor/Swing | 58 | 6.9% | +1054 | ~-2.7pp |
| 3 — Flat pool +400–+700 | 136 | 19.1% | +464 | ~+1.4pp |

### Clean Training Data Leg Win Rates (April 27+)
| Prop | Coverage 65-74% | Coverage 75-84% | Avg Odds | Breakeven |
|---|---|---|---|---|
| Hits over | 64.0% | 71.8% | -202 | 66.9% |
| SO over | 64.2% | 72.7% | -166 | 62.4% |
| TB under | 61.1% | 60.9% | -163 | 61.9% |
| Hits under | 63.8% | 60.6% | +104 | 49.0% |

---

## Pending Code Changes

| Item | File | Priority |
|---|---|---|
| Add 84% coverage ceiling to gate | `main.py` | High — trap confirmed by data |
| Hits under score normalization | `parlay_builder.py` | High — after 50+ resolved legs |
| Lineup confirmation gate | `main.py`, `enrich_legs.py` | High — voids still possible |
| TB under promotion to production | `main.py` | Medium — after WHIP validation (late June) |
| Shadow vs production comparison | Analysis | Medium — June 12+ |
| ERA rank re-evaluation | `enriched_scorer.py` | Medium — June 12+ |
| Manual regen fallback threshold review | `main.py` | Low |
| Dead ERA cleanup in `simple_scorer.py` | `simple_scorer.py` | Low |
| Health check threshold update | `server.py` | Low |
| `won_with_void` outcome tracking | `parlay_outcome_resolver.py` | Low |

---

**Build Status:** ✅ HEALTHY
**Last Deployment:** June 9, 2026 — Training data gaps + TB under + bug fixes
**Next Review:** June 10, 2026
