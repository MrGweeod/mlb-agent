# MLB Parlay Agent — Build Status
**Last Updated:** July 2, 2026 (Session 16 — Batting Order Slot Gate Removed)

## Overall System Status: ✅ OPERATIONAL — SESSION 16 DEPLOYED

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM HEALTH DASHBOARD                                │
├────────────────────────────────────────────────────────────────────────────────┤
│ Prop Whitelist (Production):    ✅ HITS OVER 0.5 + SO OVER 0.5               │
│ Prop Whitelist (Coverage):      ✅ + HITS UNDER 0.5 + TOTALBASES UNDER 1.5  │
│ Coverage Gate (Overs):          ✅ 65% FLOOR                                  │
│ Coverage Gate (Unders):         ✅ 65% FLOOR (raised Session 15)            │
│ Coverage Ceiling (hits/over):   ⚠️  ~80% CEILING PENDING                    │
│                                    Data: 61.4% win at 80–84%, 50% at 84–90%  │
│ Coverage Ceiling (SO/over):     ✅ NO CEILING — monotonic through 84%+       │
│ Builder Score Floor (Overs):    ✅ 65.0 MIN_COV_POOL                         │
│ Builder Score Floor (Unders):   ✅ 65.0 MIN_COV_POOL_UNDER                   │
│ Parlay Structure:               ✅ 4-LEG, +400 TO +700 TARGET                │
│ Parlay Builder Sort:            ✅ COMPOSITE SCORE DESC                      │
│ MAX_CANDIDATES:                 ✅ 50                                         │
│ Cross-Run Player Cap (Prod):    ✅ MAX 2 PARLAY APPEARANCES/PLAYER/DAY       │
│ Cross-Run Player Cap (Shadow):  ✅ MAX 2 PARLAY APPEARANCES/PLAYER/DAY       │
│ Player Cap Fallback Logic:      ✅ FIXED (Session 15)                        │
│ Intra-Run Player Diversity:     ✅ MAX 1 PER PLAYER PER PARLAY               │
│ Odds Cap:                       ✅ -250 HARD CAP PER LEG                    │
│ Max Legs Per Game:              ✅ 2                                          │
├────────────────────────────────────────────────────────────────────────────────┤
│ SCORING — PRODUCTION (simple_scorer.py)                                        │
│ Base Signal:                    ✅ coverage_vs_hand or coverage_overall       │
│ Consistency Signal:             ✅ GAP-BASED ±6/4/2/1 — strongest predictor  │
│ ERA Raw Signal (hits):          ✅ ERA>5.0→+5, ERA<3.0→-5                   │
│ WHIP Rank Signal (hits):        ✅ REMOVED (Session 15)                      │
│ K/9 Rank Signal (SO/over):      ✅ ACTIVE — re-evaluate ~July 9              │
│ Lineup Stability:               ✅ -5 if lineup_consistency < 0.50           │
│ Slot Gate (soft, -8):           ✅ REMOVED (Session 16 — commit 4cd3c37)     │
│                                    Confirmed backwards on 2 independent      │
│                                    3-week samples (hits/over + SO/over).     │
│                                    Annotation retained; scoring impact gone. │
├────────────────────────────────────────────────────────────────────────────────┤
│ SCORING — SHADOW (enriched_scorer.py)                                          │
│ Vulnerability Signal (hits/over):✅ RECALIBRATED (Session 15)                │
│ K/9 Rank (SO/over):             ✅ ACTIVE — re-evaluate ~July 9              │
│ WHIP Rank (TB):                 ✅ ACTIVE (starter-only ranks)               │
│ Park Factor (hits):             ✅ ACTIVE — direction-aware                  │
│ Park Factor (TB):               ✅ FIXED (Session 15), CONFIRMED LIVE        │
│                                    (Session 16) — 83.2% population (588/707) │
│ Opponent Coverage (hits/SO):    ✅ ACTIVE                                    │
│ Opponent Coverage (TB):         ✅ FIXED (Session 15), CONFIRMED LIVE        │
│                                    (Session 16) — 59.4% population (420/707) │
│ Offense Stack Bonus:            ✅ ACTIVE                                    │
├────────────────────────────────────────────────────────────────────────────────┤
│ PITCHER RANK POOL                                                              │
│ Starter-Only Ranks:             ✅ ACTIVE (Session 15) — re-evaluate ~July 9 │
├────────────────────────────────────────────────────────────────────────────────┤
│ LINEUP CONFIRMATION LAYER (CLR)                                                │
│ Scheduler Table:                ✅ mlb_pending_lineup_checks LIVE             │
│ Drain Cron (1-min):             ✅ RUNNING IN server.py                      │
│ T-45 Lineup Checks:             ✅ CONFIRMED FIRING                           │
│ Four-State Annotation:          ✅ MISSING/CONFIRMED/OUT_OF_RANGE/SCRATCHED  │
│                                    Health confirmed Session 16: 80.0%        │
│                                    CONFIRMED, 7.0% SCRATCHED, 4.0%           │
│                                    OUT_OF_RANGE, 8.9% never checked          │
│ CLR Rebuild Trigger:             ⚠️  CHANGED (Session 16) — SCRATCHED ONLY   │
│                                    BATTING_ORDER_OUT_OF_RANGE is now         │
│                                    annotation-only, does NOT trigger rebuild │
│                                    Prior state (both trigger) caused 76.9%   │
│                                    of all 78 weekly voids to involve OOR,    │
│                                    44.9% from OOR alone with no scratch      │
│ Slot Gate (soft, -8pts):        ✅ REMOVED (Session 16, see scoring above)   │
├────────────────────────────────────────────────────────────────────────────────┤
│ CLV TRACKING LAYER                                                             │
│ CLV Capture Live:               ✅ LIVE (started June 16)                    │
│ Next CLV Read:                  ⏳ ~JULY 5 (larger window)                   │
├────────────────────────────────────────────────────────────────────────────────┤
│ SHADOW PIPELINE                                                                │
│ Shadow Pipeline:                ✅ RUNNING AFTER EVERY PRODUCTION RUN        │
│ Shadow vs Production Leg WR:    ✅ SHADOW OUTPERFORMS on shared props        │
│                                    (Session 16) — hits/over +4.9pp,          │
│                                    SO/over +4.9pp, both n>60                  │
│ Shadow Parlay WR vs Production: ⚠️  Shadow 16.5% vs Prod 30.0% (7-day) —     │
│                                    explained by TB/under combinatorial drag, │
│                                    NOT a shadow scoring quality issue.       │
│                                    TB-free shadow parlays: 40.0% (n=10,      │
│                                    small sample) — see ARCHITECTURE_         │
│                                    DECISIONS.md §TB/under Parlay-Level Drag  │
├────────────────────────────────────────────────────────────────────────────────┤
│ DIAGNOSTIC / LOGGING GAPS                                                       │
│ void_reason (mlb_scored_legs):  ❌ NOT POPULATING — 97% NULL (66/68 legs,    │
│                                    Session 16 finding). Use superseded_      │
│                                    reason + lineup_check_status join instead │
│                                    until fixed. Not yet fixed.               │
├────────────────────────────────────────────────────────────────────────────────┤
│ INFRASTRUCTURE                                                                 │
│ Database Logging:               ✅ STABLE                                     │
│ Web UI:                         ✅ FUNCTIONAL                                 │
│ Deployment:                     ✅ LIVE (Railway auto-deploy)                │
│                                    Latest: commit 4cd3c37 (Jul 2, 2026)       │
│ sklearn Version Warning:        ⚠️  1.7.2→1.8.0 mismatch (non-fatal)        │
│ Unconfirmed commit 85b5bd5:     ⚠️  Landed on origin between Session 15 and │
│                                    16 without a session doc entry. Rebase    │
│                                    was clean. Origin not yet traced.         │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🔧 July 2, 2026 (Session 16): Batting Order Slot Gate Removal

**Investigation.** Re-tested the June 12 slot-gate hypothesis against a fresh 7-day window (June 24 – July 1). Both previously-penalized buckets outperformed their "favorable" counterparts a second time, independently:
- hits/over: slots 6-9 (penalized) 63.3% WR (n=30) vs. slots 1-5 (protected) 60.0% WR (n=205)
- strikeouts/over: slots 7-9 (penalized) 73.7% WR (n=19) vs. slots 1-6 (protected) 67.8% WR (n=87)

Separately, joined `mlb_parlay_recommendations_v2.superseded_reason` to `mlb_parlay_legs_v2.lineup_check_status` for all 78 voided parlays in the same window: 100% involved a `SCRATCHED` or `BATTING_ORDER_OUT_OF_RANGE` leg (confirms CLR as the sole void mechanism), `BATTING_ORDER_OUT_OF_RANGE` was present in 76.9% of voids, and 44.9% voided from `OUT_OF_RANGE` alone with no scratched player involved.

**Fix (commit 4cd3c37).**
- `src/engine/simple_scorer.py`: removed the -8 slot-gate scoring penalty entirely (not flipped — went neutral). Annotation of `batting_order`/`lineup_check_status` untouched.
- `src/apis/lineup_confirmation.py`: `BATTING_ORDER_OUT_OF_RANGE` downgraded from a CLR rebuild trigger to annotation-only in both `_find_affected_parlays()` and `run_confirmed_lineup_resolution()`. `SCRATCHED` remains the sole rebuild trigger, unchanged.
- Confirmed shadow pipeline unaffected (no batting_order columns on shadow tables).
- 13/13 tests passed (standalone script, no pytest in environment).
- Deployed after a clean rebase onto `origin/master` (which had advanced to an untraced commit `85b5bd5` since Session 15).

**Post-deploy verification (same day, small early sample):**
| Test | Result |
|---|---|
| `superseded_reason` OOR-alone check | **0 rows — confirmed pass** |
| Void rate, post-fix vs pre-fix | 0.0% (n=5) vs 58.3% (n=168) — promising, too small to confirm |
| Composite score gap, OOR vs CONFIRMED | 69.6 vs 77.8 (n=1 vs n=3) — inconclusive, sample too small |

Recheck scheduled ~July 5-6 with real volume behind all three statistical tests.

### 🔧 June 25, 2026 (Session 15): Scoring Overhaul + Player Cap Fix
*(Unchanged from prior version — WHIP rank removal, hits/under gate raise, starter-only pitcher ranks, TB/under 3-bug fix, vulnerability recalibration, player cap fallback fix. See git history for full Session 15 detail.)*

---

## Component Status

### Production Scoring Logic (simple_scorer.py)
| Signal | Status | Notes |
|--------|--------|-------|
| Coverage (base) | ✅ Active | coverage_vs_hand → coverage_overall fallback |
| Consistency | ✅ Active | ±6/4/2/1 gap-based — strongest predictor |
| ERA raw (hits) | ✅ Active | >5.0 → +5, <3.0 → -5 |
| WHIP rank (hits) | ✅ Removed | Session 15 |
| K/9 rank (SO) | ✅ Active | Re-evaluate ~July 9 with starter-only data |
| Lineup stability | ✅ Active | -5 if consistency < 0.50 |
| Slot gate | ✅ **Removed** | **Session 16 — confirmed backwards on 2 independent samples** |

### Lineup Confirmation Layer (lineup_confirmation.py)
| Behavior | Status | Notes |
|---|---|---|
| T-45 annotation check | ✅ Active | 80.0% CONFIRMED rate, 91.1% get some status |
| SCRATCHED → CLR rebuild | ✅ Active, unchanged | Factual roster state, not a statistical judgment |
| OUT_OF_RANGE → CLR rebuild | ❌ **Removed (Session 16)** | **Was 76.9% of all voids; 44.9% from OOR alone** |
| OUT_OF_RANGE → annotation | ✅ Active | Still written to lineup_check_status, no longer voids |

### Coverage Gates
| Prop / Direction | Gate | Ceiling | Status |
|---|---|---|---|
| hits/over | 65% floor | ~80% ceiling | ⚠️ Ceiling pending |
| SO/over | 65% floor | None | ✅ No ceiling confirmed |
| hits/under | 65% floor | None | ✅ Raised Session 15 |
| TB/under (shadow) | 40% floor | ~75% (tentative) | ✅ Shadow only — promotion pending construction-strategy decision (Session 16) |

---

## Performance Metrics (June 24 – July 1 Clean Window, Session 16 Review)

### Overall Parlay Win Rate, Production vs Shadow
| Pipeline | Resolved | Won | Void | Win Rate |
|---|---|---|---|---|
| Production | 60 | 18 | 89 | 30.0% |
| Shadow | 97 | 16 | 0 | 16.5% |

### Same-Prop Leg Win Rate, Production vs Shadow
| Prop | Shadow | Production | Delta |
|---|---|---|---|
| hits/over | 66.7% (n=78) | 61.8% (n=152) | +4.9pp shadow |
| strikeouts/over | 77.0% (n=100) | 72.1% (n=61) | +4.9pp shadow |

### TB/under Isolation (Shadow Parlays)
| Segment | Resolved | Won | Win Rate |
|---|---|---|---|
| With TB/under leg | 87 | 12 | 13.8% |
| Without TB/under leg | 10 | 4 | 40.0% |

### Void Attribution (Production, 78 voided parlays)
| Cause | Parlays | % |
|---|---|---|
| OUT_OF_RANGE present | 60 | 76.9% |
| SCRATCHED present | 39 | 50.0% |
| OUT_OF_RANGE alone (no scratch) | 35 | 44.9% |
| Neither flag present | 0 | 0.0% |

---

## Pending Code Changes

| Item | File | Priority |
|---|---|---|
| Recheck slot-gate fix with real volume | — (verification only) | **High — ~July 5-6** |
| Fix void_reason logging gap | `parlay_outcome_resolver.py` / `outcome_resolver.py` | Medium |
| TB/under parlay construction strategy | `parlay_builder.py` (or new module) | Medium — before TB/under promotion |
| Add hits/over coverage ceiling at ~80% | `main.py` | High — data confirmed, carried from Session 15 |
| Re-evaluate K/9 / WHIP with starter-only data | `enriched_scorer.py` | Medium — ~July 9 |
| Confirm origin of commit 85b5bd5 | — (investigation only) | Low |
| Fix sklearn version mismatch | model retraining | Low — non-fatal |
| Project file cleanup (retire stale docs) | Project Knowledge | Low |

---

**Build Status:** ✅ HEALTHY
**Last Deployment:** July 2, 2026 — Batting order slot gate removed (commit 4cd3c37)
**Next Review:** July 5-6, 2026 — slot-gate fix volume recheck
