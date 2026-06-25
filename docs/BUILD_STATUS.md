# MLB Parlay Agent — Build Status
**Last Updated:** June 25, 2026 (Session 15 — Scoring Overhaul + Player Cap Fix)

## Overall System Status: ✅ OPERATIONAL — SESSION 15 DEPLOYED

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM HEALTH DASHBOARD                                │
├────────────────────────────────────────────────────────────────────────────────┤
│ Prop Whitelist (Production):    ✅ HITS OVER 0.5 + SO OVER 0.5               │
│ Prop Whitelist (Coverage):      ✅ + HITS UNDER 0.5 + TOTALBASES UNDER 1.5  │
│ Coverage Gate (Overs):          ✅ 65% FLOOR                                  │
│ Coverage Gate (Unders):         ✅ 65% FLOOR (raised from 40% — Session 15) │
│ Coverage Ceiling (hits/over):   ⚠️  ~80% CEILING PENDING                    │
│                                    Data: 61.4% win at 80–84%, 50% at 84–90%  │
│ Coverage Ceiling (SO/over):     ✅ NO CEILING — monotonic through 84%+       │
│ Builder Score Floor (Overs):    ✅ 65.0 MIN_COV_POOL                         │
│ Builder Score Floor (Unders):   ✅ 65.0 MIN_COV_POOL_UNDER (raised Session 15)│
│ Parlay Structure:               ✅ 4-LEG, +400 TO +700 TARGET                │
│ Parlay Builder Sort:            ✅ COMPOSITE SCORE DESC                      │
│ MAX_CANDIDATES:                 ✅ 50                                         │
│ Cross-Run Player Cap (Prod):    ✅ MAX 2 PARLAY APPEARANCES/PLAYER/DAY       │
│ Cross-Run Player Cap (Shadow):  ✅ MAX 2 PARLAY APPEARANCES/PLAYER/DAY       │
│ Player Cap Fallback Logic:      ✅ FIXED (Session 15 — commit 9eed486)       │
│                                    Now checks production-eligible (non-TB)    │
│                                    legs: <12 non-TB or <6 overs → restore    │
│ Intra-Run Player Diversity:     ✅ MAX 1 PER PLAYER PER PARLAY               │
│ Odds Cap:                       ✅ -250 HARD CAP PER LEG                    │
│ Max Legs Per Game:              ✅ 2                                          │
├────────────────────────────────────────────────────────────────────────────────┤
│ SCORING — PRODUCTION (simple_scorer.py)                                        │
│ Base Signal:                    ✅ coverage_vs_hand or coverage_overall       │
│ Consistency Signal:             ✅ GAP-BASED ±6/4/2/1 — strongest predictor  │
│ ERA Raw Signal (hits):          ✅ ERA>5.0→+5, ERA<3.0→-5                   │
│ WHIP Rank Signal (hits):        ✅ REMOVED (Session 15 — commit b7b1038)     │
│                                    Was creating false 80+ bucket at 47.4% WR │
│ K/9 Rank Signal (SO/over):      ✅ ACTIVE — re-evaluate ~July 9 with         │
│                                    starter-only rank data                     │
│ Lineup Stability:               ✅ -5 if lineup_consistency < 0.50           │
│ Slot Gate (soft):               ✅ -8 if batting_order outside favorable range│
├────────────────────────────────────────────────────────────────────────────────┤
│ SCORING — SHADOW (enriched_scorer.py)                                          │
│ Vulnerability Signal (hits/over):✅ RECALIBRATED (Session 15)                │
│                                    Symmetric: <0.20→-6, <0.30→-3            │
│                                    NEW: ≥0.65→-6, ≥0.50→-3 (weak pitcher)   │
│ K/9 Rank (SO/over):             ✅ ACTIVE — re-evaluate ~July 9              │
│ WHIP Rank (TB):                 ✅ ACTIVE (starter-only ranks as of Jun 25)  │
│ Park Factor (hits):             ✅ ACTIVE — direction-aware (Session 15)     │
│ Park Factor (TB/under):         ✅ FIXED (Session 15) — was NULL for all 619 │
│                                    TB/under legs. totalBases branch added.   │
│ Park Factor Direction (unders): ✅ FIXED (Session 15) — was adding not       │
│                                    subtracting for under props               │
│ Opponent Coverage (hits/SO):    ✅ ACTIVE                                    │
│ Opponent Coverage (TB):         ✅ FIXED (Session 15) — totalBases added to  │
│                                    _PROP_STAT_MAP                            │
│ Blended ERA Rank:               ✅ COMPUTED, stored — not applied to score   │
│ Offense Stack Bonus:            ✅ ACTIVE                                    │
├────────────────────────────────────────────────────────────────────────────────┤
│ PITCHER RANK POOL                                                              │
│ Full-Season Ranks (ERA/K9/WHIP):✅ 215 qualified starters (Session 15)       │
│ Starter-Only Ranks:             ✅ NEW (Session 15 — commit b7b1038)         │
│                                    get_starter_ranks_for_today() builds      │
│                                    ERA/K9/WHIP ranks for tonight's starters  │
│                                    only (1–N, e.g. 1–18 on a 9-game slate)  │
│                                    Used as primary; full-pool as fallback    │
│                                    Eliminates reliever contamination          │
├────────────────────────────────────────────────────────────────────────────────┤
│ LINEUP CONFIRMATION LAYER (CLR)                                                │
│ Scheduler Table:                ✅ mlb_pending_lineup_checks LIVE             │
│ Drain Cron (1-min):             ✅ RUNNING IN server.py                      │
│ T-45 Lineup Checks:             ✅ CONFIRMED FIRING                           │
│ Four-State Annotation:          ✅ MISSING/CONFIRMED/OUT_OF_RANGE/SCRATCHED  │
│ CLR TB/under Exclusion:         ✅ FIXED (Session 14 — commit 8a4a7d7)       │
│ CLR Cross-Iter Player Tracking: ✅ FIXED (Session 14 — commit 8a4a7d7)       │
│ Slot Gate (soft, -8pts):        ✅ IN simple_scorer.py                       │
│ Batting Order Backfill:         ✅ 881/1031 LEGS (85.5%) JUNE 1-10          │
│ Live Annotation:                ✅ CONFIRMED LIVE                             │
├────────────────────────────────────────────────────────────────────────────────┤
│ CLV TRACKING LAYER                                                             │
│ CLV Capture Live:               ✅ LIVE (started June 16)                    │
│ First CLV Read (June 18–24):    ✅ SO/over +1.05%, hits/over +0.46%         │
│                                    hits/under -0.45%, TB/under -0.51%        │
│ Next CLV Read:                  ⏳ ~JULY 5 (larger window)                   │
├────────────────────────────────────────────────────────────────────────────────┤
│ SHADOW PIPELINE                                                                │
│ Shadow Pipeline:                ✅ RUNNING AFTER EVERY PRODUCTION RUN        │
│ TB/under Enriched Signals:      ✅ FIXED (Session 15) — park_factor and      │
│                                    opp_coverage now populating               │
│ Shadow Resolution:              ✅ ACTIVE                                    │
│ Shadow Win Rate Jun 18–24:      ⚠️  12.4% vs production 15.2% — TB/under   │
│                                    with broken signals dragging performance   │
│                                    Expect improvement with fixed signals      │
├────────────────────────────────────────────────────────────────────────────────┤
│ INFRASTRUCTURE                                                                 │
│ Database Logging:               ✅ STABLE                                     │
│ Web UI:                         ✅ FUNCTIONAL                                 │
│ Deployment:                     ✅ LIVE (Railway auto-deploy)                │
│ sklearn Version Warning:        ⚠️  1.7.2→1.8.0 mismatch (non-fatal)        │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🔧 June 25, 2026 (Session 15): Scoring Overhaul + Player Cap Fix

#### Scoring Changes (commit b7b1038)
**WHIP rank removed from simple_scorer.py hits signal.** Data analysis (232 hits/over legs) showed the WHIP rank signal was creating a false 80+ composite score bucket that won at only 47.4% — 20pp below the 66.9% breakeven. Root cause: full-season rank pool (rank 161+) is contaminated by relievers with inflated WHIPs who allow fewer actual hits than the rank implies. WHIP remains in vulnerability composite in enriched_scorer.

**hits/under gate raised from 40% to 65%.** 411 legs at the 40% gate averaged 48.8% coverage at 50.1% win rate vs 56.4% breakeven. The 14 legs that made it into parlays already averaged 66.0% coverage — the gate raise keeps the good legs and removes 397 junk legs.

**Starter-only pitcher rank pool.** New `get_starter_ranks_for_today()` in `pitcher_stats.py` builds ERA/K9/WHIP ranks restricted to tonight's confirmed starters. Eliminates reliever contamination that was causing rank 161+ anomalies. Used as primary source for `opp_pitcher_whip_rank` and `opp_pitcher_k9_rank`.

**TB/under enriched signals — 3 bugs fixed.** `totalBases` added to `_PROP_STAT_MAP` (opponent coverage was returning None), `totalBases` branch added to `_compute_park_adjustment()` (park factor was returning None), park adjustment inverted for `direction == "under"` (hitter parks were incorrectly boosting under scores).

**Vulnerability thresholds recalibrated.** Removed aggressive −10 at vuln < 0.15 (only 19 legs). Added missing weak-pitcher penalty: ≥0.65 → −6, ≥0.50 → −3. Data showed weak pitchers won at 50.6% — book prices in weak pitchers, hurting hits/over.

#### Player Cap Fallback Fixes (commits 97fbcb2 + 9eed486)
**Bug A (97fbcb2):** `"orig_qualifying_legs" in dir()` always False — `dir()` checks module scope not local variables. Removed the dead conditional.

**Bug B (9eed486, root cause):** After Bug A fix, fallback still didn't fire because it checked 41 total legs (looked healthy) but 31 were TB/under excluded from production parlays in Step 8. Only 3 usable legs remained — not enough for 4-leg parlay. Fix: fallback now computes `production_eligible` (non-TB legs) and fires if `< 12 non-TB legs` or `< 6 production overs`. Confirmed: `[player_cap] Production pool too thin after cap (11 non-TB legs, 11 overs) — restoring full pool`.

---

## Component Status

### Production Scoring Logic (simple_scorer.py)
| Signal | Status | Notes |
|--------|--------|-------|
| Coverage (base) | ✅ Active | coverage_vs_hand → coverage_overall fallback |
| Consistency | ✅ Active | ±6/4/2/1 gap-based — strongest predictor |
| ERA raw (hits) | ✅ Active | >5.0 → +5, <3.0 → -5 |
| WHIP rank (hits) | ✅ Removed | Session 15 — was inverting selection |
| K/9 rank (SO) | ✅ Active | Re-evaluate ~July 9 with starter-only data |
| Lineup stability | ✅ Active | -5 if consistency < 0.50 |
| Slot gate | ✅ Active | -8 if unfavorable batting order |

### Shadow Scoring Signals (enriched_scorer.py)
| Signal | Prop | Status | Notes |
|--------|------|--------|-------|
| Vulnerability | hits/over | ✅ Recalibrated | Symmetric ±penalties, weak pitcher added |
| K/9 rank | SO/over | ✅ Active | Starter-only ranks as of Jun 25 |
| WHIP rank | TB | ✅ Active | Starter-only ranks as of Jun 25 |
| Park factor | hits | ✅ Active | Direction-aware |
| Park factor | TB | ✅ Fixed | Was NULL for all 619 TB legs |
| Opp coverage | hits/SO | ✅ Active | — |
| Opp coverage | TB | ✅ Fixed | totalBases added to _PROP_STAT_MAP |
| Stack bonus | SO+hits | ✅ Active | — |

### Coverage Gates
| Prop / Direction | Gate | Ceiling | Status |
|---|---|---|---|
| hits/over | 65% floor | ~80% ceiling | ⚠️ Ceiling pending |
| SO/over | 65% floor | None | ✅ No ceiling confirmed |
| hits/under | 65% floor | None | ✅ Raised Session 15 |
| TB/under (shadow) | 40% floor | ~75% (tentative) | ✅ Shadow only |

---

## Performance Metrics (June 18–24 Clean Window)

### Production Parlay Win Rates
| Period | Resolved | Win Rate | Avg Odds | Edge |
|---|---|---|---|---|
| Jun 1–7 | 62 | 22.6% | +481 | +5.4pp ✅ |
| Jun 8–14 | 98 | 26.5% | +443 | +8.1pp ✅ |
| Jun 18–24 | 33 | 15.2% | +455 | -3.0pp ⚠️ |

### Production Leg Win Rates (June 18–24)
| Prop | Resolved | Win Rate | Breakeven | Edge |
|---|---|---|---|---|
| SO/over | 94 | 64.9% | 32.8% | +32.1pp ✅ |
| hits/over | 232 | 59.9% | 66.9% | -7.0pp ⚠️ |
| hits/under | 411 | 50.1% | 56.4% | -6.3pp ❌ |
| TB/under (shadow) | 619 | 55.7% | 39.1% | +16.6pp |

### CLV Read (June 18–24)
| Prop | Avg CLV % | Signal |
|---|---|---|
| SO/over | +1.05% | ✅ Genuine edge |
| hits/over | +0.46% | ⚠️ Weakly positive |
| hits/under | -0.45% | ❌ Confirmed negative |
| TB/under | -0.51% | ❌ Book pricing it in |

---

## Pending Code Changes

| Item | File | Priority |
|---|---|---|
| Add hits/over coverage ceiling at ~80% | `main.py` | **High — data confirmed** |
| Re-evaluate K/9 signal with starter-only data | `enriched_scorer.py` | Medium — ~July 9 |
| Re-evaluate WHIP signal with starter-only data | `enriched_scorer.py` | Medium — ~July 9 |
| TB/under production promotion | `main.py` | Medium — after July 9 shadow validation |
| Vulnerability recalibration validation | `enriched_scorer.py` | Medium — ~July 2 |
| Fix sklearn version mismatch | model retraining | Low — non-fatal |
| Project file cleanup (retire 4 stale docs) | Project Knowledge | Low |

---

**Build Status:** ✅ HEALTHY
**Last Deployment:** June 25, 2026 — Scoring overhaul + player cap fix (commits b7b1038, 97fbcb2, 9eed486)
**Next Review:** July 2, 2026 — vulnerability validation, stack bonus, starter-only rank first read
