# MLB Parlay Agent — Build Status
**Last Updated:** July 8, 2026 (Session 18 — Parlay Builder Redesign + Manual Parlay Dashboard)

## Overall System Status: ✅ OPERATIONAL — SESSION 18 DEPLOYED (one open verification item)

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM HEALTH DASHBOARD                                │
├────────────────────────────────────────────────────────────────────────────────┤
│ Prop Whitelist (Production):    ✅ HITS OVER 0.5 + SO OVER 0.5               │
│ Prop Whitelist (Coverage):      ✅ + HITS UNDER 0.5 + TOTALBASES UNDER 1.5  │
│ Coverage Gate (Overs):          ✅ 65% FLOOR (composite_score, not raw cov)  │
│ Coverage Gate (Unders):         ✅ 65% FLOOR — narrow pool, 1-3 players/day │
│                                    typical (characterized Session 18)        │
│ Coverage Ceiling (hits/over):   ⚠️  ~80% CEILING PENDING                    │
│                                    Reconfirmed Session 18 on full history:   │
│                                    72.0% WR at 75-79.7%, 62.3% at 80-84.6%   │
│ Coverage Ceiling (SO/over):     ✅ NO CEILING — monotonic through 84%+       │
├────────────────────────────────────────────────────────────────────────────────┤
│ PARLAY BUILDER — REDESIGNED (Session 18, commit 5600b2e)                      │
│ Structure (OLD, superseded):    ❌ FIXED 4-LEG, +400 TO +700 BAND            │
│ Structure (NEW, current):       ✅ 4-6 LEGS, +400 FLOOR ONLY, NO CEILING     │
│ Selection method:                ✅ Greedy by composite_score DESC, stops    │
│                                    as soon as floor cleared at min 4 legs    │
│ Why changed:                     Old method proven (real data, pre-deploy)   │
│                                    to force-substitute lower-scored legs for │
│                                    higher-odds ones purely to fit the band — │
│                                    top-4-by-score cleared +400 on only 3/21  │
│                                    days (14%). Top-5 clears naturally on     │
│                                    17/21 days (81%) with zero odds engineer- │
│                                    ing. See ARCHITECTURE_DECISIONS.md §21.   │
│ Validated pre-deploy:             ✅ Old vs new run side-by-side on real     │
│                                    7/7 pool — proved the exact substitution  │
│                                    (Abreu dropped for Turner) no longer      │
│                                    happens                                   │
│ Max legs per game:               ✅ 2 (unchanged)                            │
│ Player diversity (intra-parlay): ✅ MAX 1 PER PLAYER (unchanged)             │
│ Player diversity (cross-parlay): ✅ MAX 2 PARLAY APPEARANCES/PLAYER/DAY      │
│                                    (unchanged)                               │
│ Odds cap (per-leg pool):         ✅ -250 TO +150 (unchanged)                 │
│ Regression test coverage:        ❌ ZERO — 7-case validation script was run  │
│                                    ad hoc, never committed, no longer exists │
│                                    HIGH PRIORITY gap — see Pending Changes   │
│ Live-data performance validation:⚠️  NONE YET — old backtest only confirms  │
│                                    the new code doesn't crash, not that it   │
│                                    performs. Pending ~1 week of live data.   │
├────────────────────────────────────────────────────────────────────────────────┤
│ SCORING — PRODUCTION (simple_scorer.py) — UNCHANGED THIS SESSION              │
│ Base Signal:                    ✅ coverage_vs_hand or coverage_overall       │
│ Consistency Signal:             ✅ GAP-BASED ±6/4/2/1 — strongest predictor  │
│ ERA Raw Signal (hits):          ✅ ERA>5.0→+5, ERA<3.0→-5                   │
│ WHIP Rank Signal (hits):        ✅ REMOVED (Session 15)                      │
│ K/9 Rank Signal (SO/over):      ⚠️  ACTIVE — Session 18 found early signs   │
│                                    of a possible reversal at rank extremes   │
│                                    on a small (n=14) sample; re-evaluation   │
│                                    with starter-only data still pending     │
│ Lineup Stability:               ✅ -5 if lineup_consistency < 0.50           │
│ Slot Gate (soft, -8):           ✅ REMOVED (Session 16)                      │
│ Score differentiation (SO/over):⚠️  WEAKENED post-slot-gate-fix — K/9-rank  │
│                                    gap between selected/unselected legs      │
│                                    collapsed from 17.3-vs-43.9 to 15.7-vs-   │
│                                    18.8 (Session 18 finding). Real shift or  │
│                                    noise, undetermined — ~1 week of data.    │
│                                    Session 20: production 7/8-7/9 check adds │
│                                    2 more weak reads — 33.3%/45.5% leg WR    │
│                                    vs ~61.6% baseline. 3 consecutive weak    │
│                                    reads now — priority raised to High.      │
├────────────────────────────────────────────────────────────────────────────────┤
│ SCORING — SHADOW (enriched_scorer.py)                                          │
│ Offense Stack Bonus:            ✅ ACTIVE and firing (confirmed Session 18 — │
│                                    README_10.md's "not yet built" status is  │
│                                    stale). 64.4% WR when applied (n=101) vs  │
│                                    58.8% when not (n=2,153) — promising,     │
│                                    not yet conclusive.                       │
│ All other shadow signals:        ✅ Unchanged from Session 15/16 — see prior │
│                                    version for full detail.                  │
├────────────────────────────────────────────────────────────────────────────────┤
│ MANUAL PARLAY DASHBOARD — NEW (Session 18)                                     │
│ Route:                           ✅ GET /manual (page)                       │
│ Data API:                        ✅ GET /api/manual/legs (auth required)     │
│ Submit API:                      ✅ POST /api/manual/parlay (auth required)  │
│ Auth:                            ✅ Reuses existing WEB_APP_PASSWORD — no    │
│                                    separate password, no new env var        │
│ Data source:                     ✅ get_manual_legs() — same base query as   │
│                                    get_scored_legs(), LEFT JOIN to           │
│                                    mlb_scored_legs_enriched for              │
│                                    pitcher_vulnerability/park_factor/        │
│                                    blended_era_rank                          │
│ Server-side validation:          ✅ Re-fetches all leg data by odd_id —      │
│                                    client cannot spoof odds/scores/coverage  │
│                                    on a submitted pick. 4-6 legs, no dup     │
│                                    batter, max 2/game enforced server-side.  │
│ Persistence:                     ✅ save_parlay_recommendations_v2(),        │
│                                    source='manual_pick' (distinct from the   │
│                                    pre-existing 'manual' = Regenerate Now)   │
│ Resolution:                      ✅ CONFIRMED via code read — resolver has   │
│                                    no source filter, manual picks resolve    │
│                                    automatically in the existing 9am run     │
│ +400 floor on manual picks:      ✅ NON-BLOCKING — saves regardless, returns │
│                                    meets_floor: true/false. Deliberately not │
│                                    a hard reject — see ARCHITECTURE_         │
│                                    DECISIONS.md §22 for reasoning.           │
│ UI — field-name bugs:            ✅ FIXED (commit c920f32) — best_line/      │
│                                    best_odds/opposing_pitcher_name corrected │
│                                    to line/odds/pitcher_name (6 call sites)  │
│ UI — Decimal JSON bug:           ✅ FIXED (commit b4322c1) — NUMERIC columns │
│                                    (pitcher_era/k9/whip/vulnerability/       │
│                                    blended_era_rank) were breaking           │
│                                    json.dumps(), surfacing as a false        │
│                                    "wrong password" error                   │
│ UI — sticky header:              ⚠️  FIX SHOWN BUT PUSH NOT CONFIRMED —      │
│                                    structural flex-column rewrite replaces   │
│                                    the failed JS-offset approach. Operator   │
│                                    reported "looks better" after pushing,   │
│                                    but exact commit hash was never captured  │
│                                    in-session. VERIFY FIRST, Session 19.     │
│ UI — column set:                 ✅ batting_order column removed,            │
│                                    lineup_check_status moved to last column  │
│                                    (commit c920f32)                          │
│ End-to-end test (submit→resolve):❌ NEVER ACTUALLY COMPLETED — set up as the │
│                                    reason for building this and deferred     │
│                                    repeatedly for bug fixes. HIGH PRIORITY,  │
│                                    do this first next session.               │
├────────────────────────────────────────────────────────────────────────────────┤
│ LINEUP CONFIRMATION LAYER (CLR) — UNCHANGED THIS SESSION                       │
│ (See prior version for full detail — Session 16 SCRATCHED-only trigger)       │
├────────────────────────────────────────────────────────────────────────────────┤
│ CLV TRACKING LAYER — UNCHANGED THIS SESSION                                    │
│ (Removed Session 17 — see prior version)                                      │
├────────────────────────────────────────────────────────────────────────────────┤
│ SPORTSGAMEODDS API USAGE — UNCHANGED THIS SESSION                              │
│ Account downgrade status:       🔲 STILL NOT CONFIRMED — carried multiple    │
│                                    sessions, user action pending             │
├────────────────────────────────────────────────────────────────────────────────┤
│ SHADOW PIPELINE                                                                │
│ Shadow Pipeline:                ✅ RUNNING AFTER EVERY PRODUCTION RUN        │
│ Calls new builder automatically:✅ run_enriched_pipeline.py calls the same   │
│                                    build_parlays() as production — Session   │
│                                    18's redesign applies here with no        │
│                                    separate change needed                    │
│ TB/under construction question: ⚠️  NUMBERS NOW STALE — the 15.8%/26.7%      │
│                                    with/without-TB comparison (reconfirmed   │
│                                    Session 18) was generated under the OLD   │
│                                    fixed-4-leg builder. Rerun under the new  │
│                                    4-6-leg logic before any promotion        │
│                                    decision.                                 │
├────────────────────────────────────────────────────────────────────────────────┤
│ DIAGNOSTIC / LOGGING GAPS                                                       │
│ void_reason (mlb_scored_legs):  ❌ STILL NOT POPULATING — carried, no        │
│                                    action taken Session 17 or 18             │
│ Row-count inflation:            ⚠️  NEW FINDING (Session 18) — any leg       │
│                                    surviving multiple pipeline runs or CLR   │
│                                    rebuilds gets a new row per batch in      │
│                                    mlb_parlay_legs_v2/_enriched, ~2.4x       │
│                                    inflation. Documented as a query gotcha   │
│                                    in SUPABASE_SCHEMA_REFERENCE.md this      │
│                                    session — dedupe by (run_date,            │
│                                    player_name, stat, direction) for any     │
│                                    win-rate query against those tables.      │
├────────────────────────────────────────────────────────────────────────────────┤
│ INFRASTRUCTURE                                                                 │
│ Database Logging:               ✅ STABLE                                     │
│ Web UI:                         ✅ FUNCTIONAL (+ new /manual route)          │
│ Deployment:                     ✅ LIVE (Railway auto-deploy)                │
│                                    Latest confirmed commit: c920f32 (Jul 8)  │
│                                    Possible later unconfirmed commit — see   │
│                                    sticky-header open item above            │
│ Base commit at session start:    3d7aabc (Jul 7, previously undocumented —  │
│                                    documented this session; also resolved   │
│                                    the long-open "unknown commit 85b5bd5"    │
│                                    mystery — confirmed docs-only, no code)   │
│ pytest:                          ❌ NOT INSTALLED in venv — blocks building  │
│                                    the pending parlay_builder.py test suite  │
│ sklearn Version Warning:        ⚠️  1.7.2→1.8.0 mismatch (non-fatal, carried)│
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🔧 July 8, 2026 (Session 18): Parlay Builder Redesign + Manual Parlay Dashboard

**Investigation.** A deep-dive into production vs. shadow performance (leg pools, in-parlay win rates, parlay-level win rates) surfaced a specific, testable hypothesis: the old builder's fixed 4-leg, +400/+700-banded combinatorial search was forcing substitution of lower-scored legs for higher-odds ones purely to fit the payout band. Tested directly against real data before writing any code: top-4-by-`composite_score` eligible legs cleared +400 on only 3 of 21 days (14%); top-5 cleared +400-700 naturally on 17 of 21 days (81%) with zero odds engineering; top-6 badly overshot on nearly every day.

**Decision:** removed the +700 ceiling, kept a +400 floor, replaced the fixed 4-leg requirement with a 4-6 leg range, left all other constraints (max 2/game, player diversity) unchanged.

**Fix.** `src/engine/parlay_builder.py`'s branch-and-bound search replaced with a greedy selector: sort by `composite_score` descending, walk the pool applying existing constraints, stop as soon as the floor clears at ≥4 legs, cap at 6. Both the shadow pipeline and CLR rebuilds call the same function, so the fix applies everywhere automatically. Validated pre-deployment against a real July 7 pool (old vs. new run side-by-side) — confirmed the exact substitution the redesign targeted (a higher-scored leg dropped for a lower-scored, longer-odds one purely to hit the band) no longer happens.

**Manual Parlay Dashboard (`/manual`), built alongside.** Full-signal batter+pitcher table (reusing the same `get_scored_legs()`-based query the automated pipeline itself uses, enriched with shadow-pipeline vulnerability/park-factor/blended-ERA-rank data), sortable/filterable, with a 4-6 leg selection tray that submits via a new endpoint. Confirmed via direct code read that the outcome resolver has no `source` filter, so manual picks resolve automatically in the existing morning run — no resolver changes needed. Persisted with `source='manual_pick'`, distinct from the pre-existing `'manual'` value (the "Regenerate Now" button).

**Iteration, each round driven by real testing:**
- Auth hardened proactively (grant access only on exact HTTP 200, not "anything but 401").
- A resulting false "wrong password" report was root-caused (not guessed) to a `Decimal`/`json.dumps()` serialization bug on NUMERIC pitcher columns — fixed with `json.dumps(legs, default=str)`.
- Screenshot review surfaced field-name bugs (`best_line`/`best_odds`/`opposing_pitcher_name` vs. the actual `line`/`odds`/`pitcher_name` fields) and layout issues — fixed by reading the live file and cross-checking real DB field names.
- Sticky-header fix took two attempts — first (JS-measured offset) made the bug visibly worse, correctly triggering a structural rewrite instead of a third pixel guess (flex-column layout, `thead { position: sticky; top: 0 }` correct by construction). Neither Claude Code nor Claude (chat) had rendering tools available to confirm visually in either case — operator verified directly against the live deployed page.

**Commits:** `5600b2e` (builder + dashboard initial), `b4322c1` (Decimal fix), `c920f32` (field names + layout + column set). A further sticky-header structural fix was shown as a diff; push status not explicitly confirmed in-session — **verify first, Session 19.**

**Known gaps, both high priority for Session 19:**
1. The builder rewrite's 7-case regression test was never committed — zero persisted test coverage on the largest architecture change in the project.
2. The manual-pick end-to-end flow (submit → resolves correctly next morning) — the entire point of building this — was never actually tested this session.

### 🔧 July 7, 2026 (Session 17): CLV Tracking Layer Removal + SGO Cost Optimization
*(Unchanged from prior version — see that document for full detail.)*

### 🔧 July 2, 2026 (Session 16): Batting Order Slot Gate Removal
*(Unchanged from prior version.)*

### 🔧 June 25, 2026 (Session 15): Scoring Overhaul + Player Cap Fix
*(Unchanged from prior version.)*

---

## Component Status

### Parlay Builder (parlay_builder.py) — REDESIGNED Session 18
| Component | Status | Notes |
|---|---|---|
| Leg count | ✅ 4-6 (was fixed 4) | Greedy: stops at fewest legs that clear the floor |
| Combined odds | ✅ +400 floor only (was +400-700 band) | No ceiling |
| Selection method | ✅ Greedy by composite_score | Was branch-and-bound combinatorial search |
| Max legs/game | ✅ 2, unchanged | |
| Player diversity | ✅ Unchanged | Both intra- and cross-parlay caps preserved |
| Regression tests | ❌ None committed | High priority gap |
| Live performance data | ⚠️ None yet | Pending ~1 week |

### Manual Parlay Dashboard (manual.html, server.py, db.py) — NEW Session 18
| Component | Status | Notes |
|---|---|---|
| Data display | ✅ Working | Field-name bugs fixed commit c920f32 |
| Auth | ✅ Working | Hardened + Decimal bug fixed, reuses existing password |
| Submission | ✅ Working | Server-side re-validation, non-blocking floor |
| Resolution | ✅ Confirmed via code, ❌ not tested live | No source filter in resolver — should just work |
| Layout/sticky header | ⚠️ Fix shown, push unconfirmed | Verify Session 19 |

### Coverage Gates
| Prop / Direction | Gate | Ceiling | Status |
|---|---|---|---|
| hits/over | 65% floor | ~80% ceiling | ⚠️ Ceiling still pending, reconfirmed Session 18 |
| SO/over | 65% floor | None | ✅ No ceiling confirmed |
| hits/under | 65% floor | None | ⚠️ Very narrow eligible pool (1-3 players/day) — characterized Session 18, not a gate change |
| TB/under (shadow) | 40% floor | ~75% (tentative) | ⚠️ Promotion analysis stale — rerun under new builder before deciding |

---

## Pending Code Changes

| Item | File | Priority |
|---|---|---|
| Confirm sticky-header fix commit + push status | — (verification only) | **High — Session 19, first thing** |
| Complete manual-pick end-to-end test | — (verification only) | **High — Session 19, first thing** |
| Commit persisted regression tests for the new builder | `tests/test_parlay_builder.py` (new) | **High — Session 19** |
| Install pytest in venv | — (environment) | High — blocks the above |
| Live-data performance recheck of new builder | — (verification only) | High — once ~1 week of data exists |
| Rerun TB/under construction-strategy analysis under new builder | `parlay_builder.py` / analysis only | Medium — before any promotion decision |
| Recheck SO/over pool-composition softening | — (verification only) | **High** (raised Session 20 — 3 consecutive weak reads: Session 18 + 7/8 + 7/9) |
| Cancel SGO Pro subscription (account-level, not code) | — (manual action) | High — carried multiple sessions, not yet confirmed |
| Add hits/over coverage ceiling at ~80% | `main.py` | High — data reconfirmed Session 18, still not implemented |
| Re-evaluate K/9 / WHIP with starter-only data | `enriched_scorer.py` | Medium — new small-sample reversal signal adds urgency |
| Fix void_reason logging gap | `parlay_outcome_resolver.py` / `outcome_resolver.py` | Medium — carried, no action taken |
| Fix sklearn version mismatch | model retraining | Low — non-fatal |
| Project file cleanup (retire stale docs) | Project Knowledge | Low — carried |

---

**Build Status:** ✅ HEALTHY (one open verification item on the sticky-header commit)
**Last Deployment:** July 8, 2026 — parlay builder redesigned, manual parlay dashboard shipped (commits `5600b2e`, `b4322c1`, `c920f32`, plus one unconfirmed sticky-header fix)
**Next Review:** Confirm sticky-header commit hash + complete manual-pick end-to-end test (both Session 19, first priority)
