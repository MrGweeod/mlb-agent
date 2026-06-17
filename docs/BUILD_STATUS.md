# MLB Parlay Agent — Build Status
**Last Updated:** June 16, 2026 (Session 13 — CLV Activation, Shadow Resolution Fix, Pitcher Signal Overhaul, Player Cap)

## Overall System Status: ✅ OPERATIONAL — SESSION 13 DEPLOYED

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM HEALTH DASHBOARD                                │
├────────────────────────────────────────────────────────────────────────────────┤
│ Prop Whitelist (Production):    ✅ HITS OVER 0.5 + SO OVER 0.5               │
│ Prop Whitelist (Coverage):      ✅ + HITS UNDER 0.5 + TOTALBASES UNDER 1.5  │
│ Coverage Gate (Overs):          ✅ 65% FLOOR                                  │
│ Coverage Gate (Unders):         ✅ 40% FLOOR                                  │
│ Coverage Ceiling (84%+):        ⚠️  NOT YET IMPLEMENTED (trap confirmed)     │
│ Builder Score Floor (Overs):    ✅ 65.0 MIN_COV_POOL                         │
│ Builder Score Floor (Unders):   ✅ 40.0 MIN_COV_POOL_UNDER                  │
│ Parlay Structure:               ✅ 4-LEG, +400 TO +700 TARGET                │
│ Parlay Builder Sort:            ✅ COMPOSITE SCORE DESC                      │
│ MAX_CANDIDATES:                 ✅ 50                                         │
│ Cross-Run Player Cap (Prod):    ✅ MAX 2 PARLAY APPEARANCES/PLAYER/DAY       │
│ Cross-Run Player Cap (Shadow):  ✅ MAX 2 PARLAY APPEARANCES/PLAYER/DAY       │
│                                    (Session 13 — commit a538fd0)             │
│ Player Cap Fallback Logic:      ⚠️  BUG — 0 parlays when all remaining      │
│                                    legs are unders (fix next session)        │
│ Intra-Run Player Diversity:     ✅ MAX 1 PER PLAYER PER PARLAY               │
│ Odds Cap:                       ✅ -250 HARD CAP PER LEG                    │
│ Max Legs Per Game:              ✅ 2                                          │
├────────────────────────────────────────────────────────────────────────────────┤
│ LINEUP CONFIRMATION LAYER                                                      │
│ Scheduler Table:                ✅ mlb_pending_lineup_checks LIVE             │
│ lineup_scheduler.py:            ✅ COMMITTED + DEPLOYED (Session 12)         │
│ game_pks Array Format:          ✅ FIXED — postgres {x,y} format             │
│ Drain Cron (1-min):             ✅ RUNNING IN server.py                      │
│ T-45 Lineup Checks:             ✅ CONFIRMED FIRING (verified June 15 logs)  │
│ Four-State Annotation:          ✅ MISSING/CONFIRMED/OUT_OF_RANGE/SCRATCHED  │
│ CLR Run Type:                   ✅ BUILT — UPSTREAM-ONLY REPLACEMENT POOL    │
│ Slot Gate (soft, -8pts):        ✅ IN simple_scorer.py                       │
│ Batting Order Backfill:         ✅ 881/1031 LEGS (85.5%) JUNE 1-10          │
│ Live Annotation:                ✅ CONFIRMED LIVE (June 15 verified)         │
├────────────────────────────────────────────────────────────────────────────────┤
│ CLV TRACKING LAYER                                                             │
│ check_type Column:              ✅ ON mlb_pending_lineup_checks               │
│ closing_odds Column:            ✅ ON mlb_scored_legs                         │
│ clv_tracker.py:                 ✅ COMMITTED + DEPLOYED (Session 13)         │
│ CLV Rows Scheduled at T-1:      ✅ AFTER EVERY 9AM PIPELINE RUN              │
│ June 16 CLV Rows (Manual):      ✅ 11 ROWS INSERTED MANUALLY (tonight)      │
│ Live CLV Capture:               ⏳ FIRST LIVE CAPTURE TONIGHT (June 16)     │
│ First CLV Read:                 ⏳ ~JUNE 26 (10 days)                        │
├────────────────────────────────────────────────────────────────────────────────┤
│ SHADOW PIPELINE                                                                │
│ Shadow Pipeline:                ✅ RUNNING AFTER EVERY PRODUCTION RUN        │
│ Shadow Enrichment Rate:         ✅ 100%                                       │
│ Shadow Resolution (parlays):    ✅ mlb_parlay_legs_enriched.outcome CORRECT  │
│ Shadow Resolution (scored legs):✅ resolve_all_enriched_legs() ADDED         │
│                                    (Session 13 — full pool, not just parlays)│
│ Shadow Resolution Direction Bug:✅ FIXED (Session 13 — direction filter added│
│                                    to SELECT + UPDATE in resolver)           │
│ June 4–15 Backfill:             ✅ COMPLETE — 128 June 15 legs resolved      │
│ Cross-Run Player Cap (Shadow):  ✅ LIVE (Session 13 — commit a538fd0)        │
│ Park Factor Signal:             ✅ VALIDATED + PERSISTING CORRECTLY           │
│ SO/over K9 Direction:           ✅ CORRECTED (Session 13 — elite K = boost)  │
│ hits/over Pitcher Signal:       ✅ VULNERABILITY PENALTY (<0.25=-6,<0.15=-10)│
│ hits/under Pitcher Signal:      ✅ REMOVED (no signal in data)               │
│ TB/over + TB/under WHIP Signal: ✅ UNCHANGED — WHIP ±5 direction-aware      │
│ Rank Normalization (all paths): ✅ DYNAMIC — 205-pitcher pool (June 16)      │
│ Offense Stack Bonus:            ✅ BUILT + LIVE (Session 11)                 │
│ Stack Bonus Early Signal:       ⚠️  72.7% vs 55.3% — only 11 legs resolved  │
├────────────────────────────────────────────────────────────────────────────────┤
│ SCORING + SIGNALS                                                              │
│ Direction-Aware Coverage:       ✅ coverage_overall BASE SIGNAL               │
│ Consistency Signal:             ✅ GAP-BASED ±6/±4/±2/+2/+1                 │
│ WHIP Rank Signal (Hits Prod):   ✅ FIRING IN simple_scorer.py               │
│ K9 Rank Signal (SO Prod):       ✅ FIRING IN simple_scorer.py               │
│ Pitcher Vulnerability (Shadow): ✅ USED AS HITS/OVER PENALTY SIGNAL         │
│ Pitcher Ranks Pool:             ✅ 205 QUALIFIED STARTERS (June 16)          │
│ Pitcher Rank Population:        ✅ 89-96% ACROSS ERA/K9/WHIP/RAW ERA        │
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
│ Clean Shadow Cutoff:            ✅ JUNE 15, 2026 (first clean vulnerability) │
├────────────────────────────────────────────────────────────────────────────────┤
│ INFRASTRUCTURE                                                                 │
│ Database Logging:               ✅ STABLE                                     │
│ Web UI:                         ✅ FUNCTIONAL                                 │
│ Deployment:                     ✅ LIVE (Railway auto-deploy)                │
│ sklearn Version Warning:        ⚠️  1.7.2→1.8.0 mismatch on ML model        │
│                                    (non-fatal, model not in production path) │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🔧 June 16, 2026 (Session 13): CLV Activation + Shadow Resolution Fix + Pitcher Signal Overhaul

#### Fix 1 — clv_tracker.py + Mass Untracked File Commit
`src/apis/clv_tracker.py` was locally present but never committed. Same pattern as `lineup_scheduler.py` from Session 12. Also discovered 14 other untracked files including `src/apis/lineup_confirmation.py`, all `scripts/`, all `sql/` migrations, and modified `simple_scorer.py`, `parlay_outcome_resolver.py`, `server.py`.

Mass commit: 15 files, 3,263 insertions. Repo now fully in sync with what's running locally.

11 CLV rows manually inserted for June 16 slate since `log_slate_start_times()` had already run. CLV checks fire T-1 tonight for the first time.

**Commits:** `50cc5a9`, `d9eb7f1`

#### Fix 2 — Shadow Resolution Direction Bug
`resolve_enriched_parlays()` matched `mlb_scored_legs` lookup on `(player_name, stat, run_date)` without `direction`. For players with both an over and under leg, `LIMIT 1` returned the wrong direction or nothing. hits/under (0/48 resolved) and TB/under (7/80 resolved) were effectively dark. Added `direction` to SELECT, lookup query, and mirror UPDATE in three places.

#### Fix 3 — resolve_all_enriched_legs() Added
Shadow scored legs resolution was tied entirely to the parlay leg mirror — only ~20 legs/day resolved. Added `resolve_all_enriched_legs(run_date)` using the same box score path as `resolve_all_legs()`. Wired into `main.py` morning resolution block. Backfill: June 15 — 128 legs resolved (74 won, 50 lost, 4 void).

#### Fix 4 — Enriched Scorer Pitcher Signal Overhaul
Three changes to `src/engine/enriched_scorer.py`:
- **SO/over K/9:** Inverted from `(k9_rank - midpoint)` to `(midpoint - k9_rank)` — elite K pitcher now correctly boosts SO/over scoring
- **hits/over:** Replaced ERA+K9+WHIP composite (±2 each, ±6 max) with vulnerability penalty: vuln<0.15 → -10, vuln<0.25 → -6
- **hits/under:** Pitcher signal removed entirely — data showed no consistent signal

Data basis: June 15 hits/over analysis — 0/3 win rate below vulnerability 0.25 (Wheeler ERA 2.22, Burns ERA 2.14), 86% above 0.50. June 15 SO/over — Burns (K/9 14+) correctly boosted SO/over.

#### Fix 5 — Cross-Run Player Cap in Shadow Pipeline
Added `get_enriched_players_used_today()` to `db.py` (queries `mlb_parlay_legs_enriched JOIN mlb_parlay_recommendations_enriched`, HAVING COUNT(*) ≥ 2). Applied filter in `run_enriched_pipeline.py` before `build_hybrid_parlays()`. Fallback: restore full pool if fewer than 20 legs remain.

**Commit:** `a538fd0`

#### Bug Discovered — Player Cap Pool-Thinning (Not Fixed)
After 5 pipeline runs on June 16, production player cap removed 66 legs from 38 capped players. Remaining 29 legs were all unders — no combination reached +400. Builder returned 0 parlays. Fallback threshold (< 20 legs) was not triggered because 29 legs remained, but they were directionally incompatible with the odds target. Fix next session.

---

### 🔧 June 15, 2026 (Session 12): Weekend Review + Shadow Audit + Pipeline Fixes
*(See previous BUILD_STATUS for full details)*

Key fixes: `lineup_scheduler.py` created, cross-run 2x player cap (production), enriched scored legs mirror fix, dynamic rank normalization.

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
| Player diversity (cross-run prod) | Max 2 total appearances today |
| Player diversity (cross-run shadow) | Max 2 total appearances today (Session 13) |

### **4. Shadow Pipeline Pitcher Signal Routing (Session 13)**
| Prop | Pitcher Signal | Direction |
|---|---|---|
| hits/over | Vulnerability penalty | vuln<0.15 → -10, vuln<0.25 → -6 |
| hits/under | None | Removed — no signal in data |
| strikeouts/over | K/9 rank ±5 | Elite K (rank 1) = +5 boost |
| totalBases/over | WHIP rank ±5 | High WHIP = boost over |
| totalBases/under | WHIP rank ±5 | Low WHIP = boost under |

### **5. Shadow Pipeline Signal Status**
| Signal | Status | Last Fix |
|---|---|---|
| Pitcher Vulnerability (hits/over) | ✅ Active — penalty -6/-10 below 0.25 | Session 13 |
| K/9 for SO/over | ✅ Active — direction corrected | Session 13 |
| WHIP for TB | ✅ Active — direction-aware | Session 12 |
| Blended ERA Rank | ✅ Active — scale corrected | Session 12 |
| Opponent Coverage | ✅ Active — thin population | — |
| Ballpark Factor | ✅ Validated + persisting | Session 9 |
| Offense Stack Bonus | ✅ Active — early signal positive | Session 11 |

---

## Performance Metrics

### Production Leg Win Rates
| Prop | Period | Appearances | Win Rate |
|---|---|---|---|
| hits/over | June 12–14 | 145 | 66.9% ✅ |
| strikeouts/over | June 12–14 | 31 | 87.1% ✅ |
| hits/under | June 12–14 | 19 | 73.7% (small sample) |

### Shadow Scored Leg Win Rates (June 15 — first clean vulnerability day)
| Prop | Vulnerability | Legs | Win Rate |
|---|---|---|---|
| hits/over | ≥0.50 | 7 | 86% |
| hits/over | 0.25–0.49 | 7 | 71% |
| hits/over | <0.25 | 3 | 0% ⚠️ |
| strikeouts/over | all | 13 | 69% |
| totalBases/under | all | 65 | 65% |

### Shadow Stack Bonus (11 legs — small sample)
| Stack Applied | Legs | Win Rate |
|---|---|---|
| true | 11 | 72.7% |
| false | 1,532 | 55.3% |

---

## Pending Code Changes

| Item | File | Priority |
|---|---|---|
| Fix player cap pool-thinning fallback | `main.py`, `run_enriched_pipeline.py` | **🔴 URGENT — 0 parlays on late regen** |
| Add 84% coverage ceiling | `main.py` | **High — quick win, trap confirmed** |
| Vulnerability penalty calibration | `enriched_scorer.py` | Medium — after June 22 data |
| TB under promotion to production | `main.py` | Medium — after shadow validates (late June) |
| Stack bonus promotion | `enriched_scorer.py` | Medium — after June 20 data |
| Fix sklearn version mismatch | model retraining | Low — non-fatal |
| verify_common.py refactor | `verify_lineup_layer.py`, `verify_clv.py` | Low |
| Dead ERA cleanup | `simple_scorer.py` | Low |
| Health check threshold update | `server.py` | Low |

---

**Build Status:** ✅ HEALTHY (with known fallback bug on late manual regens)
**Last Deployment:** June 16, 2026 — clv_tracker, shadow resolution fix, full pool resolver, pitcher signal overhaul, shadow player cap
**Next Review:** June 17, 2026 — Fix player cap fallback + verify CLV fired + 84% ceiling
