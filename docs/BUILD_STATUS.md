# MLB Parlay Agent — Build Status
**Last Updated:** June 15, 2026 (Session 12 — Weekend Review, Shadow Audit, Pipeline Fixes)

## Overall System Status: ✅ OPERATIONAL — SESSION 12 DEPLOYED
```
┌────────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM HEALTH DASHBOARD                                │
├────────────────────────────────────────────────────────────────────────────────┤
│ Prop Whitelist (Production):    ✅ HITS OVER 0.5 + SO OVER 0.5               │
│ Prop Whitelist (Coverage):      ✅ + HITS UNDER 0.5 + TOTALBASES UNDER 1.5  │
│ Coverage Gate (Overs):          ✅ 65% FLOOR                                  │
│ Coverage Gate (Unders):         ✅ 40% FLOOR                                  │
│ Coverage Ceiling (85%+):        ⚠️  NOT YET IMPLEMENTED (trap confirmed)     │
│ Builder Score Floor (Overs):    ✅ 65.0 MIN_COV_POOL                         │
│ Builder Score Floor (Unders):   ✅ 40.0 MIN_COV_POOL_UNDER                  │
│ Parlay Structure:               ✅ 4-LEG, +400 TO +700 TARGET                │
│ Parlay Builder Sort:            ✅ COMPOSITE SCORE DESC                      │
│ MAX_CANDIDATES:                 ✅ 50                                         │
│ Cross-Run Player Cap:           ✅ MAX 2 PARLAY APPEARANCES/PLAYER/DAY       │
│ Intra-Run Player Diversity:     ✅ MAX 1 PER PLAYER PER PARLAY               │
│ Manual Regen Exclusion:         ✅ REPLACED BY CROSS-RUN CAP (Session 12)    │
│ Odds Cap:                       ✅ -250 HARD CAP PER LEG                    │
│ Max Legs Per Game:              ✅ 2                                          │
├────────────────────────────────────────────────────────────────────────────────┤
│ LINEUP CONFIRMATION LAYER                                                      │
│ Scheduler Table:                ✅ mlb_pending_lineup_checks LIVE             │
│ lineup_scheduler.py:            ✅ CREATED + DEPLOYED (Session 12)           │
│ game_pks Array Format:          ✅ FIXED — postgres {x,y} format (Session 12)│
│ Drain Cron (1-min):             ✅ RUNNING IN server.py                      │
│ T-45 Lineup Checks:             ✅ SCHEDULED AFTER 9AM PIPELINE              │
│ Four-State Annotation:          ✅ MISSING/CONFIRMED/OUT_OF_RANGE/SCRATCHED  │
│ CLR Run Type:                   ✅ BUILT — UPSTREAM-ONLY REPLACEMENT POOL    │
│ Slot Gate (soft, -8pts):        ✅ IN simple_scorer.py                       │
│ Batting Order Backfill:         ✅ 881/1031 LEGS (85.5%) JUNE 1-10          │
│ Live Annotation Mix:            ⚠️  FIRST LIVE SLATE JUNE 15 — UNVERIFIED   │
├────────────────────────────────────────────────────────────────────────────────┤
│ CLV TRACKING LAYER                                                             │
│ check_type Column:              ✅ ON mlb_pending_lineup_checks               │
│ closing_odds Column:            ✅ ON mlb_scored_legs                         │
│ CLV Rows Scheduled at T-1:      ✅ AFTER EVERY 9AM PIPELINE RUN              │
│ SGO Reuse:                      ✅ get_player_props() IMPORTED VERBATIM      │
│ Live CLV Capture:               ⚠️  FIRST LIVE SLATE JUNE 15 — UNVERIFIED   │
│ First CLV Read:                 ⏳ ~JUNE 26 (2 weeks)                        │
├────────────────────────────────────────────────────────────────────────────────┤
│ SHADOW PIPELINE                                                                │
│ Shadow Pipeline:                ✅ RUNNING AFTER EVERY PRODUCTION RUN        │
│ Shadow Enrichment Rate:         ✅ 100%                                       │
│ Shadow Resolution (parlays):    ✅ mlb_parlay_legs_enriched.outcome CORRECT  │
│ Shadow Resolution (scored legs):✅ mlb_scored_legs_enriched.result FIXED     │
│                                    (Session 12 — 11-day backfill complete)   │
│ Park Factor Signal:             ✅ VALIDATED + PERSISTING CORRECTLY           │
│ Prop-Specific Pitcher Routing:  ✅ WHIP→TB, K9→SO, ERA+K9+WHIP→HITS        │
│ Rank Normalization (all paths): ✅ DYNAMIC — 192-pitcher pool (Session 12)   │
│ Offense Stack Bonus:            ✅ BUILT + LIVE (Session 11)                 │
│ Stack Bonus Early Signal:       ⚠️  72.7% vs 55.3% — only 11 legs resolved  │
│ TB/Under in Shadow Parlays:     ⚠️  DOMINATES SHADOW CONSTRUCTION (103 apps)│
├────────────────────────────────────────────────────────────────────────────────┤
│ SCORING + SIGNALS                                                              │
│ Direction-Aware Coverage:       ✅ coverage_overall BASE SIGNAL               │
│ Consistency Signal:             ✅ GAP-BASED ±6/±4/±2/+2/+1                 │
│ WHIP Rank Signal (Hits Prod):   ✅ FIRING IN simple_scorer.py               │
│ K9 Rank Signal (SO Prod):       ✅ FIRING IN simple_scorer.py               │
│ Enriched ERA/K9/WHIP Scale:     ✅ FIXED — DYNAMIC 192-PITCHER POOL         │
│ Pitcher Ranks Pool:             ✅ 192 QUALIFIED STARTERS                    │
│ Pitcher Rank Population:        ✅ 89-96% ACROSS ERA/K9/WHIP/RAW ERA       │
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

### 🔧 June 15, 2026 (Session 12): Weekend Review + Shadow Audit + Pipeline Fixes

#### Fix 1 — lineup_scheduler.py Missing Module
`src/pipelines/lineup_scheduler.py` was never committed to the repo. Every morning pipeline silently failed with `No module named 'src.pipelines.lineup_scheduler'`, blocking all lineup and CLV checks since June 13.

Secondary bug: `game_pks` was serialized as a comma-separated string but Supabase expects a PostgreSQL array `{x,y}`. Fixed with `"{" + ",".join(str(pk) for pk in game_pks) + "}"`.

Manual backfill: 8 lineup + 8 CLV check rows written for June 15 slate via `log_slate_start_times()`.

**Commits:** `f23abfa`, sed fix

#### Fix 2 — Cross-Run 2x Player Cap
Replaced the manual-only regen exclusion block in `main.py` with a cross-run player cap applied to all sources (auto_9am, auto_12pm, auto_530pm, manual). Before each build, queries `mlb_parlay_legs_v2` for today's prior appearances. Players at ≥2 appearances removed from pool. Fallback: restore full pool if fewer than 20 legs remain after capping.

**Motivation:** June 12 — McGonigle (5 parlays), Hoerner (5), Torres (4) each sank multiple parlays simultaneously.

**Commit:** `116ae9b`

#### Fix 3 — mlb_scored_legs_enriched.result Never Resolving
Outcome resolver was updating `mlb_parlay_legs_enriched.outcome` but never writing back to `mlb_scored_legs_enriched.result`. Result was NULL for all 1,543 enriched scored legs from June 4–14 (12 days), making all shadow signal validation impossible.

Added mirror block in `outcome_resolver.py`. Backfill via direct `UPDATE ... FROM` JOIN on `(player_name, stat, run_date)` — 1,543 rows resolved.

**Commits:** `34b39a9`, `d8d64aa`

#### Fix 4 — Dynamic Rank Normalization in _calculate_enriched_score()
Session 11 fixed `pitcher_vulnerability()`. Three additional signal paths in `_calculate_enriched_score()` still used hardcoded midpoint of 15.5 (assumes 30-pitcher pool). With 192 pitchers, any rank above ~29 hit the adjustment cap immediately — signal was effectively binary.

Fixed all four paths with dynamic `midpoint = (len(pitcher_ranks) + 1) / 2.0`. Added `scripts/test_enriched_rank_normalization.py` — 5 assertions, all passing.

**Commit:** `0a7ae36`

---

### 🔧 June 13, 2026 (Session 11): Stack Bonus + K/9 Fix + Lineup Deployment

#### Stack Bonus Built (3 bugs fixed before first run)
- `pitcher_vulnerability()` composite score (ERA + K/9 + WHIP, normalized 0-1)
- `apply_stack_bonuses()` post-scoring pass in `run_enriched_pipeline.py`
- `stack_bonus_applied` + `pitcher_vulnerability` columns in `mlb_scored_legs_enriched`
- Bug 1: Rank scale hardcoded 1-30 → Dynamic max-rank fixed
- Bug 2: K/9 direction inverted in `pitcher_vulnerability()` → Fixed
- Bug 3: Stack eligibility direction-blind → `STACK_ELIGIBLE_PROPS` filter added

#### K/9 Direction Bug in _calculate_enriched_score() (SO over)
Formula `(15.5 - k9_rank) / 2.9` gave rank 1 (elite K pitcher) a +5.0 boost to SO over — wrong direction. Anti-selected SO over legs for 7+ days. Fixed to `(k9_rank - 15.5) / 2.9`. Historical backfill for June 9-12 (72 legs).

#### main.py Deployment Gap
Session 10 changes (lineup/CLV scheduling) were never pushed to GitHub. Committed and deployed. First lineup/CLV scheduling ran June 13.

---

### 🔧 June 12, 2026 (Session 10): Lineup Confirmation + CLV + Backtest + Correlation Spec

#### New: Lineup Confirmation Layer (5 phases)
Full event-driven lineup annotation and parlay resolution layer.

Migrations applied:
```sql
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

#### New: CLV Tracking Layer
```sql
ALTER TABLE mlb_pending_lineup_checks ADD COLUMN IF NOT EXISTS check_type text NOT NULL DEFAULT 'lineup';
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS closing_odds text;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS closing_odds_captured_at timestamp without time zone;
```

#### Backtest Results (v2 — clean 533-leg production pool)
| Variant | Leg Δ | Parlay Δ | Verdict |
|---|---|---|---|
| EV-sort | +0.0pp | -6.2pp | Discard |
| Slot gate | -0.0pp | -9.7pp | Discard |
| Combined | -0.1pp | -8.6pp | Discard |

---

## Component Status

### **1. Prop Whitelist**
```python
# Production coverage + scoring:
ALLOWED_PROPS = {
    ("hits",       "over",  0.5),
    ("hits",       "under", 0.5),
    ("strikeouts", "over",  0.5),   # hitter only
    ("totalBases", "under", 1.5),   # shadow validation only
}

# Production parlays (TB/under excluded):
production_legs = [l for l in qualifying_legs if l.get("stat") != "totalBases"]
```

### **2. Coverage Gates**
| Direction | Gate | Status |
|---|---|---|
| Over | `coverage_overall >= 65%` | ✅ Active |
| Under | `coverage_overall >= 40%` | ✅ Active |
| All | `coverage_overall <= 84%` | ⚠️ NOT YET IMPLEMENTED |

### **3. Parlay Construction**
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
| Player diversity (intra-run) | 1 per parlay |
| Player diversity (cross-run) | Max 2 total appearances today — removed from pool after 2nd |

### **4. Source Types**
| Source | Description |
|---|---|
| `auto_9am` | Morning automated pipeline |
| `auto_12pm` | Midday automated pipeline |
| `auto_530pm` | Evening automated pipeline |
| `manual` | Manual regenerate |
| `confirmed_lineup_resolution` | Auto-rebuild after scratch/out-of-range detection |

### **5. Shadow Pipeline Signal Status**
| Signal | Status | Last Fix |
|---|---|---|
| Blended ERA Rank | Active — scale corrected | Session 12 |
| Opponent-Specific Coverage | Active — thin population | — |
| Ballpark Factor | Active — validated | Session 9 |
| Prop-Specific Pitcher Routing | Active — scale corrected | Session 12 |
| Offense Stack Bonus | Active — early signal positive | Session 11 |

---

## Performance Metrics

### Production Leg Win Rates (June 12–14, resolved only)
| Prop | Appearances | Win Rate |
|---|---|---|
| hits/over | 145 | 66.9% ✅ |
| strikeouts/over | 31 | 87.1% ✅ |
| hits/under | 19 | 73.7% (small sample) |

### Shadow Scored Leg Win Rates (June 4–14, first clean read)
| Prop | Legs | Win Rate |
|---|---|---|
| strikeouts/over | 199 | 63.3% |
| hits/over | 343 | 61.5% |
| totalBases/under | 638 | 56.1% |
| hits/under | 363 | 44.1% ⚠️ |

### Shadow Stack Bonus (11 legs — small sample)
| Stack Applied | Legs | Win Rate |
|---|---|---|
| true | 11 | 72.7% |
| false | 1,532 | 55.3% |

---

## Pending Code Changes

| Item | File | Priority |
|---|---|---|
| Add 84% coverage ceiling | `main.py` | **High — quick win, trap confirmed** |
| Investigate K/9 direction for hits/over | `src/engine/enriched_scorer.py` | Medium — after June 20 clean data |
| TB under promotion to production | `main.py` | Medium — after shadow validates (late June) |
| Remove WHIP from hits scoring if still flat | `src/engine/enriched_scorer.py` | Low — after June 20 clean data |
| verify_common.py refactor | `verify_lineup_layer.py`, `verify_clv.py` | Low |
| Dead ERA cleanup in `simple_scorer.py` | `simple_scorer.py` | Low |
| Health check threshold update | `server.py` | Low |
| `won_with_void` outcome tracking | `parlay_outcome_resolver.py` | Low |

---

**Build Status:** ✅ HEALTHY
**Last Deployment:** June 15, 2026 — lineup_scheduler, player cap, enriched resolution fix, rank normalization fix
**Next Review:** June 16, 2026 — Verify lineup/CLV from June 15 + player cap in logs + 84% ceiling fix
