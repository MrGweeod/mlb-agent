# MLB Parlay Agent — Build Status
**Last Updated:** July 29, 2026 (Session 23 — SGO billing empirically verified per-event; pipeline schedule cut 3→2 runs/day ahead of the 2026-08-01 SGO tier downgrade; full prop-line capture + resolution built into mlb_prop_legs_history)

## Overall System Status: ✅ OPERATIONAL — SESSIONS 22+23 WORK COMPLETE LOCALLY, ABOUT TO BE COMMITTED

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
│ PARLAY BUILDER — REVERTED TO FIXED 4 LEGS (Session 21, branch pending merge)   │
│ Structure (Session 18, superseded):❌ 4-6 LEGS, +400 FLOOR ONLY, NO CEILING  │
│                                    Confirmed -EV: -$0.42 to -$0.66 per $1    │
│                                    staked vs. old structure's +$0.128        │
│ Structure (CURRENT, reverted):  ✅ FIXED 4 LEGS, +400 FLOOR ONLY, NO CEILING │
│                                    MAX_LEGS constant 6→4. Floor-only         │
│                                    philosophy from Session 18 kept — only    │
│                                    the flexible leg-count half reverted.     │
│                                    See ARCHITECTURE_DECISIONS.md §26.        │
│ Why reverted:                    Real EV per $1 staked, computed from live  │
│                                    resolved parlays: pre-redesign 4-leg      │
│                                    +$0.128 (n=486) vs. post-redesign 4-leg   │
│                                    -$0.662 (n=28) and 5-leg -$0.416 (n=58).  │
│                                    Higher payout on longer parlays doesn't   │
│                                    compensate for the lower AND-probability  │
│                                    hit rate.                                 │
│ Loop boundary safety:            ✅ Verified by direct code read — MIN_LEGS  │
│                                    == MAX_LEGS == 4 converges cleanly, no    │
│                                    off-by-one or infinite-loop risk          │
│ Open question:                   ⚠️  Simulation suggests the revert may NOT  │
│                                    fully restore +$0.128 EV (-$0.25 to       │
│                                    -$0.34 in sim, n=48-69, thin/noisy) —     │
│                                    flagged for live tracking, not resolved   │
│ Max legs per game:               ✅ 2 (unchanged)                            │
│ Player diversity (intra-parlay): ✅ MAX 1 PER PLAYER (unchanged)             │
│ Player diversity (cross-parlay): ✅ MAX 2 PARLAY APPEARANCES/PLAYER/DAY      │
│                                    (unchanged)                               │
│ Odds cap (per-leg pool):         ✅ -250 TO +150 (unchanged)                 │
│ Regression test coverage:        ✅ 14 new tests (tests/test_bug_fixes.py)   │
│                                    committed Session 21, covering leg-count  │
│                                    boundary behavior alongside the other two │
│                                    fixes. 76/76 total tests passing.         │
│ Live-data performance validation:⚠️  PENDING — revert not yet deployed as   │
│                                    of this doc update. Watch parlay win rate │
│                                    over the next 1-2 weeks post-deploy.      │
├────────────────────────────────────────────────────────────────────────────────┤
│ SCORING — PRODUCTION (simple_scorer.py) — logic unchanged, upstream fixes    │
│                                    below affect whether adjustments fire     │
│ Base Signal:                    ✅ coverage_vs_hand or coverage_overall       │
│ Consistency Signal:             ✅ GAP-BASED ±6/4/2/1 — sample floor added   │
│                                    Session 21 (MIN_RECENT_GAMES=5) — was     │
│                                    trusting recent_10 off as few as 1 game   │
│ ERA Raw Signal (hits):          ❌ CONFIRMED INVERTED (Session 21) — weak-   │
│                                    pitcher bucket (+5 boost) underperforms   │
│                                    neutral in every base-coverage band       │
│                                    tested. Same contaminated-source pattern  │
│                                    as WHIP (removed Session 15). Rebuild     │
│                                    scoped, NOT implemented — still ACTIVE    │
│                                    and unchanged in production. See          │
│                                    ARCHITECTURE_DECISIONS.md §29.            │
│ WHIP Rank Signal (hits):        ✅ REMOVED (Session 15)                      │
│ K/9 Rank Signal (SO/over):      ⚠️  ACTIVE — same data-source risk as ERA   │
│                                    flagged Session 21 (same underlying       │
│                                    fetch function) but controlled testing    │
│                                    came back mixed/inconclusive, not         │
│                                    clearly inverted. Monitoring, no action.  │
│ Lineup Stability:               ⚠️  WAS SILENTLY DEAD ALL SEASON — DB       │
│                                    persistence bug fixed Session 21 (column  │
│                                    never in the INSERT statement, 100% NULL  │
│                                    across 18,356 rows). Persistence fixed;   │
│                                    whether the upstream Step 5b filter has   │
│                                    actually been executing is UNCONFIRMED —  │
│                                    needs a Railway log check.                │
│ Slot Gate (soft, -8):           ✅ REMOVED (Session 16)                      │
│ Score differentiation (SO/over):⚠️  Still unresolved (carried, High         │
│                                    priority) — Session 21's 7/17-19 check    │
│                                    didn't add a clean additional read either │
│                                    direction (51.5% one week, 68.4% next).   │
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
│ SPORTSGAMEODDS API USAGE — REVISED Session 23                                  │
│ Billing model:                   ✅ CONFIRMED PER-EVENT, empirically —       │
│                                    /account/usage delta = 18 for 18 events    │
│                                    returned (ratio 1.00), vs. 25,486 total    │
│                                    markets in those same events (ratio        │
│                                    0.0007). Prior evidence (local event-count │
│                                    logging) could NOT have distinguished      │
│                                    per-event from per-market billing — this   │
│                                    session ran the actual account-counter     │
│                                    test instead of trusting it further.       │
│ Pipeline schedule:                ✅ CUT 3→2 runs/day (9 AM + 5:30 PM only,  │
│                                    12 PM dropped) — src/web/server.py's       │
│                                    _PIPELINE_SCHEDULE. Real 7-day usage data: │
│                                    12 PM slot averaged 14.6/39.4 objects/day  │
│                                    (~37%). Post-cut projection: ~744/month,   │
│                                    vs. the 2,500/month Amateur-tier cap       │
│                                    taking effect 2026-08-01.                  │
│ Account downgrade status:       🔲 STILL NOT CONFIRMED — carried multiple    │
│                                    sessions, user action pending, deadline    │
│                                    2026-08-01. Watch usage the first few days │
│                                    after downgrade to confirm the projection. │
├────────────────────────────────────────────────────────────────────────────────┤
│ PROP-LINE CAPTURE (mlb_prop_legs_history) — NEW Session 23                     │
│ Purpose:                         Full, non-qualified-filtered prop-line +    │
│                                    game-line capture — an isolated           │
│                                    calibration dataset for a ground-up       │
│                                    rebuild, NOT a production/shadow signal.  │
│ Capture module:                  ✅ src/pipelines/prop_legs_capture.py,     │
│                                    wired into main.py's 9 AM-only path       │
│                                    (skip_resolution=False gate) — reuses     │
│                                    that run's already-fetched sgo_games/     │
│                                    all_sgo_props/schedule, ZERO new SGO      │
│                                    API calls.                                │
│ Markets captured:                 Game lines (moneyline/spread/total,       │
│                                    market_scope='game') + batter hits/       │
│                                    strikeouts(over-only)/totalBases +        │
│                                    pitcher strikeouts (market_scope=         │
│                                    'player', player_role disambiguated       │
│                                    independently of get_player_props()'s     │
│                                    own normalization — see architecture doc) │
│ Schema fixes (live migration):   ✅ player_id nullable, market_scope +      │
│                                    player_role columns + CHECK constraints,  │
│                                    plus a partial unique index for the       │
│                                    game-scope (player_id IS NULL) case —     │
│                                    without it, game-level rows would never   │
│                                    have deduped across runs (Postgres        │
│                                    treats every NULL as distinct).           │
│ Resolution:                       ✅ resolve_prop_legs_history(), chained   │
│                                    into daily_reference_refresh.py right     │
│                                    after it backfills yesterday's game logs  │
│                                    — reads its own uncommitted same-         │
│                                    transaction writes. Isolated — writes     │
│                                    ONLY to mlb_prop_legs_history.            │
│ Validation:                       ✅ Resolution: 7/7 synthetic test cases   │
│                                    passed against a real completed game     │
│                                    with known outcomes. Capture: validated   │
│                                    via isolated test script, 2 real bugs     │
│                                    found and fixed (ON CONFLICT partial-     │
│                                    index target, Athletics team-abbrev       │
│                                    mismatch) — see DIAGNOSTIC / LOGGING      │
│                                    GAPS below and ARCHITECTURE_DECISIONS.md. │
│ Production wiring status:        ⚠️  Tested via standalone scripts only —  │
│                                    the real main.py run_pipeline() code     │
│                                    path itself not yet exercised live.       │
├────────────────────────────────────────────────────────────────────────────────┤
│ SHADOW PIPELINE                                                                │
│ Shadow Pipeline:                ✅ RUNNING AFTER EVERY PRODUCTION RUN        │
│ Calls new builder automatically:✅ run_enriched_pipeline.py calls the same   │
│                                    build_parlays() as production — Session   │
│                                    18's redesign applies here with no        │
│                                    separate change needed                    │
│ TB/under construction question: ⚠️  Session 21: builder reverted back to    │
│                                    fixed-4-leg (see PARLAY BUILDER section   │
│                                    above) — the original 15.8%/26.7%         │
│                                    with/without-TB numbers, generated under  │
│                                    the old fixed-4-leg builder, may be valid │
│                                    again without a rerun. Confirm before     │
│                                    relying on them for a promotion decision. │
├────────────────────────────────────────────────────────────────────────────────┤
│ REFERENCE DATA SCHEMA — NEW (Session 22)                                       │
│ Tables:                          ✅ mlb_teams, mlb_players, mlb_games,       │
│                                    mlb_player_batting_logs,                  │
│                                    mlb_player_pitching_logs,                 │
│                                    mlb_team_standings(+_splits),             │
│                                    mlb_player_season_batting_stats/          │
│                                    _pitching_stats — applied directly to     │
│                                    Supabase before this session, no repo     │
│                                    migration file. Additive only — does not  │
│                                    touch mlb_scored_legs or any existing     │
│                                    production table.                        │
│ Season-to-date backfill:         ✅ COMPLETE — 124 game dates (2026-03-25   │
│                                    season opener through 2026-07-29),        │
│                                    1,613 games, ~34,100 batting-log rows,    │
│                                    ~13,600 pitching-log rows, 1,335 players  │
│ Data-integrity validation:       ✅ 3 independent box-score spot-checks     │
│                                    matched the live API exactly;             │
│                                    game_pk cross-check with mlb_scored_legs: │
│                                    1,300/1,320 matched (remainder is a       │
│                                    found-not-fixed mlb_scored_legs bug, see  │
│                                    DIAGNOSTIC / LOGGING GAPS below)          │
│ Season-stats/standings snapshot: ✅ scripts/backfill_reference_snapshots.py │
│                                    (new) — relies on MLB's own              │
│                                    playerPool=QUALIFIED filter rather than   │
│                                    reimplementing the PA/IP threshold        │
│                                    client-side (confirmed live to match)     │
│ Daily refresh:                   ⚠️  scripts/daily_reference_refresh.py    │
│                                    (new) written, dry-run validated, wired   │
│                                    into server.py's scheduler (3 AM ET) —    │
│                                    NOT YET DEPLOYED, nothing committed this  │
│                                    session. Standings/leaderboard snapshots  │
│                                    stay frozen at 2026-07-29 until pushed.   │
├────────────────────────────────────────────────────────────────────────────────┤
│ DIAMOND LINE DASHBOARD (dashboard_api/) — REWORK Session 22                    │
│ Standings page:                  ✅ GET /api/standings + static/            │
│                                    standings.html — validated field-for-     │
│                                    field against the operator's own MLB.com  │
│                                    screenshot, including a found-and-fixed   │
│                                    WCGB sign bug (raw API returns literal    │
│                                    '+7.0' for wildcard-holding teams, a      │
│                                    naive float() cast was collapsing it)     │
│ Leaderboard pages:                ✅ GET /api/leaderboards/hitting+pitching │
│                                    + static/leaderboards.html, sortable —    │
│                                    pitching output near-exact match on       │
│                                    every column vs. operator's screenshot    │
│ season_stats.py:                 ✅ Swapped from a live MLB API call per    │
│                                    player per request to DB-first reads      │
│                                    from the new reference tables, with a     │
│                                    live-API fallback preserved for players   │
│                                    not in the qualified-only reference       │
│                                    tables (avoids a coverage regression)     │
│ Frontend architecture finding:   ⚠️  static/support.js (68K) is a          │
│                                    GENERATED file — no dc-runtime/ source    │
│                                    exists anywhere in the repo. New pages    │
│                                    built as separate static files instead    │
│                                    of extending the existing bundle — see    │
│                                    ARCHITECTURE_DECISIONS.md §31.            │
│ Step 4 (drill-down cards):       🔲 DEFERRED — operator's choice, not       │
│                                    blocked on anything found this session    │
├────────────────────────────────────────────────────────────────────────────────┤
│ DIAGNOSTIC / LOGGING GAPS                                                       │
│ get_totals_props() key prefix:  ⚠️  NEW FINDING (Session 23) — searches for  │
│                                    'runs-*' keys, live SGO responses use     │
│                                    'points-*'. Confirmed dormant (never      │
│                                    called elsewhere in the codebase, via     │
│                                    grep) — not actively broken, just never   │
│                                    correct. Not fixed (nothing depends on    │
│                                    it); prop_legs_capture.py's own game-line │
│                                    parsing uses the correct prefix directly. │
│ source label inconsistency:     ⚠️  NEW FINDING (Session 23) —              │
│                                    mlb_parlay_recommendations_v2.source is   │
│                                    literally 'midday'/'evening' for those    │
│                                    scheduled slots (raw scheduler label      │
│                                    passed straight through), not             │
│                                    'auto_12pm'/'auto_530pm' as documented in │
│                                    SUPABASE_SCHEMA_REFERENCE.md. The 9 AM    │
│                                    slot passes no explicit source and        │
│                                    correctly falls through to an hour-based  │
│                                    fallback; the other slots don't. Pre-     │
│                                    existing, unrelated to this session's     │
│                                    changes. Low priority now that 'midday'   │
│                                    no longer fires post-schedule-cut.        │
│ mlb_scored_legs.game_pk mismatch:⚠️  NEW FINDING (Session 22) — 8/1,320     │
│                                    checked game_pks belong to future,        │
│                                    unplayed games (confirmed live), not the  │
│                                    game actually on that leg's run_date.     │
│                                    Flagged, not root-caused or fixed —       │
│                                    mlb_scored_legs wasn't touched this       │
│                                    session per the read-only backfill scope │
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
│                                    Latest confirmed commit: 65ce276 (Jul 23) │
│                                    — dashboard_api Phase 1 (undocumented     │
│                                    until this update, see Session 22 note    │
│                                    in SESSION_HANDOFF.md). Session 22's own  │
│                                    work (backfill scripts, dashboard         │
│                                    additions, server.py scheduler wiring)    │
│                                    AND Session 23's work (SGO billing        │
│                                    verification, schedule cut, prop_legs_    │
│                                    capture.py) are NOT yet committed or      │
│                                    deployed — about to be, together.         │
│ Base commit at session start:    3d7aabc (Jul 7, previously undocumented —  │
│                                    documented this session; also resolved   │
│                                    the long-open "unknown commit 85b5bd5"    │
│                                    mystery — confirmed docs-only, no code)   │
│ pytest:                          ✅ INSTALLED and working as of Session 21 — │
│                                    76 tests passing (62 original + 14 new)  │
│ sklearn Version Warning:        ⚠️  1.7.2→1.8.0 mismatch (non-fatal, carried)│
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🔧 July 29, 2026 (Session 23): SGO Billing Verification + Schedule Cut + Full Prop-Line Capture — NOT YET DEPLOYED

**Work.** Second, distinct handoff on the same day as Session 22: (1) empirically verify SGO's per-event vs. per-market billing before relying on it further, (2) cut the pipeline schedule from 3 runs/day to 2 ahead of the 2026-08-01 SGO Pro→Amateur downgrade, (3) build full prop-line capture into the (Session-22-created, still-empty) `mlb_prop_legs_history` table as an isolated ground-up-rebuild calibration dataset. Full detail in `SESSION_HANDOFF.md`'s Session 23 entry.

**Task 1.** Built a real test (`scripts/verify_sgo_billing.py`) hitting SGO's own `/account/usage` counter before/after one `/events` call — delta of 18 matched 18 events returned exactly, vs. 25,486 total markets in those events. Per-event billing confirmed unambiguously. Also found (not fixed) that `get_totals_props()` searches the wrong key prefix — dormant/unused code, not live-broken.

**Task 2.** Removed the 12 PM slot from `src/web/server.py`'s `_PIPELINE_SCHEDULE`. Verified against real 7-day usage data (not just projection): 12 PM averaged ~37% of daily SGO usage; post-cut projects to ~744/month, well under the 2,500 cap.

**Task 3.** Fixed `mlb_prop_legs_history`'s schema via live migration (nullable `player_id`, new `market_scope`/`player_role` columns, a partial unique index for game-scope dedup that the literal spec would have missed). Built `src/pipelines/prop_legs_capture.py` (capture, wired into `main.py`'s 9 AM path, zero new SGO calls; resolution, chained into `daily_reference_refresh.py`). Validated live: resolution 7/7 test cases passed; capture found and fixed two real bugs (an `ON CONFLICT` partial-index target bug, and an Athletics-relocation team-abbreviation bug) before landing clean (36 game lines + 176 then 60 more player legs captured across two runs, natural-key upsert-and-append confirmed working).

**Not deployed.** Nothing from Session 22 or 23 is committed as of this doc update — about to be, together.

### 🔧 July 29, 2026 (Session 22): Reference-Data Schema Backfill + Diamond Line Dashboard Rework — NOT YET DEPLOYED

**Work.** Two-part handoff: (1) get an already-drafted, never-run reference-data backfill script working and run it season-to-date, plus write the season-stats/standings snapshot and daily-refresh pieces that hadn't been drafted; (2) scope, then build, a rework of the Diamond Line dashboard (`dashboard_api/`) to surface the new reference data. Full detail (including every field-level validation performed) is in `SESSION_HANDOFF.md`'s Session 22 entry — this section is the compressed version.

**Backfill.** Reviewed the draft script against LIVE `statsapi.mlb.com` responses before running it — found and fixed three real bugs (batting logs gated on a field that's never actually returned by `boxscore_data()`, so none would have inserted; `is_starter` gated on another field that's likewise never present; a real FK column, `opposing_pitcher_id`, never populated). Ran season-to-date: 124 game dates, 1,613 games, ~34,100 batting-log rows, ~13,600 pitching-log rows, 1,335 players. Wrote and ran the season-stats/standings snapshot script (discovered MLB's own API already does the qualified-players filtering the handoff asked to reimplement) and the daily-refresh script (wired into `server.py`'s scheduler, not yet deployed). Found, but did not fix (out of scope), a pre-existing data-quality bug in `mlb_scored_legs` — 8 of 1,320 checked `game_pk` values point at future, unplayed games.

**Dashboard.** Presented a scoping plan before writing code — approved, then built steps 1-3 of the agreed 4-step sequence: Standings page, `season_stats.py` swapped off live per-request API calls (with a live fallback preserved for non-qualified players, to avoid a coverage regression), Hitting/Pitching leaderboard pages. All three validated against the operator's own MLB.com screenshots, field-for-field. Found `static/support.js` is a generated file with no committed source (`dc-runtime/` doesn't exist in the repo) — this changed the plan to build new pages as separate static files rather than extending the existing bundle.

**Not deployed.** Nothing from this session is committed. All changes sit in the operator's WSL clone working tree as of this doc update.

### 🔧 July 20, 2026 (Session 21): Post-Break Investigation — Builder Leg-Count Revert + Two Signal-Pipeline Bug Fixes + Pitcher ERA Audit

**Investigation.** First review since the All-Star break. Operator requested a 3-day production/shadow performance check, suspecting the pre-break Session 19/20 changes were the cause of a perceived decline. Git history ruled that out directly — no code shipped between 7/10 and 7/20 except a docs-only commit. The real cause traced to the Session 18 builder redesign: avg legs/parlay jumped from a fixed 4.00 to 4.4-4.5 exactly at the 7/8 deploy, and actual EV per $1 staked went from +$0.128 (pre-redesign 4-leg, n=486) to -$0.42/-$0.66 (post-redesign 5-leg/4-leg). A systematic audit of every scoring adjustment (controlling for the selection-bias risk of the `composite_score >= 65` gate) found `lineup_consistency` completely dead due to a DB-persistence bug, the pitcher ERA adjustment inverted due to a contaminated data source, and a missing sample-size floor on the streak/consistency signal.

**Fixes shipped (branch `fix/leg-cap-lineup-consistency-streak-floor`, not yet merged as of this doc update):**
1. `src/engine/parlay_builder.py` — `MAX_LEGS` 6→4, reverting to fixed-4-leg parlays. Floor-only-odds philosophy (no ceiling) from Session 18 retained.
2. `src/utils/db.py` — `log_scored_legs()`'s INSERT for `mlb_scored_legs` now includes `lineup_consistency` in the column list, values tuple, and `ON CONFLICT` clause. Had been silently dropped since project inception (100% NULL, 18,356 rows).
3. `src/engine/coverage.py` — `MIN_RECENT_GAMES = 5` floor added to `coverage_recent_10` in both `_hitter_coverage()` and `_pitcher_coverage()`.

**Explicitly not fixed this session:** the pitcher ERA adjustment, confirmed inverted via controlled base-coverage-banded analysis (same contaminated-source pattern as the WHIP signal removed Session 15), was deliberately left active pending a proper rebuild (recent-starts ERA via a new `get_pitcher_game_log()`) rather than removed outright — operator wants the signal retained, not deleted. See `ARCHITECTURE_DECISIONS.md` §29 for the full rebuild scope.

**Tests:** `tests/test_bug_fixes.py` (new, 14 tests) — 76/76 total passing.

**Known gaps, both high priority for Session 22:**
1. Branch not yet merged/deployed as of this doc update — confirm this first.
2. Whether the leg-cap revert fully restores pre-redesign EV is unconfirmed — a same-session simulation suggested a possible partial gap (-$0.25 to -$0.34 vs. the historical +$0.128), but the simulation itself was thin/noisy (two windows disagreed by ~10 points of win rate). Watch live results over 1-2 weeks.
3. `lineup_consistency`'s persistence is fixed, but whether the upstream Step 5b filter in `main.py` has actually been executing successfully (vs. silently hitting its wrapping `try/except`) is unconfirmed — needs a Railway log check.

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

### Parlay Builder (parlay_builder.py) — REDESIGNED Session 18, LEG COUNT REVERTED Session 21
| Component | Status | Notes |
|---|---|---|
| Leg count | ✅ Fixed 4 (reverted from 4-6, Session 21) | 4-6 range confirmed -EV (-$0.42 to -$0.66/$1) vs. fixed-4's +$0.128/$1; reverted |
| Combined odds | ✅ +400 floor only (unchanged from Session 18) | No ceiling — this half of the Session 18 redesign was kept |
| Selection method | ✅ Greedy by composite_score | Was branch-and-bound combinatorial search pre-Session 18 |
| Max legs/game | ✅ 2, unchanged | |
| Player diversity | ✅ Unchanged | Both intra- and cross-parlay caps preserved |
| Regression tests | ✅ 76 passing (62 + 14 new, Session 21) | `tests/test_bug_fixes.py` covers the leg-count boundary behavior |
| Live performance data | ⚠️ Pending deploy | Revert not yet live as of this doc update; watch 1-2 weeks post-deploy |

### Manual Parlay Dashboard (manual.html, server.py, db.py) — NEW Session 18
| Component | Status | Notes |
|---|---|---|
| Data display | ✅ Working | Field-name bugs fixed commit c920f32 |
| Auth | ✅ Working | Hardened + Decimal bug fixed, reuses existing password |
| Submission | ✅ Working | Server-side re-validation, non-blocking floor |
| Resolution | ✅ Confirmed via code, ❌ not tested live | No source filter in resolver — should just work |
| Layout/sticky header | ⚠️ Fix shown, push unconfirmed | Verify Session 19 |

### Scoring Signal Integrity (simple_scorer.py inputs) — AUDITED Session 21
| Signal | Status | Notes |
|---|---|---|
| `lineup_consistency` | ⚠️ Persistence fixed, upstream filter unconfirmed | Was 100% NULL, all season — `db.py` INSERT fix Session 21. Whether the Step 5b filter itself has been executing needs a Railway log check. |
| Pitcher ERA (hits props) | ❌ Confirmed inverted, not fixed | Same contaminated data source as removed WHIP signal. Rebuild scoped (`ARCHITECTURE_DECISIONS.md` §29), not implemented — still active, unchanged. |
| K/9-rank (SO/over) | ⚠️ Same source risk, inconclusive evidence | Monitoring only, no action taken |
| Streak/consistency gap | ✅ Sample floor added | `MIN_RECENT_GAMES = 5` in `coverage.py`, both hitter and pitcher paths |

### Coverage Gates
| Prop / Direction | Gate | Ceiling | Status |
|---|---|---|---|
| hits/over | 65% floor | ~80% ceiling | ⚠️ Ceiling still pending, reconfirmed Session 18 |
| SO/over | 65% floor | None | ✅ No ceiling confirmed |
| hits/under | 65% floor | None | ⚠️ Very narrow eligible pool (1-3 players/day) — characterized Session 18, not a gate change |
| TB/under (shadow) | 40% floor | ~75% (tentative) | ⚠️ Promotion analysis stale — rerun under new builder before deciding |

### Reference Data Schema (mlb_teams, mlb_players, mlb_games, mlb_player_batting_logs/_pitching_logs, mlb_team_standings(+_splits), mlb_player_season_batting_stats/_pitching_stats) — NEW Session 22
| Component | Status | Notes |
|---|---|---|
| Season-to-date backfill | ✅ Complete, validated | 124 dates, 1,613 games, ~34,100 batting rows, ~13,600 pitching rows, 1,335 players. 3 independent live spot-checks matched exactly. |
| Season-stats/standings snapshot | ✅ Complete, validated | `scripts/backfill_reference_snapshots.py` — relies on MLB's own `playerPool=QUALIFIED` filter, confirmed to match the intended PA/IP threshold |
| Daily refresh | ⚠️ Written, not deployed | `scripts/daily_reference_refresh.py`, wired into `server.py`'s scheduler (3 AM ET) — dry-run validated, now also resolves `mlb_prop_legs_history` (Session 23), but nothing committed/pushed yet |
| mlb_scored_legs.game_pk integrity | ⚠️ 8/1,320 mismatches found | Pre-existing bug in `mlb_scored_legs`, unrelated to this backfill — flagged, not fixed (out of scope) |

### SGO Cost Management — REVISED Session 23
| Component | Status | Notes |
|---|---|---|
| Billing model | ✅ Confirmed per-event | `/account/usage` delta test: 18 delta = 18 events (ratio 1.00) vs. 25,486 markets (ratio 0.0007) |
| Pipeline schedule | ✅ Cut 3→2 runs/day | `src/web/server.py` `_PIPELINE_SCHEDULE` — 12 PM slot removed |
| Projected usage post-cut | ✅ ~744/month | Real 7-day data, not just projection; cap is 2,500/month starting 8/1 |
| Tier downgrade | 🔲 Not yet confirmed | Deadline 2026-08-01, user action outside the codebase |

### Prop-Line Capture (mlb_prop_legs_history) — NEW Session 23
| Component | Status | Notes |
|---|---|---|
| Schema (player_id nullable, market_scope, player_role, partial unique index) | ✅ Applied live | Migration applied directly to Supabase, no repo migration file |
| Capture (game lines + player props) | ✅ Built, validated via standalone test | `src/pipelines/prop_legs_capture.py`, zero new SGO calls, wired into `main.py`'s 9 AM path |
| Resolution | ✅ Built, validated (7/7 test cases) | `resolve_prop_legs_history()`, chained into `daily_reference_refresh.py` |
| Real production run_pipeline() exercise | ⚠️ Not yet done | Only tested via isolated scripts — watch the first live 9 AM run post-deploy |
| Isolation from production/shadow | ✅ Confirmed by design | Writes only to `mlb_prop_legs_history`/`mlb_teams`/`mlb_players`/`mlb_games` |

### Diamond Line Dashboard (dashboard_api/) — REWORK Session 22
| Component | Status | Notes |
|---|---|---|
| Standings page | ✅ Working, validated | `GET /api/standings` + `static/standings.html` — field-for-field match against operator's screenshot, WCGB sign bug found and fixed |
| Hitting/Pitching leaderboards | ✅ Working, validated | `GET /api/leaderboards/hitting`+`/pitching` + `static/leaderboards.html`, sortable — near-exact match on pitching, hitting matched with expected drift |
| `season_stats.py` | ✅ Reworked, validated | DB-first from reference tables, live-API fallback preserved for non-qualified players (no coverage regression) |
| Frontend (`support.js`) | ⚠️ Confirmed unmaintainable as-is | Generated file, no `dc-runtime/` source in repo — new pages built as separate static files instead, see `ARCHITECTURE_DECISIONS.md` §31 |
| Player/team drill-down cards | 🔲 Not built (step 4) | Deferred by operator choice this session, not blocked |
| Deploy status | ⚠️ Not deployed | Nothing from this session committed/pushed |

---

## Pending Code Changes

| Item | File | Priority |
|---|---|---|
| Commit and push Sessions 22+23's work | `scripts/`, `dashboard_api/`, `src/pipelines/prop_legs_capture.py`, `src/web/server.py`, `main.py` | **High — being done now. Daily reference-data refresh and prop-line capture are both inert until this happens.** |
| Watch first live 9 AM prop-line capture run | — (verification only) | **High — new Session 23, real `run_pipeline()` wiring not yet exercised live** |
| Confirm SGO tier downgrade lands cleanly 8/1 | — (verification only) | **High — new Session 23, deadline 2026-08-01** |
| Build Diamond Line dashboard step 4 (drill-down cards) | `dashboard_api/` (new) | Medium — deferred by operator choice Session 22, not blocked |
| Root-cause the mlb_scored_legs game_pk mismatch | `mlb_scored_legs` (production table, not touched Session 22) | Medium — new Session 22, found via live cross-check, 8/1,320 affected |
| Fix source labeling inconsistency ('midday'/'evening' vs. documented 'auto_12pm'/'auto_530pm') | `main.py` `run_pipeline()` | Low — new Session 23, pre-existing, 'midday' no longer fires post-schedule-cut |
| Fix get_totals_props() wrong key prefix | `src/apis/sportsgameodds.py` | Low — new Session 23, confirmed dormant/unused |
| Merge Session 21 branch to master and deploy | `fix/leg-cap-lineup-consistency-streak-floor` | **High — carried again, Sessions 22/23 did not touch this branch. Blocks everything below needing live data.** |
| Confirm lineup_consistency Step 5b filter is actually executing | — (verification only, check Railway logs) | **High — new Session 21** |
| Watch leg-cap revert live EV over 1-2 weeks | — (verification only) | **High — new Session 21** |
| Build + backtest pitcher ERA signal rebuild (recent-starts ERA) | `src/apis/matchup.py` (new `get_pitcher_game_log()`), `simple_scorer.py` | **High — scoped Session 21, explicitly deferred, not started** |
| Re-validate lineup_consistency 0.70 threshold once data accumulates | — (analysis only) | Medium — new Session 21, needs a few weeks of post-fix data |
| Monitor K9-rank signal with more data | — (analysis only) | Medium — new Session 21, same source risk as ERA, evidence inconclusive |
| Confirm sticky-header fix commit + push status | — (verification only) | High — carried since Session 19, still not confirmed |
| Complete manual-pick end-to-end test | — (verification only) | **High — carried since Session 19, still not done** |
| Rerun/confirm TB/under construction-strategy analysis | `parlay_builder.py` / analysis only | Medium — may be moot now that builder reverted to fixed-4-leg; confirm before rerunning |
| Recheck SO/over pool-composition softening | — (verification only) | High — carried, unresolved (Session 21 didn't add a clean read either direction) |
| Cancel SGO Pro subscription (account-level, not code) | — (manual action) | High — carried multiple sessions, not yet confirmed |
| Add hits/over coverage ceiling at ~80% | `main.py` | High — data reconfirmed Session 18, still not implemented |
| Fix void_reason logging gap | `parlay_outcome_resolver.py` / `outcome_resolver.py` | Medium — carried, no action taken |
| Fix sklearn version mismatch | model retraining | Low — non-fatal |
| Project file cleanup (retire stale docs) | Project Knowledge | Low — carried |

---

**Build Status:** ✅ HEALTHY — Sessions 22 and 23's work (reference-data backfill, Diamond Line dashboard, SGO billing verification + schedule cut, full prop-line capture) validated and ready, about to be committed together; Session 21's fixes still sitting on an unmerged branch, unrelated and untouched
**Last Deployment:** July 23, 2026 (`65ce276`, dashboard_api Phase 1 — previously undocumented, see Session 22 note in `SESSION_HANDOFF.md`) is still the last *deployed* change. Session 21's fixes remain on an unmerged branch; Sessions 22 and 23's combined work is committed nowhere yet as of this doc update.
**Next Review:** Commit and push Sessions 22+23's work first thing (nothing daily-refreshes or captures prop lines until this happens) / watch the first live 9 AM capture run and the 8/1 SGO tier downgrade / decide whether to build dashboard step 4 next or return to the Session 21 queue (merge that branch, confirm lineup_consistency filter via Railway logs, watch leg-cap-revert live EV, pitcher ERA rebuild, manual-pick end-to-end test — all carried, now behind two sessions' worth of newer work)
