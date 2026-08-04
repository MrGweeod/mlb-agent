# MLB Parlay Agent — Session Handoff
**Last Updated:** August 4, 2026 (Session 26 — fixed the parlay builder's zero-recovery bug: a top-4-by-score pick that missed the +400 odds floor now retries via bounded single-leg swaps instead of giving up; live-verified producing 5 real parlays)

## Current Status
✅ **OPERATIONAL — PARLAY BUILDER FLOOR-RECOVERY FIX DEPLOYED AND CONFIRMED LIVE (SESSION 26)**
✅ **`build_parlays()` picked legs by a single greedy pass sorted only by `composite_score`, checked the +400 odds floor only after 4 legs were already locked in, and gave up entirely (for that slot AND every remaining slot in the batch) if the pick missed.** Reproduced live on 2026-08-04: top-4 landed at +337, zero parlays despite 36 eligible legs in the pool — this is what Session 25's fix left unresolved (see the now-superseded caveat below). Fixed via `_attempt_swap_recovery()`: when the top-4 pick misses the floor, tries single-leg swaps against every remaining eligible alternative in the pool (bounded to `len(legs) * SWAP_CANDIDATE_LIMIT` attempts), keeping the floor-clearing swap with the highest total `composite_score`. Full detail below and `ARCHITECTURE_DECISIONS.md` §38.
✅ **A real gap was found and fixed via live-data testing before trusting the first version of this fix.** The initial implementation capped swap candidates to the next 10 best-*scored* alternatives (per the task's own suggested example). Replaying today's actual pool showed this missed a real floor-clearing combination (+725) because the legs with the best odds ranked 18th-33rd by score, not in the top 10 — composite_score and odds aren't correlated. Widened the search to the full remaining pool (`SWAP_CANDIDATE_LIMIT` raised from 10 to 200, still a bounded safety cap, not a score cutoff) before shipping.
✅ **Live-verified against the real database, not just logs.** Triggered the real `run_morning_pipeline()` (the exact function the scheduler calls) on the deployed fix: **5 parlays written to `mlb_parlay_recommendations_v2`/`mlb_parlay_legs_v2`** for `run_date = 2026-08-04` (+450, +402, +421, +413, +427 — all clearing the floor, hitting the top of the 3-5 target), confirmed via direct SQL query. Every single parlay used the swap-recovery path, pairing 3 short-odds/high-score legs with one longer-odds/lower-score leg (e.g. Jake Cronenworth -127, Ryan Waldschmidt -142, Trea Turner -137) — exactly the intended behavior.
✅ ~~Caveat: neither Session 25 verification run actually hung~~ — **superseded by Session 26:** this session ran the real pipeline multiple additional times on the deployed stall fix with no hang, and the underlying gap that was actually blocking recommendations (this parlay-builder bug, not a residual stall) is now also fixed and live-confirmed. The next real scheduled run (9 AM/5:30 PM ET) is still the final confirmation neither session has directly observed — see Pending Items.
✅ ~~Not yet observed post-fix: a saved parlay recommendation~~ — **RESOLVED Session 26:** 5 real parlay rows confirmed written today, see above.
✅ **`opposing_pitcher_id` was being silently dropped before `mlb_training_data`'s INSERT** (same class of bug as Session 21's `lineup_consistency` fix) — `enrich_legs.py` computes it and `mlb_scored_legs` already persisted it correctly, but `log_training_data_legs()` never included it. Fixed in `src/utils/db.py`.
✅ **Point-in-time batter/pitcher stat backfill built** (`scripts/backfill_point_in_time_stats.py`, new) — incremental daily cumulative-stat tables (`mlb_player_batting_cumulative`/`_pitching_cumulative`) plus a fill for `mlb_training_data.pt_role`/`pt_*`/`opp_pt_*`, chained into `daily_reference_refresh.py`. A real coupling bug (own-role fill and opposing-pitcher fill were incorrectly gated together) was caught via live-data testing and fixed before being trusted — see Session 24 entry below and `ARCHITECTURE_DECISIONS.md` §35.
✅ **Ran the backfill once against production**, results verified by direct query rather than assumed: `pt_role` 98.8% covered (matches historical rate, 0 new fills — remainder is legacy non-numeric IDs, correctly out of scope); `opp_pt_era` 100% filled once season-opener/pitcher-debut rows with zero prior in-season data (confirmed structurally unfillable) are excluded from the denominator.
✅ **Coverage-threshold-vs-matchup-quality analysis completed** (read-only, no scoring changes) — see `docs/COVERAGE_VS_MATCHUP_ANALYSIS.md` and `ARCHITECTURE_DECISIONS.md` §36. Found the `coverage_overall` gate structurally excludes true low-coverage legs for hits/over and batter-K (untestable for those bet types from `mlb_training_data`); totalBases showed real support for the operator's low-coverage/good-matchup hypothesis; also found `coverage_overall`/`composite_score` only reflect the current scoring pipeline from 2026-06-09 onward (analysis restricted accordingly).
🔲 **Pending: re-run coverage-vs-matchup analysis (target 8/6/2026)** once `mlb_prop_legs_history` has ~1 week of ungated data. See `ARCHITECTURE_DECISIONS.md` §36 for full context and first-pass results.
✅ **RESOLVED Session 25: `mlb_parlay_legs_v2`'s no-new-legs-since-2026-07-23 gap was the silent pipeline stall** — see the top of this section and `ARCHITECTURE_DECISIONS.md` §37 for the full root-cause and fix.
✅ **SGO billing empirically confirmed per-event, not per-market.** The handoff's own justification (`mlb_sgo_request_log.entities_consumed` tracking game count) turned out to be weaker evidence than it looked — that field is a LOCAL count of `/events` response items, which trivially equals game count regardless of how SGO actually bills, since `/events` returns one object per game either way. Real test: hit SGO's own `/account/usage` counter immediately before and after one real `/events` call — delta was **18**, exactly matching **18 events returned**, while total markets across those same 18 events was **25,486** (delta/markets ratio 0.0007). Unambiguous per-event billing confirmation.
✅ **Schedule cut from 3 runs/day (9 AM/12 PM/5:30 PM) to 2 (9 AM/5:30 PM)** — `src/web/server.py`'s `_PIPELINE_SCHEDULE`. Real 7-day historical data (not just projection): 12 PM slot averaged 14.6/39.4 objects/day (~37%); post-cut projects to **~744 objects/month**, well under the 2,500/month Amateur-tier cap taking effect 2026-08-01.
✅ **`mlb_prop_legs_history` schema fixed via live migration** — `player_id` made nullable, `market_scope`('player'/'game') and `player_role`('batter'/'pitcher'/NULL) columns added with CHECK constraints enforcing they stay consistent with each other. Also added a partial unique index for the game-scope (`player_id IS NULL`) case — the original single UNIQUE constraint would never have deduped game-level rows across runs, since Postgres treats every NULL as distinct for uniqueness purposes; caught and fixed before this went anywhere near production.
✅ **New `src/pipelines/prop_legs_capture.py`** — full prop-line capture (game lines: moneyline/spread/total; player props: batter hits/strikeouts/totalBases, pitcher strikeouts) wired into `main.py`'s 9 AM-only path (`skip_resolution=False` gate), reusing the SAME already-fetched `sgo_games`/`all_sgo_props`/`schedule` from that run's existing Steps 2-3 — **zero new SGO API calls**. Plus `resolve_prop_legs_history()`, chained into `scripts/daily_reference_refresh.py` right after it backfills yesterday's game logs (the exact moment the data it needs first becomes available). Fully isolated — writes only to `mlb_prop_legs_history`/`mlb_teams`/`mlb_players`/`mlb_games`, never `mlb_scored_legs` or any recommendation/training table.
✅ **Both new pipelines validated against live data, two real bugs found and fixed in the process:**
&nbsp;&nbsp;&nbsp;**1. Resolution: 7/7 synthetic test cases passed** (`scripts/test_prop_legs_resolution.py`, using a real already-backfilled game with known outcomes — Freddy Peralta 7 K, Bo Bichette 0-for-4, home won 11-7 — covering pitcher-K, batter-hits, moneyline, and total resolution logic).
&nbsp;&nbsp;&nbsp;**2. Capture: found and fixed an `ON CONFLICT` bug** — Postgres requires a partial unique index's `WHERE` predicate to be restated in the `ON CONFLICT` clause itself, not just the column list; omitting it raised "no unique or exclusion constraint matching" on every single game-scope upsert on the first live test run. Also found and fixed a team-abbreviation bug: the 2026 Athletics relocation means their schedule-side full name is now literally `"Athletics"` (not `"Oakland Athletics"`), which fell through to a wrong default (`"ATH"`) instead of matching SGO's actual short name (`"OAK"`). After both fixes: 36 game-line legs + 176 then 60 more player legs captured cleanly across two live runs, with `odds_history` correctly appending and `first_seen_*`/`last_recorded_*` behaving exactly as specified on the second run's re-upsert.**
⚠️ **A live test surfaced a real, separate bug in existing (but unused/dead) code — not fixed, just found and worked around.** `get_totals_props()` in `src/apis/sportsgameodds.py` searches for `runs-*` market keys; SGO's actual live keys use a `points-*` prefix (confirmed via raw response dump — `points-all-game-ou-over`, `points-away-game-ml-away`, etc.). That function is never called anywhere else in the codebase (confirmed via repo-wide grep), so this bug has been dormant, not corrupting anything live. The new capture module's own game-line parsing uses the confirmed-correct `points-` prefix directly rather than reusing or patching that function — `get_totals_props()` itself is untouched, bug and all.
🔲 **Pending: commit and push everything from Sessions 22, 23, and 24 together** — nothing from any of the three sessions has been committed yet as of this doc update.

**Carried from Session 22 (still true, no code change this session):**
✅ Reference-data schema backfilled season-to-date (124 dates, 1,613 games) and validated
✅ Diamond Line dashboard reworked — Standings + Leaderboards pages, `season_stats.py` DB-first swap
⚠️ `daily_reference_refresh.py` wired into `server.py`'s scheduler but not deployed
⚠️ 8 `game_pk` mismatches found in `mlb_scored_legs`, flagged not fixed (see Session 22 entry below)
🔲 Diamond Line dashboard step 4 (drill-down cards) still deferred

**Carried from Session 21 (still true, no change this session):**
✅ Parlay builder reverted: MAX_LEGS 6→4 (fixed 4-leg structure restored)
✅ `lineup_consistency` DB-persistence bug fixed
✅ `coverage_recent_10` sample-size floor added (`MIN_RECENT_GAMES = 5`)
⚠️ Pitcher ERA signal confirmed inverted, rebuild scoped but not implemented — still ACTIVE and unchanged in `simple_scorer.py`
🔲 Manual-pick end-to-end test (submit → resolve) — still not done, carried again this session (not touched — out of scope)

---

## What Happened on August 4, 2026 (Session 26)

### Context

Immediately following Session 25's pipeline-stall fix, a second, distinct bug surfaced in the same live-verification loop: the fixed pipeline now ran to completion reliably, but still produced **zero parlays** — top-4-by-score picks kept missing the +400 odds floor by a small margin (+337, +342, +332 across several runs) and the builder gave up rather than trying an alternative combination. Task: fix the parlay builder's floor-recovery behavior, per an operator-confirmed design (score-first selection preserved, fixed 4-leg structure preserved, odds only a constraint on the combination — not a selection criterion).

### Root cause (confirmed, matched the pre-diagnosed report exactly)

`src/engine/parlay_builder.py`'s `build_parlays()` selects legs by a single greedy pass sorted only by `composite_score` descending, checks the odds floor only after 4 legs are locked in, and — critically — `break`s the entire `for rank in range(1, top_n+1)` loop on the first miss, abandoning every remaining parlay slot in the batch too, not just the one that missed.

### Fix — bounded single-leg-swap recovery

New `_attempt_swap_recovery()`: when the top-4 pick misses the floor, tries replacing each of the 4 selected legs with each remaining eligible alternative in the pool, checking the same per-player/per-game/no-duplicate-odd_id constraints the greedy pass enforces. Among all swaps that clear the floor, keeps the one with the highest total `composite_score` — not just the first found — preserving score-first intent. Bounded to `len(legs) * SWAP_CANDIDATE_LIMIT` attempts, never unbounded. Each outcome (`clean top-4 pass` / `recovered via swap — N attempt(s)` / `no combination found — N attempt(s)`) is now logged explicitly.

### A real gap found via live-data testing, before trusting the first version

The task's own suggested implementation shape — "try swapping each position against the next 5-10 best alternatives" — was implemented literally first: `SWAP_CANDIDATE_LIMIT = 10`, candidates drawn from the next 10 best-*scored* remaining legs. A live full-pipeline trigger on this version still produced 0 parlays (`no combination found — 40 attempt(s)`, exactly `4 × 10`). Rather than accept that as a legitimate "no valid parlay" outcome, pulled today's actual eligible pool directly from `mlb_scored_legs` and checked by hand: a real floor-clearing combination existed (Jake Cronenworth -123, Ryan Waldschmidt -139, Seiya Suzuki -158, Ezequiel Tovar -161 → **+725**), but those legs ranked 18th-33rd by `composite_score` — well outside a top-10-by-score cutoff — because odds and composite_score aren't correlated (score also reflects coverage/trend/matchup signals independent of raw win probability). Fixed by widening the search to the full remaining pool (`SWAP_CANDIDATE_LIMIT` raised to 200, a safety cap on total attempts, not a score-based cutoff) — real eligible pools in this system run ~30-180 legs, so worst case stays a cheap, bounded few hundred checks.

### Testing

`tests/test_parlay_builder.py` (new, 10 tests): clean top-4 pass unchanged; swap recovery picks the highest-total-score valid swap, not just the first found; each constraint (duplicate player, per-game cap, duplicate odd_id) correctly rejects a candidate; a genuinely unrecoverable pool reports failure cleanly without hanging; and a regression test locking in the exact "good-odds leg ranked far down by score" gap found above. 10/10 passing. Full suite still partially blocked locally — 3 of 6 test files need a `DATABASE_URL` this environment doesn't have (same pre-existing gap as Session 25); 26/26 of the locally-runnable tests (12 pre-existing + 5 from Session 25 + this session's 9-then-10) passed.

Replayed today's actual 39-leg eligible pool (pulled directly from `mlb_scored_legs`) through the fixed `build_parlays()` locally before redeploying: produced 5 valid parlays, all recovered via swap — confirmed the fix against the real data that motivated it, not just synthetic test cases, before shipping.

### Deploy and verify live

Committed and pushed in two steps (initial fix, then the widened-search correction) — both deployed to both Railway services, confirmed via `list-deployments`/`get-status`. Live-verified with a real trigger of `run_morning_pipeline()` (the scheduler's own function) on the fully-fixed code: **5 parlays written to `mlb_parlay_recommendations_v2`/`mlb_parlay_legs_v2`** for `run_date = 2026-08-04`, confirmed via direct SQL query (not log output alone, per this task's explicit instruction — a past session's "completed cleanly" claim not matching the database is exactly the failure mode being guarded against here): +450 (Peña/Olson/Chisholm/Turner), +402 (McGonigle/Chourio/Trout/Waldschmidt), +421 (Walker/Edwards/Albies/Cronenworth), +413 (Turang/Stott/Langford/Aranda), +427 (DeLauter/Machado/Rumfield/Rice) — hitting the top of the 3-5 target, all 4-leg, all clearing +400.

### Session 26 status

Fixed, deployed, and live-verified against the real database with real production data — the strongest verification standard available short of watching the actual 9 AM/5:30 PM ET scheduled trigger (still an open item, shared with Session 25's own unclosed loop — see Pending Items). New/changed files: `src/engine/parlay_builder.py`, `tests/test_parlay_builder.py` (new), plus this doc, `BUILD_STATUS.md`, `ARCHITECTURE_DECISIONS.md`.

---

## What Happened on August 4, 2026 (Session 25)

### Context

Both the production and shadow parlay pipelines had stopped producing any output on 2026-07-23 — the exact gap Session 24 had found (`mlb_parlay_legs_v2` zero new legs since that date) but flagged as out of scope for its read-only analysis task, not root-caused. Task: diagnose, fix, test, and deploy.

### Step 0 — Verify local state before trusting anything

Per this project's workflow rules, confirmed the local clone's `git status`/`git log -1` (`1db8918`, clean working tree, matching `origin/master`) against Railway's actually-deployed commit before treating any prior investigation notes as current. This mattered: `BUILD_STATUS.md`/`SESSION_HANDOFF.md` still described Sessions 22-24's work as "about to be committed together," but it had already been committed and deployed on 2026-07-31 (`1db8918`) — a stale status carried across doc updates without being re-verified, corrected in both docs this session.

### Step 1 — Confirm the root cause with direct evidence, not the most plausible-sounding guess

The natural hypothesis — the pipeline logs `[7/8] Computing trend signals...` and then goes silent, so the trend-signals loop (`_attach_trend_signals()`, ~150-180 sequential `get_batter_game_log()` calls) must be hanging — was tested directly rather than assumed. Added flush-forced per-call instrumentation to that loop, deployed it, and triggered a live run via the admin API (`/api/admin/run_full_pipeline`). It processed all 162 legs cleanly in well under a second of application time. **The leading hypothesis was wrong**, disproven with real evidence before any fix was written.

Tracing forward from where the live run actually did stop (`Fetching pitcher quality and opponent offense ranks...`, the very next step) led to `get_pitcher_ranks()`/`get_team_offensive_ranks()` (`src/apis/pitcher_stats.py`, `src/apis/team_stats.py`) — loops over ~245 qualified pitchers and 30 teams calling the third-party `statsapi` package. Reading that package's source directly (`.venv/Lib/site-packages/statsapi/__init__.py:1785`), rather than trusting its docstrings, showed every wrapper function (`statsapi.get()`, `player_stat_data()`, `schedule()`, `standings_data()`, `boxscore_data()`, `lookup_player()`) calls `requests.get(url, **request_kwargs)` with `request_kwargs={}` by default — **no timeout anywhere, and no parameter exposed to set one for most of these wrappers.** A repo-wide grep found the identical pattern at ~20 call sites across both the production and shadow pipelines — explaining why both stalled together on 2026-07-23 (shared code, not two independent bugs), and matching every piece of behavioral evidence gathered before this session (silent, no exception, CPU/memory idle, no blocked query in `pg_stat_activity` — because the hang would be client-side, in a network call, not a DB query at all).

**Caveat reported honestly rather than glossed over:** the live diagnostic run did not itself hang — it completed the full pipeline in ~3.5 minutes end-to-end. The failure is evidently intermittent, gated by real-world MLB Stats API conditions at the exact moment of the call, consistent with production stalling specifically at the 9 AM/5:30 PM ET scheduled trigger windows (not an off-schedule manual trigger). The missing-timeout defect is 100% confirmed by reading the dependency's source; a live hang was not personally caught mid-flight this session.

### Step 2 — Fix

New `src/utils/net.py::call_with_timeout()` — since most `statsapi` wrapper functions don't expose a way to pass a timeout through, this runs the wrapped call in its own daemon thread and enforces a wall-clock deadline via `queue.Queue.get(timeout=...)`, returning a caller-supplied default and logging clearly instead of blocking forever. Each call gets its own thread rather than a shared pool, so a permanently-hung call can't exhaust a pool and block later calls too. Applied at every live-pipeline `statsapi.*` call site (both prod and shadow — `main.py`, `mlb_stats.py`, `pitcher_stats.py`, `team_stats.py`, `lineup_confirmation.py`, `enrich_legs.py`, `run_enriched_pipeline.py`), bounded to 15s each, matching the bound `mlb_stats.py`'s own `requests.get()` calls already used. Added an overall 90s wall-clock deadline to the three long sequential loops (`_attach_trend_signals`, `get_pitcher_ranks`, `get_team_offensive_ranks`) so a worst-case run fails loudly and continues with partial data instead of taking up to an hour.

### Step 3 — Test

`tests/test_net_timeout.py` (new) — proves a call that never returns is bounded to ~`timeout` seconds and returns cleanly rather than blocking (5/5 passing). Could not run the full existing suite: 3 of 6 test files (`test_bug_fixes.py`, `test_enriched_scorer.py`, `test_lineup_confirmation.py`) import `src/utils/db.py`, which connects to Postgres at module import time, and no `DATABASE_URL` was available locally in this session's environment (tried both a dummy value and asked the operator to locate the real one — not found in the time available). `tests/test_time_utils.py` (12) plus the new suite (5) — **17/17 ran and passed locally.** This is a partial result, reported as such rather than claimed as the full 76.

### Step 4 — Deploy and verify live

Committed and pushed (`cf23e94`). Hit a local git SSL cert error (`unable to get local issuer certificate`) — same class of issue Session 22 hit; fixed by setting `git config --global http.sslBackend schannel` (confirmed with the operator before touching global git config), which switches to the Windows-native cert store. Both `mlb-agent` and `dashboard-api` Railway services confirmed deployed on `cf23e94` via `list-deployments`/`get-status` (one deploy attempt appeared stuck in `BUILDING` with no log output for 20+ minutes — Railway's own diagnostic agent confirmed it had actually completed successfully; a `get-logs` API-timing artifact, not a real stall — redeployed anyway for a clean confirmation).

**Live verification, per the operator's explicit direction to force it rather than wait ~3 hours for the natural 5:30 PM ET slot:** triggered `run_morning_pipeline()` (the exact function the scheduler itself calls) twice via `/api/admin/run_full_pipeline` — once just before the fix deployed (reproduced the pipeline running cleanly with the diagnostic-only build, disproving the original hypothesis), once just after (confirmed the actual fix). Both completed all 8/9 steps in ~3 minutes each, including the previously-hanging pitcher/team-ranks step, with zero hangs. Neither run saved a parlay recommendation — both hit the exact same, unrelated, legitimate reason (best 4-leg combo only reached +337/+342 odds vs. the +400 minimum) — confirmed identical pre- and post-fix, so not a symptom of this bug. `mlb_scored_legs` confirmed still healthy throughout (165-173 legs/day through 2026-08-04).

### Session 25 status

Fixed, deployed, confirmed live via forced runs of the real pipeline function. **Not yet observed: a real scheduled-run confirmation** (9 AM/5:30 PM ET, not a manual trigger) or a saved parlay recommendation post-fix — both are open follow-ups, not blockers, since the underlying defect is code-confirmed and the forced runs used the identical code path the scheduler uses. New/changed files: `src/utils/net.py` (new), `main.py`, `src/apis/mlb_stats.py`, `src/apis/pitcher_stats.py`, `src/apis/team_stats.py`, `src/apis/lineup_confirmation.py`, `src/pipelines/enrich_legs.py`, `src/pipelines/run_enriched_pipeline.py`, `tests/test_net_timeout.py` (new), plus this doc, `BUILD_STATUS.md`, `ARCHITECTURE_DECISIONS.md`.

---

## What Happened on July 30, 2026 (Session 24)

### Context

Two distinct handoffs the same day. First: `mlb_training_data` has never captured which pitcher a batter faced going forward — the raw `opposing_pitcher_id` is computed in-memory during scoring and `mlb_scored_legs`'s own INSERT already persists it correctly, but it was silently dropped before `log_training_data_legs()`'s INSERT (a prior, separate one-time backfill had already recovered this historically; this handoff was forward-going only). Second: answer the operator's direct question — is the current `composite_score >= 65` coverage-heavy gate discarding legs where a good opposing-matchup would outweigh lower coverage/consistency?

### Task 1 — Opposing-Pitcher Capture Fixed Forward + Point-in-Time Stat Backfill

**Fix.** Added `opp_pitcher_id` to `log_training_data_legs()`'s INSERT column list and values tuple in `src/utils/db.py` — one line each, matching the exact silent-drop pattern already fixed once for `lineup_consistency` in Session 21. Verified via a new source-inspection test (`tests/test_bug_fixes.py::TestOppPitcherIdTrainingDataInsert`) that the column appears in both the column list and values tuple of the single `INSERT INTO mlb_training_data` statement in the file.

**New `scripts/backfill_point_in_time_stats.py`.** Two pieces, chained into `daily_reference_refresh.py` immediately after it backfills yesterday's game logs: (1) `refresh_cumulative_tables()` — incremental daily append to `mlb_player_batting_cumulative`/`mlb_player_pitching_cumulative` (running season-to-date totals, handles doubleheaders via aggregation); (2) `backfill_training_data_point_in_time()` — fills `mlb_training_data`'s `pt_role`/`pt_avg`/`pt_obp`/`pt_slg`/`pt_ops`/`pt_k_pct`/`pt_bb_pct`/`pt_era`/`pt_whip`/`pt_k9`/`pt_innings_pitched`/`opp_pt_*` columns from the two cumulative tables plus `mlb_players.primary_position` (for disambiguating `stat='strikeouts'` between a batter's own Ks and a pitcher's Ks-thrown).

**A real bug caught by testing against live data before trusting the design.** The first draft gated the opposing-pitcher (`opp_pt_*`) fill on successfully resolving the row's own `player_id` to a number. Querying the actual 12,207-row backlog (rows with `opp_pitcher_id` set but `opp_pt_era` still NULL) showed the overwhelming majority carry a legacy SGO-style string `player_id` (e.g. `"MICHAEL_MCGREEVY_1_MLB"`, from before this session's fix) whose `pt_role` had *already* been resolved by the original one-time backfill's own name-based crosswalk — the draft's coupling meant `opp_pt_*` would never fill for any of them, purely because this script's simple int-cast couldn't *also* resolve the unrelated `player_id`. Fixed by decoupling the two fills so each is computed independently per row, from only the inputs it actually needs.

**Validated against production, not just logic-reviewed.** Manually verified `pt_avg`/ERA/WHIP/K9 formulas against real cumulative-table rows and confirmed the doubleheader-aggregation CTE handles a real 2-game day correctly, before running anything for real. Then ran the actual backfill against Supabase (translated to direct SQL since no local `DATABASE_URL` exists in this environment — Supabase creds live in Railway only — the SQL was written to exactly mirror the tested Python script's logic, not a simplified stand-in). Results: `pt_role` 104,507/105,728 rows covered (98.8%, matching the historical rate — **0 new rows filled this run**, all 1,221 remaining are confirmed legacy non-numeric `player_id`s, correctly out of scope for a forward-going fix). `opp_pt_era`: 78,863/91,070 filled (86.6%); the remaining 12,207 were checked individually — **100% have zero prior in-season cumulative data for their opposing pitcher** (confirmed via `EXISTS` check both before and after the run: 0/12,207 either time) — ~79% are literal opening-weekend games (3/28–3/31, structurally no "before" data can exist), the rest are individual pitcher-debut games. Excluding that genuinely-unfillable set, fill rate is 100%. The decoupling fix's payoff is forward-looking, not retroactive: it ensures a pitcher's *second* start (once real prior data exists) gets filled on the next daily run instead of being silently skipped over an unrelated `player_id` issue.

**Constraint honored:** read-only/additive only. `simple_scorer.py`, `enriched_scorer.py`, `parlay_builder.py`, and `mlb_scored_legs`'s own (already-correct) `opposing_pitcher_id` handling were not touched. Full detail: `ARCHITECTURE_DECISIONS.md` §35.

### Task 2 — Coverage Threshold vs. Matchup Quality Analysis

Full report: `docs/COVERAGE_VS_MATCHUP_ANALYSIS.md`. Read-only analysis, no scoring changes made.

**Two methodological findings that reshaped the analysis, found while reproducing the handoff's own baseline correlation table (not assumed correct without re-derivation):**
1. `coverage_overall` is hard-floored at 65% (`over` props) / 40% (`under` props) by `main.py`'s Gate 1, *before* a leg is ever scored or logged. Confirmed directly: zero rows below 65.0 for hits/over and batter-K across the entire table, no filter needed to produce that floor. This means "low coverage" barely exists in `mlb_training_data` for those two bet types — the operator's exact question (does a truly-low-coverage, good-matchup leg beat a high-coverage, bad-matchup one) is untestable for them from this table. totalBases has a real, wide range (40–86%) because its `under`-direction gate is lower, making it the one bet type where the question could actually be tested.
2. `coverage_overall`/`composite_score` are only consistently defined from **2026-06-09** onward — before that, a different (pre-current) scoring pipeline was in effect, confirmed via `composite_score` values as low as 1.36 that are mathematically impossible under the current formula given a 65%+ coverage floor. The entire analysis was restricted to the post-6/9 regime for internal consistency; this also means pitcher-strikeout props (discontinued from the pipeline entirely, per `main.py`'s `ALLOWED_PROPS` comment) have zero current-era rows and no opposing-matchup metric at all.

**Results:** hits/over showed no support for the hypothesis (Q3, low-cov+good-matchup, lost to Q2, high-cov+bad-matchup, by 8.4pp; interaction term p=0.765). totalBases showed real, adequately-sampled support (Q3 beat Q2 by 11.5pp win rate / ~$0.21 EV per $1) — but totalBases is currently shadow-only, not live production. Batter-K was directionally supportive (Q3 beat Q2 by 10pp, significant interaction coefficient in both coverage proxies tested) but every relevant Step-1 cell sits under this project's own n<50 reliability bar. Pitcher-K couldn't be tested at all (no opposing-matchup metric exists for a pitcher-role leg).

**Recommendation:** don't loosen the coverage gate for hits/over on this evidence — the data argues against it for the bet type the gate exists to protect. Re-run once `mlb_prop_legs_history` (Session 23, ungated, confirmed capturing 1,014 rows as of today) has ~1 week of data (target 2026-08-06), joined against the now-built cumulative tables, to get a real answer for hits/over and batter-K too.

**Side finding, not yet investigated:** while building the analysis dataset, `mlb_parlay_legs_v2` was found to have zero new legs for any `run_date` from 2026-07-24 through 2026-07-30 (last activity 2026-07-23) — confirmed via direct query, not assumed. Flagged as a pending item, not root-caused this session (out of scope for a read-only analysis task).

### Session 24 status

Nothing from Sessions 22, 23, or 24 has been committed as of this doc update — all three sessions' work (reference-data backfill, Diamond Line dashboard, SGO billing verification, schedule cut, full prop-line capture, opposing-pitcher/point-in-time-stat backfill, coverage-vs-matchup analysis) is about to be committed together. New/changed files this session: `src/utils/db.py` (opp_pitcher_id fix), `scripts/backfill_point_in_time_stats.py` (new), `scripts/daily_reference_refresh.py` (two new steps wired in), `tests/test_bug_fixes.py` (new test class), `docs/COVERAGE_VS_MATCHUP_ANALYSIS.md` (new). One production database backfill run (idempotent, decoupled per-row updates — see Task 1 above); no Supabase schema/migration changes this session (all target columns/tables already existed from the prior session's backfill).

---

## What Happened on July 29, 2026 (Session 23)

### Context

A second, distinct handoff on the same day as Session 22: (1) empirically verify SGO's billing model (per-event vs. per-market) before relying on it further, (2) cut the production pipeline schedule from 3 runs/day to 2 ahead of the 2026-08-01 SportsGameOdds Pro→Amateur tier downgrade (2,500 objects/month cap), and (3) build full, non-qualified-filtered prop-line capture into the (empty, schema-only-as-of-Session-22) `mlb_prop_legs_history` table — a ground-up-rebuild calibration dataset, explicitly isolated from all production/shadow scoring and win-rate reporting. Handoff explicitly flagged that Session 22's work was still sitting uncommitted and instructed not to assume it was live — confirmed via fresh `git log`/`git status` at the start of this session (unchanged from Session 22's end state).

### Task 1 — SGO Billing Verification

The handoff's own supporting evidence — `mlb_sgo_request_log.entities_consumed` tracking day-to-day game counts across months of logs — turned out to be weaker than it first appeared: that field is computed **locally**, as `len(response['data'])` inside `sportsgameodds.py`'s `_sgo_get()`. Since `/events` structurally returns one object per game/event with all markets nested inside each one's `odds` dict, that count equals game count almost by definition, regardless of how SGO actually bills — it never counted markets at all, so on its own it can't distinguish per-event from per-market billing.

Built `scripts/verify_sgo_billing.py` to run the actual test: call SGO's own account-level usage counter (`/account/usage` → `rateLimits.per-month.current-entities`) immediately before and after one real `/events` call, and compare the delta to both events-returned and total-markets-returned. Result: **delta = 18, events returned = 18** (ratio 1.00) — an exact match — while total markets across those same 18 events was **25,486** (ratio 0.0007). Billing is per-event, confirmed as unambiguously as an empirical test gets.

Also checked response completeness (the handoff's other open question): `pitcher_strikeouts` returned 36 distinct players (exactly 2 starters × 18 games — no truncation), `batter_hits`/`batter_strikeouts`/`batter_total_bases` each returned ~306-307 distinct players (broad, consistent coverage, not a narrow default subset). One completeness result looked wrong at first — `game_lines: 0` — but investigation traced it to `get_totals_props()` (in `src/apis/sportsgameodds.py`) searching for the wrong key prefix (`runs-*` instead of the actual live `points-*`), not a real absence of game-level markets; that function is unused elsewhere in the codebase (confirmed via grep), so the bug was dormant rather than live-broken. Conclusion reported back to the operator before proceeding, per the handoff's explicit gate: **both sub-questions passed, no scope reduction needed for Task 3.**

### Task 2 — Schedule Cut

Removed the `(dtime(12, 0), "midday")` entry from `src/web/server.py`'s `_PIPELINE_SCHEDULE`, plus updated the accompanying docstrings/comments/print statements and a stale reference in `main.py`. Verified the actual impact with real historical data rather than trusting the handoff's own projection: pulled 7 days of `mlb_sgo_request_log`, bucketed by ET time-of-day —

| Day | 9am | 12pm | 5:30pm | Total |
|---|---|---|---|---|
| 07-24 | 15 | 15 | 14 | 44 |
| 07-25 | 15 | 15 | 10 | 40 |
| 07-26 | 15 | 15 | 1 | 31 |
| 07-27 | 12 | 12 | 11 | 35 |
| 07-28 | 16 | 16 | 15 | 47 |

Average 39.4 objects/day, of which the 12 PM slot averaged 14.6/day (~37%). Post-cut projection: **~24.8/day → ~744/month** — comfortably under the 2,500 cap, more headroom than the handoff's own ~1,110/month estimate.

**Side finding, not touched:** production `mlb_parlay_recommendations_v2.source` values for the non-morning slots are literally `'midday'`/`'evening'` (the raw scheduler label passed straight through), not `'auto_12pm'`/`'auto_530pm'` as `SUPABASE_SCHEMA_REFERENCE.md` documents — the 9 AM slot passes no explicit source and falls through to an hour-based fallback that correctly produces `'auto_9am'`, but the other slots don't go through that fallback. Pre-existing, unrelated to this session's changes, flagged not fixed.

### Task 3 — Full Prop-Line Capture

**Schema fixes**, applied as a live migration (no repo migration file, matching how the reference schema itself was applied): `player_id` made nullable; `market_scope` (`'player'`/`'game'`, NOT NULL) and `player_role` (`'batter'`/`'pitcher'`/NULL) added, both with CHECK constraints (including one enforcing `market_scope`/`player_id` stay consistent with each other — a defensive addition beyond the literal spec, cheap and closes an obvious drift risk). Also added a **partial unique index** (`(game_pk, stat, line, direction, sportsbook) WHERE player_id IS NULL`) for the game-scope case — the original single `UNIQUE(player_id, game_pk, stat, line, direction, sportsbook)` constraint would never have deduped game-level rows across repeated runs, since Postgres treats every NULL `player_id` as distinct for uniqueness purposes. Caught before it caused silent duplicate accumulation in production.

**Capture module** (`src/pipelines/prop_legs_capture.py`, new): captures game lines (moneyline/spread/total, `market_scope='game'`) and player props (batter hits/strikeouts/totalBases, pitcher strikeouts, `market_scope='player'`) for every player with a posted line — not filtered to qualified players, per the handoff's explicit "full capture is the point of this task." Wired into `main.py`'s `run_pipeline()` right after Step 3's existing SGO fetch, gated on `not skip_resolution` (9 AM morning run only) — reuses that same call's `sgo_games`/`all_sgo_props`/`schedule`, making **zero new SGO API calls**. `mlb_teams`/`mlb_players`/`mlb_games` rows are upserted `ON CONFLICT DO NOTHING` directly from this job's own data (schedule + resolved player IDs), so it doesn't depend on Session 22's `daily_reference_refresh.py` ever being deployed, per the handoff's explicit instruction.

**Player-role disambiguation**, the handoff's flagged concern: `get_player_props()` (existing, untouched, still used by production) normalizes SGO's `batting_strikeouts` and `pitching_strikeouts` raw statIDs to the same internal `'strikeouts'` stat name and doesn't preserve which prefix matched — the same batter-vs-pitcher ambiguity already worked around once elsewhere in the codebase. Rather than modify that production-depended-on function, `_build_odd_id_role_map()` independently scans each game's raw `odds` dict by key prefix and matches back to each leg's `odd_id` — fully additive, zero change to `get_player_props()`'s existing behavior or callers.

**Two real bugs found via live testing, both fixed:**
1. **`ON CONFLICT` target didn't match the partial index.** First live run: every single game-scope upsert failed with `there is no unique or exclusion constraint matching the ON CONFLICT specification` (0 game lines, 0 player legs written — the per-game try/except swallowed the game-line failure before player-leg processing could even run for any matched game). Root cause: Postgres requires a partial unique index's `WHERE` predicate to be restated in the `ON CONFLICT` clause itself, not inferred from the column list. Fixed by adding `WHERE player_id IS NULL` to the game-scope conflict target.
2. **Athletics team-matching bug.** 5 of 11 SGO games failed to match a schedule `game_pk` on the first live run. Added a debug dump of unmatched team-pairs to diagnose rather than guess — 4 of the 5 turned out to be a genuine testing-time artifact (`get_todays_games()` with no date override windows relative to UTC midnight, not Eastern midnight; testing at ~10 PM ET pulled in a few of the *next* Eastern calendar day's games, which obviously don't match "today's" schedule — expected behavior, not a bug, and won't happen during the real 9 AM ET production run). The 5th (`('BOS', 'OAK')`) was a real bug: the 2026 Athletics relocation means the schedule's full team name is now literally `"Athletics"`, and the hardcoded team-abbreviation map only had `"Oakland Athletics"` as a key, so it fell through to a wrong default (`"ATH"`) instead of matching SGO's actual short name (`"OAK"`, confirmed live). Fixed by mapping the bare `"Athletics"` name to `"OAK"` directly.

**Validation, in order:**
- `scripts/test_prop_legs_resolution.py` — 7 synthetic test cases against a real, already-backfilled completed game (2026-03-26, game_pk 823649) with known outcomes: pitcher-K over/under, batter-hits over/under, home/away moneyline, game total. **7/7 passed** before any capture-side testing began.
- `scripts/test_prop_legs_capture.py` — isolated test replicating only the schedule+SGO fetch, calling `capture_full_prop_lines()` directly, without running the rest of the pipeline or touching `mlb_scored_legs`/recommendation tables. First run surfaced both bugs above (0 rows written, all failed). Second run (after the `ON CONFLICT` fix): 36 game lines + 176 player legs captured, 0 errors. Third run (after the Athletics fix, ~5 min later): confirmed `('BOS','OAK')` now matches; re-upserted the same legs plus new ones (36 game lines, 60 more player legs) and confirmed `odds_history` correctly appended a second entry while `first_seen_odds`/`first_seen_at` stayed pinned to the original insert — the natural-key upsert-and-append behavior works exactly as specified.

**Resolution wiring:** `resolve_prop_legs_history(cur)` takes a cursor rather than owning its own connection, so it composes into `scripts/daily_reference_refresh.py`'s existing single transaction — called immediately after that job backfills yesterday's `mlb_player_batting_logs`/`_pitching_logs`, reading its own uncommitted step-1 writes within the same transaction (Postgres supports this natively). Resolves player-scope legs against the relevant log table/column by `(player_role, stat)`; game-scope legs against `mlb_games.home_score`/`away_score` (moneyline: which side actually won; spread: margin adjusted by the stored line; total: combined score vs. line). Writes only `result`/`actual_value`/`resolved_at` on `mlb_prop_legs_history` — nothing else.

### Session 23 status

Nothing from Session 22 or 23 has been committed. All files (schema migrations already applied live to Supabase; code changes sitting in the operator's WSL clone and Claude's own scratch clone) are about to be committed together. New/changed files this session: `src/web/server.py` (schedule cut), `main.py` (capture wiring + stale comment fix), `src/pipelines/prop_legs_capture.py` (new), `scripts/daily_reference_refresh.py` (resolution wiring added), `scripts/verify_sgo_billing.py` (new, diagnostic), `scripts/test_prop_legs_capture.py` (new, diagnostic), `scripts/test_prop_legs_resolution.py` (new, diagnostic). Two live Supabase migrations applied: `mlb_prop_legs_history` nullable `player_id` + `market_scope`/`player_role` columns + CHECK constraints, and the game-scope partial unique index.

---

## What Happened on July 29, 2026 (Session 22)

### Context

Operator handoff covered two pieces of work: (1) get an already-drafted-but-never-run reference-data backfill script working and run it season-to-date, plus write the season-stats/standings snapshot and daily-refresh pieces that hadn't been drafted yet, and (2) scope — and, once approved, start building — a rework of the Diamond Line dashboard (`dashboard_api/`) to surface the new reference data via MLB.com-style leaderboard/standings tables and player/team drill-down cards. A new, normalized reference schema had already been applied directly to the live Supabase database before this session started (no migration file in the repo — confirmed via `information_schema` that the tables existed, empty).

### Task 1 — Reference-Data Backfill

**Environment setup.** No local clone of `mlb-agent` existed on the operator's Windows machine going into this session (confirmed via `git status`/`git log -1` comparison — the operator had no unpushed local work anywhere). Cloned fresh from GitHub. Hit an unrelated SSL certificate verification failure on both `git clone` and Python's `requests` library (`unable to get local issuer certificate`) — worked around via `git -c http.sslBackend=schannel` and `pip install pip-system-certs`, both of which switch to the Windows-native certificate store instead of `certifi`'s bundled one. Root cause (corporate proxy vs. antivirus TLS inspection) not investigated further — not this session's problem to fix, just a local workaround.

**Script review, before any run.** Read `src/apis/mlb_stats.py`'s `get_schedule()`/`get_box_score()` source and cross-checked against LIVE `statsapi.mlb.com` responses (not just docstrings) — this surfaced three real bugs in the draft script, all fixed before the first run (full detail in `scripts/backfill_reference_data.py`'s module docstring):
1. `statsapi.boxscore_data()` has its own hardcoded `fields` whitelist that does NOT include `plateAppearances`, `hitByPitch`, or `gamesStarted` — even though these look like reasonable fields to expect. The draft's batting-log insert was gated on `if batting.get("plateAppearances")`, which is always `None`/falsy via this API path — no batting logs would ever have been written. Fixed to gate on non-empty `batting` dict (confirmed via live inspection: genuinely empty `{}` for non-participants, a real signal).
2. `is_starter` was gated on `pitching.get("gamesStarted", 0) == 1` — also never present, always False. Fixed to use `side_data["pitchers"][0]` (first entry of the side's pitcher-appearance list, confirmed live to be the starter).
3. `opposing_pitcher_id` (a real FK column on `mlb_player_batting_logs`) wasn't populated at all in the draft. Fixed, which required restructuring to a two-pass insert per game (upsert both rosters into `mlb_players` first, then insert logs) so the FK always resolves regardless of which side is processed first.

Also derived `batting_order` (an exact 1–9 lineup slot) from each player's own `battingOrder` field (e.g. `"300"` → slot 3) — the draft had explicitly flagged this as a known, unfixed gap, but the data turned out to already be available via the same box-score call, just unused.

**Dry-run + validation.** `--dry-run` over 2026-03-01–03 correctly processed 0 games (before the season started — confirmed the actual opener was 2026-03-25, not 3/1). A real (non-dry-run, but within the legitimate range) single-day run against 2026-03-26 was spot-checked row-by-row in Supabase against the live box score for that exact game (Freddy Peralta's pitching line, Bo Bichette's batting line including `opposing_pitcher_id`/`batting_order`) — every field matched.

**Full run.** Operator does not use a local `.venv` with `DATABASE_URL` shared with Claude by choice — all script execution this session was done by the operator directly, via `railway run <command>` from their own WSL clone, which injects the linked Railway service's env vars without Claude ever seeing `DATABASE_URL`. Full range `2026-03-01`–`2026-07-29` completed: 124 distinct game dates (season actually ran 3/25–7/29, with a ~3-day gap around the confirmed All-Star break), 1,613 games, 34,128 batting-log rows, 13,575 pitching-log rows, 1,335 distinct players.

**Season-stats + standings.** `scripts/backfill_reference_snapshots.py` (new — the handoff's Task 1 items 4a/4b weren't drafted yet). Investigated live whether the handoff's proposed PA≥3.1×team-games / IP≥1.0×team-games qualification threshold needed to be computed client-side: confirmed `stats=season&group=hitting|pitching` defaults to `playerPool=QUALIFIED` server-side and that the returned pool's minimum PA lines up with the expected threshold on a spot-checked date — this is literally the same computation MLB.com's own leaderboards (the screenshots this task was scoped from) use. Relied on that instead of reimplementing it. Also pulls standings + splits from the `/standings` endpoint's `records.splitRecords`/`divisionRecords`/`leagueRecords` structure, confirmed live.

**WCGB sign bug.** After first getting the standings page rendering (see Task 2 below), a side-by-side check against the operator's own screenshot showed `wcgb` values for wildcard-holding teams (Yankees, Red Sox) missing a `+` prefix the screenshot had. Traced directly: the raw `wildCardGamesBack` field is genuinely a literal string like `'+7.0'` for a team holding a spot, vs. a plain `'7.0'` for a team chasing one — `float()` collapses both to `7.0`. Fixed by storing the `'+'` case as a negative number in the DB (distinguishable, still numeric) and reconstructing the `+` on display in `dashboard_api/standings.py`. Required an `ALTER TABLE` (additive, nullable — not present, `mlb_player_season_batting_stats` also got one for `plate_appearances`, see Task 2) and a re-run of the snapshot backfill, both confirmed.

**Data-integrity checks (handoff item 6).**
- `mlb_games.game_pk` vs. `mlb_scored_legs.game_pk` for overlapping dates: 1,300 of 1,320 distinct game_pks matched. 12 of the 20 unmatched were today's games (not yet Final at check time — expected). The other 8 were investigated directly against the live API and turned out to be a genuine pre-existing data-quality bug in `mlb_scored_legs`: those specific `game_pk` values are attached to leg rows with `run_date` values in May/June, but the game_pks themselves belong to unplayed games scheduled for August/September 2026. Not fixed (out of scope — `mlb_scored_legs` is a production table this work was told not to touch), just flagged with evidence.
- 3 independent box-score spot-checks (games from March, June, and July) compared `mlb_player_pitching_logs`/`mlb_player_batting_logs` rows against a fresh live API pull for the same game — all fields matched exactly on every check.

**Daily refresh.** `scripts/daily_reference_refresh.py` (new) — runs games/logs for *yesterday* (not literally "today," since a refresh running before today's games finish would see mostly non-Final games) plus today's season-stats/standings snapshot. Dry-run validated standalone (imports resolve cleanly, correct date logic, rolls back cleanly) before being wired into `src/web/server.py`'s existing in-process scheduler (`_reference_data_scheduler()`, 3 AM ET, same pattern as the existing 9 AM/12 PM/5:30 PM pipeline scheduler and the lineup-drain cron). Per `WORKFLOW_RULES.md`'s "Red Flags" section (new scheduled API calls need sign-off), this was NOT wired in silently — explicitly confirmed with the operator first. Not yet deployed (nothing committed/pushed this session).

### Task 2 — Diamond Line Dashboard Rework

**Scoping, before any code.** Read `dashboard_api/`'s existing backend (`main.py`, `db.py`, `queries.py`, `shape.py`, `season_stats.py`, `odds_extra.py`) and frontend (`static/index.html`, `support.js`, `styles.css`). Two findings reshaped the plan from what the handoff assumed:
1. The existing dashboard is entirely built around *today's* slate and props (three tabs: Matchup/Batters/Pitchers) — there was no leaderboard or standings view at all before this session, so the new work is additive, not a redesign.
2. `static/support.js` (68K) is a GENERATED file — its own first line reads `// GENERATED from dc-runtime/src/*.ts — do not edit. Rebuild with 'cd dc-runtime && bun run build'.` A repo-wide search confirmed `dc-runtime/` doesn't exist — only the compiled output was ever committed. This means "extend the existing frontend" isn't actually an available option; the plan (presented and approved before writing any code) was to build all new pages as separate, self-contained static files (plain HTML/CSS/vanilla JS, reusing `styles.css`'s design tokens) that `main.py`'s existing `StaticFiles(html=True)` mount serves automatically with zero backend routing changes, cross-linked via plain `<a>` tags in each page's nav.

**Sequencing agreed (and followed): standings first (smallest surface) → `season_stats.py` live-call reduction → hitting/pitching leaderboards → player/team drill-down cards (deferred).**

**1. Standings page.** `dashboard_api/standings.py` (new) + `GET /api/standings` + `static/standings.html`. Pivots `mlb_team_standings` + `mlb_team_standings_splits` (long-format split rows) into the wide MLB.com layout (W/L/PCT/GB/WCGB/XTRA/1 RUN/DAY/NIGHT/GRASS/TURF/EAST/CENTRAL/WEST/AL-NL/VS.R/VS.L), grouped by division. Validated by the operator pulling the raw JSON directly and comparing every AL East team against the operator's own MLB.com screenshot from earlier in this session — exact match on every field except the (subsequently found and fixed) WCGB sign.

**2. `season_stats.py` live-call reduction.** The existing version made one live MLB API call per player per dashboard request (6h cache) for BA/OBP/K%/BB%/ERA/K9/WHIP/W-L on the Batters/Pitchers tabs. Rewrote to read from the new reference tables first, with a live-API fallback ONLY for players not present there. This distinction mattered: the reference tables are qualified-players-only by design (~150 hitters/~60 pitchers on a given day), but the dashboard's existing tabs show ANY player with a prop today, including below-threshold players — a DB-only swap would have silently gone blank for exactly the players least likely to already be well known. The fallback preserves full coverage; only the common case (qualified players, most of a day's props) skips the network round trip. Required adding `plate_appearances` to `mlb_player_season_batting_stats` (additive migration — the original reference-schema application didn't include it, and K%/BB% need it as the denominator, not `at_bats`, to match the existing formula exactly). Validated: operator pulled 5 real batters from `/api/dashboard/refresh` post-swap — all BA/K%/BB%/OBP values sane and (for Otto Lopez specifically) matched an earlier live pull from this same session almost exactly.

**3. Hitting/Pitching leaderboards.** `dashboard_api/leaderboards.py` (new) + `GET /api/leaderboards/hitting`+`/pitching` + `static/leaderboards.html` (click-to-sort columns, defaults matching the operator's screenshots — AB-sorted hitting, SO-sorted pitching). Column set matches MLB.com's own pages exactly since the reference tables were built to capture the same fields. Validated: pitching leaderboard was a near-exact match against the operator's own screenshot on every single column for the first 3 pitchers (Misiorowski, Williams, Cease — W/L/ERA/G/GS/CG/SHO/IP/H/R/ER/HR/HB/BB/SO/WHIP/AVG all identical); hitting matched with the expected small day-over-day drift (screenshot was from a game or so earlier than "today").

**Step 4 (player/team drill-down cards)** — explicitly deferred to a future session, operator's choice, not blocked on anything found this session.

### Session 22 status

Nothing committed or pushed as of this doc update. All new/changed files exist only in the operator's WSL clone working tree (`/home/gweeod/mlb-agent`) and Claude's own scratch clone (`C:\Users\gweeo\repos\mlb-agent`, Windows). Files touched: `scripts/backfill_reference_data.py` (rewritten), `scripts/backfill_reference_snapshots.py` (new), `scripts/daily_reference_refresh.py` (new), `src/web/server.py` (scheduler wiring added), `dashboard_api/main.py`, `dashboard_api/standings.py` (new), `dashboard_api/leaderboards.py` (new), `dashboard_api/season_stats.py` (rewritten), `dashboard_api/static/standings.html` (new), `dashboard_api/static/leaderboards.html` (new), `dashboard_api/static/index.html` (nav links added). Two Supabase migrations applied directly (not via a repo migration file, matching how the reference schema itself was applied): `plate_appearances` added to `mlb_player_season_batting_stats`.

---

## What Happened on July 20, 2026 (Session 21)

**Context.** First review since the All-Star break (games resumed July 17). Operator asked for a 3-day production + shadow performance check (7/17-7/19), excluding `manual_pick` source, prompted by concern that pre-break changes were responsible for a perceived decline.

### Investigation 1 — 3-Day Post-Break Performance Check

Production: 33 resolved parlays, 2 won (6.1%). Shadow: 36 resolved, 7 won (19.4%). Leg-level win rates for both pipelines were healthy (58-68% weekly, in line with historical norms) — the weakness was concentrated at the parlay level, not the leg level.

### Investigation 2 — Root Cause Is the July 8 Builder Redesign, Not the July 10 Changes

The operator's original hypothesis was the Session 19/20 changes (scratch handling, timezone centralization), deployed July 10. Git history confirmed **nothing was pushed to `master` between 7/10 and 7/20 except a docs-only commit (`6b5ca06`, 7/14)** — no code changes exist in the window the operator suspected. Void rate actually *improved* post-7/10 (consistent with the scratch-handling fix working as intended), and no `game_start_time` contamination had reoccurred. Weekly production win rate showed a **multi-week decline that predates 7/10** (18.8%→26.3%→15.3%→20.0%→14.5%→9.9%→6.1%, week of 6/1 through week of 7/13) — the week of 7/6 (all pre-7/10) was already at 9.9%.

The actual fingerprint: **avg legs/parlay jumped from a fixed 4.00 (100% 4-leg, all of June) to 4.4-4.5 (only ~45% 4-leg) exactly at the July 8 builder redesign** (Session 18, `ARCHITECTURE_DECISIONS.md` §21 — floor-only odds, flexible 4-6 leg count). With individual legs winning independently at ~60-65%, more legs per parlay mechanically drives down parlay-level win rate (0.62⁴≈15% vs 0.62⁶≈6%) even with unchanged leg quality — confirmed leg quality didn't meaningfully change (avg `composite_score` of selected legs: 73.7 pre-redesign vs 71.3 post).

### Investigation 3 — EV Confirms It's a Real Loss, Not Just Optics

Actual dollar EV per $1 staked, pre- vs. post-redesign:

| Era | Legs | n | Win Rate | Avg Odds | EV per $1 |
|---|---|---|---|---|---|
| Pre-redesign | 4 | 486 | 20.2% | +450 | **+$0.128** |
| Post-redesign | 4 | 28 | 7.1% | +419 | **−$0.662** |
| Post-redesign | 5 | 58 | 8.6% | +574 | **−$0.416** |

The higher payout on longer parlays does not compensate for the lower hit rate — both post-redesign buckets are solidly negative EV, while the pre-redesign fixed-4-leg structure was solidly positive on a large sample.

**Simulated hard 4-leg cap** (top-4-by-`composite_score` within each actual post-redesign parlay, using current signals): 14.5-16.7% win rate, −$0.25 to −$0.34 EV per $1 (n=48-69, two overlapping windows). Better than the current 5-6-leg structure, but **doesn't cleanly restore the pre-redesign +$0.128 EV** — flagged honestly as either small-sample noise (windows disagreed by ~10 points against each other) or a second, unisolated factor (in-season signal drift, All-Star-break calendar noise on recent-form signals). Not resolved this session — see Pending Items.

**Decision:** revert `MAX_LEGS` from 6 back to 4 (fixed 4-leg parlays). Backed by the large pre-redesign sample; the "does it fully restore profitability" question is left open for live tracking rather than further backtesting, given sample-size limits.

### Investigation 4 — Signal Audit: What's Actually Working

Systematic check of every adjustment in `simple_scorer.py`, controlling for the selection-bias trap where `composite_score >= 65` gating can make a bonus look bad or a penalty look good purely because bonused legs needed less base coverage to qualify.

**`lineup_consistency` — confirmed dead, not a scoring problem.** `main.py` computes it correctly in memory (Step 5b filter, `<0.70` removes the leg unless an injury-expanded-role exception applies), but `db.py`'s `log_scored_legs()` INSERT for `mlb_scored_legs` never included the column in its column list or values tuple — computed, then silently discarded before reaching the database. 100% NULL across the entire season (18,356/18,356 rows, 4/17-7/20). **Fixed this session** (Fix 2 below). Note: fixing persistence doesn't confirm the upstream Step 5b filter has actually been running successfully — see Pending Items.

**Pitcher ERA adjustment — confirmed inverted, controlling for base coverage.** `pitcher_era` comes from `_fetch_pitcher_season_stats()` in `src/apis/matchup.py` — cumulative full-season ERA, 5.0 IP floor, no role/recency separation. This is the *same function and same raw stat split* WHIP was pulled from on June 25 for "reliever-contaminated pool" reasons. Bucketed by base coverage band (~5-pt bands), the "weak pitcher" bucket (ERA>5.0, gets a +5 boost for hits/over) underperformed "neutral" in every band and underperformed "ace pitcher" (ERA<3.0, −5 penalty) in 3 of 4 bands — e.g. band ~72 coverage: ace 63.8% (n=80), neutral 59.8% (n=246), weak-pitcher 54.2% (n=59). The adjustment is currently rewarding exactly the legs that perform worse. **Not fixed this session** — operator explicitly wants ERA kept as a signal (reasonable — pitcher quality should matter), so a rebuild was scoped rather than a removal: replace cumulative season ERA with a recent-starts ERA (new `get_pitcher_game_log()`, same pattern as the existing batter game-log function), raise the sample floor from 5.0 IP to ~3 starts, and backtest the replacement with the same controlled-band method before shipping. **Deferred to a future session.**

**K9-rank adjustment — same data-source risk, inconclusive evidence.** Also sourced from `_fetch_pitcher_season_stats()`, same theoretical contamination risk as ERA. Controlled-band test came back mixed (one band showed the expected direction, another inverted it) rather than consistently backwards — plausibly because K/9 is a more stable, less luck-dependent stat than ERA. **No action taken — monitor with more data before deciding.**

**Streak/consistency adjustment (`coverage_recent_10` gap) — weak signal, missing sample floor.** Bucketed win rate spanned only 57.1%-63.3% and was non-monotonic (the "severe cold" bucket, −6 penalty, actually beat "moderate cold," −4 penalty: 61.5% vs 57.1%). Root cause: `coverage_recent_10` in `src/engine/coverage.py` had no minimum-sample floor — `coverage_overall` requires `get_season_minimum(overall_games)` before being trusted, but the recent-10 window would compute and trust a value off as few as 1 logged game. **Fixed this session** (Fix 3 below) — `MIN_RECENT_GAMES = 5` added, applied to both `_hitter_coverage()` and `_pitcher_coverage()` (shared code — benefits the shadow scorer too, no separate fix needed there).

### Fixes Shipped This Session (branch: `fix/leg-cap-lineup-consistency-streak-floor`)

**Fix 1 — `src/engine/parlay_builder.py`:** `MAX_LEGS` 6→4. Docstrings updated. Verified the greedy-selection loop's boundary behavior directly: with `MIN_LEGS == MAX_LEGS == 4`, the early-exit check (`len(legs) >= MIN_LEGS and combined_dec >= floor`) and the hard cap (`len(legs) >= MAX_LEGS`) now converge at the same point — no off-by-one, no infinite-loop risk, confirmed by direct code read of `build_parlays()` in addition to the new tests passing.

**Fix 2 — `src/utils/db.py`:** `log_scored_legs()`'s INSERT for `mlb_scored_legs` — added `lineup_consistency` to the column list, the values tuple (`leg.get("lineup_consistency")`), and the `ON CONFLICT` `COALESCE` clause. Confirmed only one `INSERT INTO mlb_scored_legs` exists in the file.

**Fix 3 — `src/engine/coverage.py`:** `MIN_RECENT_GAMES = 5` constant added; `coverage_recent_10` now returns `None` (skipping the adjustment entirely) when `recent_games < 5`, in both `_hitter_coverage()` and `_pitcher_coverage()`.

**Tests:** `tests/test_bug_fixes.py` (new, 340 lines, 14 tests across 5 classes) — leg-count boundary behavior, `lineup_consistency` column/tuple/conflict-clause presence via source inspection, `coverage_recent_10` floor behavior on both paths. Full suite: 76 passing (62 original + 14 new), 0 failures.

**Status: on branch, not yet merged to master as of this doc update.**

---

## What Happened on July 10, 2026 (Session 20)

### Issue A — game_start_time UTC/ET Contamination Cleanup

**Root cause (confirmed):** `scripts/backfill_game_start_time.py` wrote `game_start_time` as a naive Eastern Time string (via `.astimezone(ET_TZ)` + `.strftime(...)`, stripping tzinfo), while `src/pipelines/enrich_legs.py` stores raw UTC ISO strings. Both values land in the same column in the same format, with no way to distinguish the convention by inspection. 15 `game_pk`s had two conflicting `game_start_time` values across their legs — 503 individual legs affected in `mlb_scored_legs`. `mlb_scored_legs_enriched` had zero conflicts (those game_pks had no enriched rows).

**Scope (verified against Supabase before any fix):**
- 10 game_pks with a clean 4-hour gap (EDT vs UTC — certain timezone mixup): 822983, 823140, 823384, 823707, 824037, 824194, 824360, 824601, 824925, 825009 — 406 rows
- 5 game_pks with other gaps — confirmed via StatsAPI as postponed/rescheduled games, same fix applies: 823471, 824362, 824684, 824840, 824850 — 97 rows

**Fix:** `scripts/fix_game_start_time_contamination.py` — re-fetches authoritative UTC start time from `statsapi.get('game', {'gamePk': game_pk})` (the same call `enrich_legs.py` already makes) and overwrites all affected rows in both tables. Both a dry-run (confirmed in prior session) and live run (this session) executed. Post-fix verification: zero conflicts in both `mlb_scored_legs` and `mlb_scored_legs_enriched`.

**Bleeding stopped:** `scripts/backfill_game_start_time.py` was retired (renamed `.retired`) before the historical fix was applied — no further new contamination possible. A regression-detection query is documented in `SUPABASE_SCHEMA_REFERENCE.md` under "Data Health Checks."

---

### Issue B — Brandon Lowe / hits-over matchup_adj NULL: Root Cause (Reconstructed, Not Log-Confirmed)

**Context:** After `81374e4` (which added `matchup_adj` and related columns to the enriched legs INSERT) was deployed, `/api/admin/run_full_pipeline` was triggered live and the affected legs were re-queried directly from Supabase — `matchup_adj` was still NULL, and `composite_score` was bit-for-bit identical to its pre-fix value, meaning the pipeline had not touched those rows at all. This ruled out "the INSERT bug alone" as a sufficient explanation.

**Root cause (reconstructed from code analysis — not confirmed by log evidence):** Most likely, `run_enriched_pipeline.py` was crashing at the source-label block (lines 510-517) due to a pytz import before `6bdd86b` centralized timezone handling via `src/utils.time_utils.now_et`. The crash happened *after* `_calculate_enriched_score` computed `matchup_adj` correctly, but *before* `_log_enriched_legs` (line 521) ran the INSERT — so `matchup_adj` was calculated but never persisted. That crash was caught by the broad `try/except` in `main.py` wrapping `run_enriched_pipeline`, silencing it entirely.

Both `81374e4` (INSERT columns) and `6bdd86b` (pytz fix) were required: together they allowed the INSERT to run with the correct columns populated. The 2026-07-10 pipeline run (post-`6bdd86b` deployment) confirmed `matchup_adj=2.62` for Brandon Lowe in Supabase, and all previous run_dates (07-07 through 07-09) show NULL — consistent with the fix timing.

**Important caveat:** this root cause was identified by reading the code and git history, not by direct log evidence. Railway logs for the pre-`6bdd86b` timeframe were not accessible (Railway CLI not available locally; browser check was flagged as quick/non-blocking but also not completed this session). The "pytz crash at line 510" explanation is the most coherent one given the code structure and commit history, but it was not directly confirmed by a log line showing the exception. It should be treated as the most likely explanation, not a settled fact.

**Debug instrumentation added and then removed this session:** `[DEBUG whitelist]`, `[DEBUG matchup]`, and `[DEBUG INSERT]` print blocks were added to `run_enriched_pipeline.py` and `enriched_scorer.py` to trace Brandon Lowe through the pipeline — but because the fix was already deployed when the debug run was executed, all three checkpoints showed correct behavior (whitelist: passes, matchup_adj=2.62, INSERT tuple present). The instrumentation was removed before this commit. A temporary `scripts/debug_issue_b.py` was also deleted.

**Status: resolved** — `matchup_adj` populating correctly in live production as of 2026-07-10.

---

## Session 20 Commits

| Commit | Message |
|--------|---------|
| *(this commit)* | fix: game_start_time UTC/ET contamination cleanup + Issue B root cause investigation |

---

## What Happened on July 10, 2026 (Session 19)

### Item 1 — Scratch Handling Rewrite + Dead-Link Bug Fix (`src/apis/lineup_confirmation.py`)

**Old behavior:** on any SCRATCHED leg, void the whole parlay and rebuild from a fresh player pool.

**New behavior (time-gated reduce-path):**
1. When a scratch hits: check how far out each *surviving* leg's game starts.
2. If **all** surviving games are >1 hour out → rebuild (old behavior, unchanged).
3. If **any** surviving game is ≤1 hour out (or already started) → drop only the scratched leg(s), keep the parlay.
   - ≥3 surviving legs: parlay stays pending, resolves next morning off survivors only.
   - <3 surviving legs: void the whole parlay.
4. If a second scratch hits an already-reduced parlay → same rule applied again from scratch against whatever legs remain — no special-cased "second scratch" logic.

**Dead-link bug fixed:** `superseded_by_batch_id` was previously set to a `batch_id` even when no replacement parlay was ever inserted under that batch, creating 7+ confirmed dangling references (e.g. `clr_2026-07-08_2125`). Fix: `superseded_by_batch_id` is now only set when a replacement parlay was actually inserted. When no rebuild happens (time-gate rule or thin pool), `superseded_by_batch_id` stays NULL and a distinct `superseded_reason` is recorded (`'SCRATCHED_NO_REBUILD'` or `'THIN_POOL_NO_REBUILD'`). Also fixed `result_note` on `mlb_pending_lineup_checks` to only count parlays that were actually rebuilt or actually reduced-and-kept — not voided-with-nothing-to-show-for-it.

Voided/dropped individual legs remain as rows in `mlb_parlay_legs_v2` with `outcome='void'` — not deleted — so `num_legs`/`total_odds` can be recalculated off survivors.

**Tests:** `tests/test_lineup_confirmation.py` (9 tests, all passing). Covers: rebuild when all games >1hr out; drop when any game <1hr out; drop-leaves-3 stays pending; drop-leaves-2 voids; second scratch on already-reduced parlay; thin-pool rebuild failure leaves `superseded_by_batch_id` NULL; successful rebuild sets `superseded_by_batch_id` to real batch; `superseded_reason` set correctly on no-rebuild paths.

---

### Item 2 — Manual Dashboard: `coverage_overall` Column (`src/web/static/manual.html`)

Added a "Cov (Overall)" column adjacent to the existing "Cov (vs Hand)" column in the manual dashboard table. "Cov (vs Hand)" continues to show `coverage_vs_hand` when available, falling back to `coverage_overall` when no hand-split exists (matching the production pipeline's logic). The new column always shows raw `coverage_overall`. This makes it immediately visible when the two columns differ and when they're identical (i.e. when no hand-split exists and the fallback is in use).

No backend changes — `get_manual_legs()` already returns `coverage_overall` in the query; this was purely a frontend column addition.

---

### Item 3 — Shadow Scoring Rebuild: Absolute-Value Pitcher/Batter Signals (`src/engine/enriched_scorer.py`)

Replaced all rank-based pitcher signal blocks in `_calculate_enriched_score` (K/9-rank adjustment, pitcher vulnerability scoring block, WHIP-rank adjustment) with a single continuous linear-scale matchup adjustment block. Production scoring (`simple_scorer.py`) is **not touched** — this is shadow pipeline only.

**Formula shape:** `adjustment = ((value − midpoint) / half_range) × max_weight`, clamped to `[−max_weight, +max_weight]` per factor, then combined with a per-prop cap. For hits/over and hits/under, proportional scaling (not hard-clipping) is used when the ERA+WHIP raw sum exceeds the ±7 cap.

**Per-prop weight table:**
| Prop | Factors & weights | Combined cap |
|---|---|---|
| hits/over | ERA ±5, WHIP ±3 (weak pitcher → positive) | ±7 |
| hits/under | ERA ±5, WHIP ±3 (elite pitcher → positive) | ±7 |
| strikeouts/over | K/9 ±5 (high K/9 → positive) | ±5 |
| totalBases/under | Pitcher: ERA ±4, WHIP ±2, K/9 ±1; Batter: OBP ±2, K% ±1.5, BB% ±1, BA ±0.5 (elite pitcher / high K%, low OBP/BA/BB% → positive) | ±12 |

**Ranges used (from actual DB data p5/p95, 11,080 legs May–Jul 2026):**
- ERA: midpoint 4.25, half-range 2.75 (range 1.50–7.00)
- WHIP: midpoint 1.20, half-range 0.50 (range 0.70–1.70)
- K/9: midpoint 8.25, half-range 2.75 (range 5.50–11.00) — user-confirmed 2026-07-10
- Batter ranges (OBP/BA/K%/BB%): league-average estimates; validate after first shadow run with real batter data

**Batter stats for TB/under:** accumulated from the MLB-StatsAPI gameLog endpoint (`get_batter_game_log()`). Field names confirmed live: `atBats`, `hits`, `baseOnBalls`, `strikeOuts`, `plateAppearances`, `hitByPitch`. Minimum 50 PA required; returns None if insufficient. Called only for `stat=="totalBases" and direction=="under"` to avoid unnecessary API calls for other prop types.

**`_compute_blended_era_rank()` preserved:** still called for metadata storage in `enriched`, but no longer drives scoring. `pitcher_vulnerability()` also preserved — still used by `run_enriched_pipeline.py` for stack bonus computation.

**Decimal fix:** raw `pitcher_era`, `pitcher_whip`, `pitcher_k9` come from Supabase as Python `Decimal`. Added `float(value)` coercion inside `_linear_adj()` to prevent `TypeError: unsupported operand type(s) for -: 'decimal.Decimal' and 'float'`. Confirmed via live validation run against 2026-07-09 legs.

**Real-data validation (2026-07-09, 60 legs):**
- hits/over: weak pitchers (ERA 6.71, WHIP 1.61) → +6.93 ✓; elite pitcher (ERA 1.71, WHIP 0.66) → −7.00 (capped) ✓
- strikeouts/over: K/9=11.5 → +5.00 (capped) ✓; K/9=3.6 → −5.00 (capped) ✓
- totalBases/under: elite pitcher (ERA 2.74, WHIP 1.04, K/9 11.7) → +3.84 ✓; weak pitcher → negative ✓

**Tests:** `tests/test_enriched_scorer.py` (37 tests, all passing in ~1s). Covers: `_linear_adj` endpoints/midpoint/None/clamping, `_compute_matchup_adjustment` for all 4 prop types including cap enforcement and direction-sign correctness, and final 5–95 clamp via `_calculate_enriched_score` with monkeypatching.

---

## Session 19 Commits

| Commit | Message |
|--------|---------|
| *(see git log)* | feat: scratch reduce-path + dead-link fix + lineup confirmation tests |
| *(see git log)* | feat: add coverage_overall column to manual dashboard |
| *(see git log)* | feat: enriched scorer rebuild — linear-scale matchup signals + tests |
| *(see git log)* | docs: update session handoff and architecture docs for Session 19 |

---

## What Happened on July 8, 2026 (Session 18)

### Part 1 — Production vs. Shadow Performance Deep-Dive

Prompted by a request to understand what legs are getting selected into parlays and why, and whether the scoring criteria are right, ran an extensive Supabase investigation across both pipelines.

**Scored-leg pool win rates (14-day window, both pipelines nearly identical):**
| Prop | Resolved | Win Rate |
|---|---|---|
| totalBases/under | 1,346 | 57.9% |
| hits/over | 489 | 62.2% |
| strikeouts/over | 220 | 63.6% |
| hits/under | 117 | 51.3% |

**Slot-gate fix recheck (carried over from Session 16, overdue since ~July 5-6):** Void rate dropped exactly as intended post-fix (58.3% → 20.3%, pre/post July 2). But parlay win rate *also* dropped in the same window (27.1% → 10.9%), which needed explaining rather than assuming the fix caused it.

- **Ruled out:** survivorship bias from OOR legs. Parlays *without* any OOR leg actually won *less* post-fix (6.7%, n=30) than parlays *with* one (16.0%, n=25) — the opposite of what survivorship would predict.
- **Actual cause:** strikeouts/over — the strongest-edge prop — saw its in-parlay leg win rate fall from 76.0% (n=75) pre-fix to 56.7% (n=104) post-fix, coinciding with a broader pool-wide softening (69.5% → 55.4%). More concerning: the composite score's K/9-rank differentiation between selected and non-selected legs nearly vanished post-fix (rank gap 17.3 vs 43.9 pre-fix → 15.7 vs 18.8 post-fix), and post-fix, higher-composite-score SO/over legs actually won *less* than lower-scored ones (53.8% vs 57.5%, n=52/40).
- **Conclusion:** the void-rate fix is working as designed; the coincident SO/over softening is either a real pool-composition shift or noise — sample too thin (~1 week) to say which. Flagged for a recheck once another week of data accumulates.

**hits/over coverage ceiling (Session 15 finding, still unimplemented) — reconfirmed with full history:**
| Coverage Bucket | Resolved | Win Rate |
|---|---|---|
| 70.0–74.7% | 739 | 66.2% |
| 75.0–79.7% | 293 | 72.0% |
| 80.0–84.6% | 53 | **62.3%** ⚠️ |
| 87.5–88.9% | 2 | 50.0% |

Same pattern as originally documented (61.4%/50% figures) — climbs then falls off a cliff above ~80%. Still real, still not implemented. n=53 in the 80-84 bucket is a reasonable sample; the top bucket (n=2) is not.

**TB/under combinatorial drag (Session 16 finding) — reconfirmed with fresh 14-day data:**
| Segment (shadow) | Resolved | Win Rate |
|---|---|---|
| Parlays with a TB/under leg | 177 | 15.8% |
| Parlays without one | 15 | 26.7% |

Same direction as Session 16 (13.8% vs 40.0% then). **Note:** this finding was generated under the *old* fixed-4-leg builder. With the builder redesign later this session (see Part 2), the construction-strategy question this was scoping should be re-evaluated under the new 4-6-leg, floor-only logic before any promotion decision — the old numbers may not transfer directly.

**Offense stack bonus (shadow) — confirmed live and positive, contradicting stale README status:**
```
stack_bonus_applied = true:  106 legs, 64.4% win rate, avg vulnerability 0.718
stack_bonus_applied = false: 2,153 legs, 58.8% win rate
```
+5.6pp on n=101 resolved — promising, not yet conclusive, but it's built and firing (README_10.md still says "not yet built" — that file is stale, per the existing Session 16 cleanup item).

**K/9 rank signal — early warning, not yet conclusive.** Bucket analysis on the most recent 21 days showed a non-monotonic, possibly reversed pattern (the worst-ranked-matchup bucket had the highest win rate, 85.7% n=14, vs 60.6% in the best-ranked bucket, n=198) — small samples in the higher buckets make this noisy, but it's directionally consistent with the SO/over softening above. Feeds into the already-pending "re-evaluate K/9 and WHIP with starter-only data" item.

**Row-count inflation discovered in `mlb_parlay_legs_v2`/`mlb_parlay_legs_enriched`:** any leg that survives into multiple pipeline runs (9am/midday/evening) or CLR rebuild batches on the same day gets a *new row* per batch, even though it's the same real-world at-bat. Confirmed ~2.4x inflation ratio across all major props (568 raw rows / 231 distinct day-player pairs for hits/over, etc.). Deduplicating by `(run_date, player_name, stat, direction)` barely moved win rates (hits/over 62.8%→60.0%, strikeouts/over 64.8%→62.6%) but cut the true sample size by more than half. **Documented as a new gotcha in `SUPABASE_SCHEMA_REFERENCE.md` this session — see that file.**

**hits/under deep-dive — initial negative read reversed with more data.** A 14-day dedup pull showed a concerning 36.4% win rate (n=11, real independent outcomes after dedup), heavily concentrated in two repeat players (Pavin Smith, Rodolfo Duran — together 6 of the 11 outcomes). Root cause of the concentration: only 1-3 players/day clear the 65% coverage floor for hits/under (raised from 40% in Session 15) — the pipeline isn't choosing badly among many candidates, there's almost nothing to choose from most days. **Extending to 35 days reversed the read entirely: true win rate 57.9% (n=57)** — the 14-day sample was a cold stretch, not a persistent problem. Lesson: don't draw conclusions on this prop from less than ~30 days given how thin its eligible pool is.

Also confirmed clean: TB/under has not appeared in a production parlay leg since June 18 (Phase 3.7 exclusion, still holding), and shadow's TB/under pool is *not* scarce like hits/under's — 65-120 eligible players/day, a structurally different (oversupply, not scarcity) problem from hits/under's.

---

### Part 2 — Parlay Builder Redesign: Floor-Only Odds, Flexible Leg Count

**The "math problem" hypothesis, tested and confirmed with data.** The theory: forcing exactly 4 legs into a fixed +400/+700 combined-odds band was regularly causing the builder to substitute a lower-scored, higher-odds leg for a better-scored one purely to land inside the band.

- Tested directly: ranking eligible legs (coverage ≥65%, odds -250/+150) purely by `composite_score` and checking what the top-4's combined odds would be — **cleared the +400 floor on only 3 of 21 days (14%)**. The other 18 days, the objectively best 4-leg combination available would have priced below +400, meaning the old builder was structurally required to reach past its own top picks.
- Live proof against real July 7 data: old builder's top parlay used Rafaela/Walker/Gelof/**Turner** (+405), dropping Abreu (composite 75.9) for Turner (composite 74.9, longer odds) purely to hit the band.
- Tested leg-count fix: top-5 pure-quality-ranked legs (no odds engineering) landed inside +400-700 naturally on **17 of 21 days (81%)**; top-4 undershot on 18/21; top-6 badly overshot (800-1,500+) on nearly every day.
- Sanity check against real outcomes: a pure top-4/top-5 pick would have hit as a full parlay on 4/21 and 3/21 days (19.0%/14.3%) — comparable to actual production's 17.5% over the same window, i.e. removing the odds-band constraint doesn't cost win rate in this sample.

**Decision:** eliminate the +400/+700 band. Replace with a +400 floor only (no ceiling). Replace the fixed 4-leg requirement with a 4-6 leg range. Keep max-2-legs-per-game and player-diversity constraints unchanged.

**Implementation (`src/engine/parlay_builder.py`, via Claude Code):** the entire branch-and-bound combinatorial search (~180 lines, including timeout handling and candidate deduplication) was replaced with a much simpler greedy selector: sort the eligible pool by `composite_score` descending, walk it applying the existing constraints, and stop as soon as both (a) at least 4 legs are selected and (b) combined odds clears +400 — only reaching past 4 legs when the floor isn't cleared yet, capped at 6. If the best 6 legs still can't clear +400, that parlay slot produces nothing (same behavior as the old "insufficient pool" case). `TOTAL_LEGS` is kept defined as an alias for the new `MIN_LEGS` constant so `src/apis/lineup_confirmation.py`'s existing import doesn't break. Both the shadow pipeline and CLR rebuilds call this same function, so the fix applies to all three call sites automatically.

Live-data validation: re-running old vs. new builder against the same real July 7 pool confirmed the fix works exactly as intended — the new Parlay 1 includes *both* Abreu and Turner (5 legs, +661) instead of choosing between them.

A standalone 7-case test script validated the new logic (4-6 leg range, floor enforcement, no ceiling, constraint preservation) — **but this test script was never committed to the repo** (it lived in `/tmp` during the build session and is now gone). See Pending Items #3.

---

### Part 3 — Manual Parlay Dashboard (`/manual`)

**Goal:** let the operator see the same full-signal data the automated pipeline uses, hand-pick 4-6 legs using human judgment, and have that pick resolve automatically in the same morning run as automated parlays — enabling a real manual-vs-automated comparison over time.

**Architecture (built via Claude Code, iterated across several rounds this session):**
- `src/utils/db.py`: `get_manual_legs(run_date)` — same dedup logic as the existing `get_scored_legs()`, LEFT JOINs `mlb_scored_legs_enriched` by `odd_id` for `pitcher_vulnerability`, `park_factor`, `blended_era_rank` (nullable where the shadow pipeline hasn't scored that leg).
- `src/web/server.py`: `GET /manual` (page), `GET /api/manual/legs` (data, auth required), `POST /api/manual/parlay` (submit, auth required). Submission re-fetches all leg data server-side from `mlb_scored_legs` by `odd_id` — nothing client-supplied (odds, scores, coverage) is trusted. Validates 4-6 legs, no duplicate batter, max 2 legs/game. Saves via the existing `save_parlay_recommendations_v2()` with **`source='manual_pick'`** — distinct from the existing `'manual'` source value, which is the "Regenerate Now" button (still the algorithm, on demand) and was already in use before this session.
- **Confirmed `parlay_outcome_resolver.py` has no source filter** — it resolves anything `outcome='pending'` for the run_date regardless of source. Manual picks flow through the existing 9am morning run automatically with zero additional wiring.
- `src/web/static/manual.html`: standalone table UI — every batter row carries its full production scoring signal set plus its probable opposing pitcher's ERA/K9/WHIP/hand/vulnerability, no join needed client-side. Sortable, filterable, percentile-based heat coloring, a live parlay slip with running combined odds, submit button.

**No database schema changes were needed** — `source` was already a free-text column. No migration was applied.

**Iteration rounds this session (chronological, each triggered by real testing or review, not speculation):**

1. **Initial build** (commit `5600b2e`) — builder rewrite + full dashboard (db.py, server.py routes, manual.html) bundled together since the dashboard files were untracked from an earlier uncommitted pass. Included two design decisions made during code review before first deploy: (a) auth probe was tightened to only grant access on an exact 200 response instead of "anything but 401" (closing a real hole where a 500 would have let someone in), and (b) the +400 floor was changed from a hard reject to a non-blocking `meets_floor` field on manual submissions — hard-blocking a human's confident pick below +400 would reintroduce the exact "payout target fighting leg quality" problem the builder redesign was meant to fix, just applied to human judgment instead of an algorithm.

2. **"Password not working"** — diagnosed as *not* actually a password problem. Root cause: `pitcher_era`, `pitcher_k9`, `pitcher_whip`, `pitcher_vulnerability`, `blended_era_rank` are Postgres `NUMERIC` columns, which psycopg2 returns as Python `Decimal` — and `json.dumps()` can't serialize `Decimal`, so `/api/manual/legs` was throwing and returning 500. The stricter auth check from step 1 (correctly) couldn't distinguish that 500 from a real 401, so it displayed "Authentication failed," sending the user chasing the wrong password. **Fix (commit `b4322c1`):** `json.dumps(legs, default=str)` (matches the existing convention already used elsewhere in the file) plus differentiated error messaging — 401 shows "Incorrect password," any other status shows the actual status code.

3. **UI review from screenshots** surfaced four real issues, diagnosed by reading the live file and cross-checking the actual DB response rather than guessing:
   - Line/Odds columns blank: `manual.html` referenced `best_line`/`best_odds`, but the actual returned columns (raw `mlb_scored_legs` fields) are `line`/`odds`. Six call sites had this bug, not just the table.
   - Opposing pitcher name blank despite ERA/K9/WHIP populating: referenced `opposing_pitcher_name`, actual field is `pitcher_name`.
   - Cramped rows, header appearing to sink below row 1: tight padding (4-6px) plus a hardcoded `position: sticky; top: 53px` that didn't account for a status line rendered between the header and table.
   - Requested: drop the `batting_order` column, move `lineup_check_status` to last.
   - **Fix (commit `c920f32`):** all field-name references corrected, column set updated, padding/font increased, and the sticky header offset switched from a hardcoded pixel value to a JS function measuring `header.offsetHeight` at render time.

4. **Sticky header fix attempt 1 failed** — screenshot showed the problem *worse*, with a partially-clipped row visible under the header, indicating the header was overlapping mid-table, not just misaligned. The JS-measured-offset approach was diagnosed as inherently fragile (timing- and content-dependent) rather than tuned further. **Structural fix (uncommitted as of this write-up, see Open Item below):** replaced page-level scroll entirely — `body` becomes a `height: 100vh` flex column, `header` takes natural height, `.table-wrap` gets `flex: 1; overflow-y: auto` and becomes its own scrolling container, so `thead { position: sticky; top: 0 }` sticks correctly with no JS and no measurement, by construction. Neither Claude Code nor Claude (chat) had a way to render/screenshot this fix to confirm visually — user was asked to push and check the live page directly given the low blast radius of a pure CSS change. User reported "Looks better" after doing so.

**Open item:** the final structural sticky-header fix (the flex-column rewrite) was shown as a diff and explicitly **not pushed** pending visual confirmation, per the request that made the change. The user's "Looks better" response strongly implies they pushed it and checked the live site, but this was never explicitly confirmed in-session, and no commit hash was captured for it. **First thing to verify next session:** `git log -1` to get the actual hash, confirm it's live on Railway, and update this doc.

---

## Session 18 Commits

| Commit | Message |
|--------|---------|
| `5600b2e` | feat: manual parlay dashboard + greedy builder + two auth/floor fixes |
| `b4322c1` | fix: handle Decimal serialization in /api/manual/legs + differentiate auth errors |
| `c920f32` | fix: correct field names, layout, and column set on manual parlay dashboard |
| *(unconfirmed)* | fix: sticky header structural rewrite (flex-column layout) — diff shown, push status not confirmed in-session |

**Base commit at session start:** `3d7aabc` (July 7 — "fix: surface SGO timeout failures and regen pipeline errors to frontend"). This commit was previously undocumented; while investigating it this session, also confirmed the long-flagged "unknown commit `85b5bd5`" (Session 16) is nothing more than a docs-only commit (`Update SESSION_HANDOFF.md`) — that open item is now resolved, no code content, no further action needed.

---

## Production Performance Check — July 8-9, 2026 (checked 2026-07-10, end of Session 20)

**Requested as a sanity check before closing out Session 20.** Parlay-level results looked alarming at first glance — worth documenting the actual finding so it isn't re-investigated from scratch next session.

**Parlay-level:** 21 of 22 resolved parlays lost across both days (4.5% win rate). Only one parlay won (a `confirmed_lineup_resolution` rebuild on 7/8).

**Leg-level (deduped, matches the row-inflation-safe query pattern in `SUPABASE_SCHEMA_REFERENCE.md`):**
| Date | Prop | Resolved | Win Rate |
|---|---|---|---|
| 7/8 | hits/over | 22 | 59.1% |
| 7/8 | strikeouts/over | 9 | 33.3% |
| 7/9 | hits/over | 20 | 65.0% |
| 7/9 | strikeouts/over | 11 | 45.5% |

**Conclusion: not a new bug.** hits/over is at or above its ~62% historical baseline on both days — no concern. strikeouts/over is well below its ~61.6% baseline on both days (combined 8/20 = 40%), which is more data in the same direction as the already-tracked "SO/over pool softening" item (see Pending Item #7 below, elevated this session). The parlay-level near-shutout is consistent with what leg-level AND-condition math predicts once a weak prop is mixed into 4-6-leg parlays — e.g. 3 hits/over legs at ~62% × 2 strikeouts/over legs at ~40% ≈ 3.8% expected parlay win rate, close to the ~4.5% actually observed. Not flagged as a new investigation.

**Ruled out as a cause:** confirmed none of the three scratch events on these two days (Tyler Callihan, Rodolfo Duran on 7/8; Willson Contreras on 7/9) used Item 1's new time-gated reduce-path — Item 1 hadn't deployed yet at the time these ran, so nothing from Session 19/20's fixes touches this window. The dangling `clr_2026-07-08_2125` reference also shows up here again — this is the same historical dead-link case already found and explicitly not backfilled (Item 1 fix is going-forward-only), not a new occurrence.

---

## Pending Items — Next Session

### 1. Commit and push Sessions 22+23's work (High Priority — as of this doc update, being done now)
Nothing from either session was committed as of this doc's own writing. Backfill scripts, `dashboard_api/` additions, `server.py` scheduler wiring (both `_reference_data_scheduler()` and the schedule cut), and `src/pipelines/prop_legs_capture.py` all sit uncommitted. Until pushed: `mlb_team_standings`/leaderboard snapshots stay frozen at `as_of_date: 2026-07-29`, the 3-run/day schedule stays live (SGO cost keeps accruing at the higher rate past the 8/1 tier downgrade), and no prop-line capture happens at all.

### 2. Watch the first live 9 AM capture run once deployed (High Priority, new Session 23)
`src/pipelines/prop_legs_capture.py` was validated via isolated test scripts (`scripts/test_prop_legs_capture.py`, `scripts/test_prop_legs_resolution.py`), not via a real production `run_pipeline()` invocation — the wiring itself (the `if not skip_resolution:` gate in `main.py`, the try/except around the capture call) has not been exercised inside the real morning run. Check Railway logs for `[prop_legs_capture]` output on the first post-deploy 9 AM run, and check `mlb_prop_legs_history` row counts the same day.

### 3. Confirm SGO Pro→Amateur downgrade lands cleanly on 2026-08-01 (High Priority, new Session 23)
Schedule cut and quota math (§Session 23) assume the Amateur tier's 2,500/month cap starting 8/1. Watch `mlb_sgo_request_log`/`check_sgo_usage()`'s own quota warnings for the first few days after the downgrade to confirm actual usage tracks the ~744/month projection, not the untested worst case.

### 4. Consider fixing the mlb_parlay_recommendations_v2.source labeling inconsistency found this session (Low Priority, new Session 23, flagged not fixed)
`'midday'`/`'evening'` are written literally instead of `'auto_12pm'`/`'auto_530pm'` as documented — pre-existing, unrelated to anything changed this session, low priority since `'midday'` no longer fires at all post-schedule-cut (only `'evening'` remains affected going forward).

### 5. Build player/team drill-down cards — Diamond Line dashboard step 4 (Medium Priority, new Session 22, explicitly deferred by operator)
Last piece of the approved dashboard scoping plan. Click-through from the new Standings/Leaderboards tables (or a search) to a player game-log card (`mlb_player_batting_logs`/`_pitching_logs`) or team profile card (`mlb_teams` + standings history + roster + recent schedule from `mlb_games`). Depends on nothing new — the underlying data (game logs, season-stat time series) is already backfilled and validated. Most complex piece of the four (real interactivity, modal/route design) — that's why it was sequenced last, not because anything blocks it.

### 6. Merge Session 21 branch to master and deploy (High Priority — blocks everything below that needs live data)
`fix/leg-cap-lineup-consistency-streak-floor` is reviewed and ready (diffs verified line-by-line) but not yet merged as of this doc update. Nothing below involving new data can start until this is live.

### 7. Confirm the lineup_consistency Step 5b filter is actually running (High Priority, new Session 21)
The DB-persistence fix means `lineup_consistency` will start populating going forward, but that doesn't confirm the upstream filter in `main.py` (Step 5b — removes legs with `lineup_consistency < 0.70` unless injury-exception) has been successfully calling the MLB Stats API this whole time. The whole block is wrapped in a broad `try/except` that would silently swallow an import or runtime error. Check a live Railway log for `[5b]`/`[lineup_consistency]` print output on a recent run to confirm it's actually executing and removing legs, not silently hitting the except branch every run.

### 8. Watch leg-cap revert live performance (High Priority, new Session 21)
Parlay win rate should move back toward the 15-20% range within days of the fixed-4-leg revert going live. If it doesn't, that's a signal the "doesn't fully restore pre-redesign EV" gap found in this session's simulation (Investigation 3) is real and not just small-sample noise — worth a fresh pre/post comparison after ~1-2 weeks.

### 9. Scope and build the pitcher ERA signal rebuild (High Priority, new Session 21, explicitly deferred by operator this session)
Replace cumulative season ERA with recent-starts ERA: build `get_pitcher_game_log()` (same StatsAPI gameLog pattern as the existing batter function), compute ERA over the pitcher's last 5 starts, raise the minimum sample floor from 5.0 IP to ~3 starts. Backtest with the same controlled-band method used this session (bucket by base coverage, compare win rate across ERA tiers) before wiring it into `simple_scorer.py` — do not ship without that validation, since the original signal never got this treatment and that's exactly how it went unnoticed this long.

### 10. Re-validate lineup_consistency's 0.70 filter threshold once data accumulates (Medium Priority, new Session 21)
No historical data exists to backtest the 0.70 cutoff itself — it's never been persisted before this session's fix. Once a few weeks of live data exist, check whether 0.70 is actually the right line, the same way other thresholds in this project have been tuned from real data rather than left at their original guess.

### 11. Monitor K9-rank signal with more data (Medium Priority, new Session 21)
Shares the same theoretical data-source risk as the now-confirmed-inverted ERA signal (same `_fetch_pitcher_season_stats()` call), but controlled testing this session was mixed/inconclusive rather than clearly backwards. No action taken — revisit with a larger sample before deciding either way.

### 12. Complete the manual-pick end-to-end test (High Priority — never actually completed)
Submit one real parlay from `/manual`, confirm it lands in `mlb_parlay_recommendations_v2` with `source = 'manual_pick'` and correct leg data in `mlb_parlay_legs_v2`, then confirm it resolves correctly (not left `pending`) after the next 9am run. Deferred through Sessions 18, 19, 20, 21, 22, and 23 (not touched — out of scope for the backfill/dashboard/SGO work). This is also what the separate `dashboard_api/` → `server.py` Phase 2 merge decision is gated on — see the note under Session 22 below.

### 13. Validate batter ranges for shadow scorer after first shadow run (High Priority, new Session 19)
The batter OBP/BA/K%/BB% ranges in `enriched_scorer.py` use league-average estimates. After the first few shadow runs, pull actual p5/p95 from the populated batter stats and update `_OBP_MID/_OBP_HALF` etc. to match the real range of this leg pool (same methodology as the pitcher ranges were derived from actual DB data).

### 14. Compare shadow vs. production win rate after a few weeks (Medium Priority, new Session 19)
The enriched scorer rebuild is live in shadow. Check it against the comparison queries in this doc and `SUPABASE_SCHEMA_REFERENCE.md` after 3-4 weeks of shadow runs. Look for: shadow win rate > production win rate on the same prop types, and shadow edge (WR vs. odds-implied probability) vs. production edge. Session 21 note: the 7/17-19 window showed shadow's best week (19.4%) vs. production's worst (6.1%) — biggest gap of the season, but still only n=36, same small-sample caveat as everything else this window.

### 15. Re-evaluate TB/under construction strategy under the new builder (Medium Priority, carried)
Combinatorial-drag numbers were generated under the old fixed-4-leg builder. Session 21 note: the builder is now back to fixed-4-legs (reverted), so this analysis's original fixed-4-leg assumption is valid again — may not need re-running after all now that Session 18's 4-6-leg structure has been reverted. Confirm before spending time on this.

### 16. SO/over pool softening — recheck with more volume (Priority: High, carried from Session 18/20)
The composite score's K/9-rank differentiation weakened post-slot-gate-fix. Three consecutive weak reads as of Session 20 (Session 18's ~1 week + 7/8 33.3% + 7/9 45.5%, all vs. ~61.6% baseline). Session 21's leg-level check on 7/17-19 didn't add a clean fourth read in either direction — strikeouts/over dipped to 51.5% the week of 7/6 but recovered to 68.4% the week of 7/13 — so this remains unresolved, not newly confirmed or newly cleared.

### 17. Cancel SGO Pro subscription (High Priority, carried from Session 17 — see also item 3 above, new Session 23, about confirming the downgrade lands cleanly once it happens)
Code change validated. Account-level downgrade is a manual action outside the codebase — deadline 2026-08-01.

### 18. Add hits/over coverage ceiling at ~80% (High Priority, carried from Session 15, reconfirmed)
Full-history data still shows the climb-then-cliff pattern (72.0% at 75-79.7%, 62.3% at 80-84.6%). Not yet implemented.

### 19. Fix void_reason logging gap (Medium Priority, carried from Session 16, still not done)
`void_reason` on `mlb_scored_legs` is still NULL for the large majority of voided legs.

### 20. Fix the mlb_scored_legs game_pk mismatch found in Session 22 (Medium Priority, carried from Session 22, flagged not fixed)
8 of 1,320 checked `game_pk` values in `mlb_scored_legs` belong to future/unplayed games rather than the game actually happening on that leg's `run_date` — confirmed directly against the live API. Root cause not investigated (likely an odds-provider/game-matching issue upstream of where the read-only backfill touches). Out of scope (told not to modify `mlb_scored_legs`) — worth a proper root-cause session given it affects a production table's key integrity, even at a small (~0.6%) rate.

### 21. Consider fixing get_totals_props()'s wrong key prefix (Low Priority, new Session 23, flagged not fixed)
`src/apis/sportsgameodds.py`'s `get_totals_props()` searches for `runs-*` keys; live SGO responses use `points-*`. Confirmed dormant (never called elsewhere in the codebase, via grep) rather than actively broken — low priority precisely because nothing depends on it. `src/pipelines/prop_legs_capture.py`'s own game-line parsing already uses the correct prefix independently, so this isn't blocking anything; fix opportunistically if that function is ever wired up for real use.

### 22. Project file cleanup (Low priority, carried, still not done)
Retire `README_10.md` and other stale files from Project Knowledge.

---

## System Health Indicators

### Green Lights
✅ opp_pitcher_id fix and point-in-time backfill validated against live production data before being trusted — including catching a real coupling bug (own-role and opposing-pitcher fills incorrectly gated together) that would have silently skipped ~12,207 fillable-in-the-future rows (Session 24)
✅ Coverage-vs-matchup analysis reproduced the prior baseline's exact n/win-rate numbers before building anything new, then found (rather than assumed) two methodological issues — the coverage_overall hard floor and the pre-6/9 scoring-era mismatch — that reshaped the whole analysis instead of proceeding on a flawed premise (Session 24)
✅ A stale "Session 21 branch pending merge" status, carried unverified across two prior session-handoff updates, was checked directly against git history and corrected (Session 24) — `git merge-base --is-ancestor` confirmed it was already merged
✅ SGO billing verification used SGO's own account-level usage counter (before/after delta), not the codebase's own local event-count logging — the local metric couldn't actually have distinguished per-event from per-market billing, and the session caught that before relying on it further (Session 23)
✅ Response-completeness check surfaced a real dormant bug (get_totals_props()'s wrong key prefix) via live testing rather than accepting "0 game lines" at face value (Session 23)
✅ Schedule-cut impact verified against 7 days of real mlb_sgo_request_log data, not just the handoff's own projection (Session 23)
✅ A genuine gap in the literal migration spec (partial-unique-index dedup for NULL player_id) caught and fixed before it caused silent duplicate accumulation in production (Session 23)
✅ Both new pipelines (capture, resolution) tested in isolation before being trusted — resolution against known real outcomes (7/7 passed), capture via a standalone script separate from the full production pipeline — catching two real bugs (ON CONFLICT target, Athletics abbreviation) before either went anywhere near the daily schedule (Session 23)
✅ Reference-data backfill fully validated, not just run-and-assumed-correct (Session 22) — 3 independent live box-score spot-checks matched exactly, standings/leaderboard output matched the operator's own MLB.com screenshots field-for-field
✅ Draft backfill script's real bugs (batting logs that would never have inserted, is_starter always False, missing FK) caught via live API inspection BEFORE the first run, not discovered after (Session 22)
✅ Dashboard scoping plan presented and explicitly approved before any dashboard code was written (Session 22) — including the support.js generated-bundle finding that changed the technical approach
✅ season_stats.py DB-first swap kept a live-API fallback specifically to avoid a silent regression for non-qualified players — caught during design, not after shipping (Session 22)
✅ New scheduled job (_reference_data_scheduler) NOT wired in silently — explicit sign-off sought per WORKFLOW_RULES.md's Red Flags section before touching production's scheduler (Session 22)
✅ Parlay builder leg-count regression found and reverted with real EV evidence (Session 21) — pre-redesign fixed-4-leg era: +$0.128 EV/$1 (n=486); post-redesign 4-6 leg era: −$0.42 to −$0.66 EV/$1
✅ lineup_consistency DB-persistence bug root-caused via direct trace from main.py → db.py, not guessed (Session 21) — confirmed 100% NULL across 18,356 rows before fix
✅ coverage_recent_10 missing sample floor root-caused via direct code read and inconsistency with coverage_overall's existing floor (Session 21)
✅ Pitcher ERA signal inversion confirmed via controlled analysis (base-coverage-banded), not just a raw bucket comparison that could've been a selection-bias artifact (Session 21)
✅ 14 new tests committed alongside all three Session 21 fixes — 76/76 passing
✅ Scratch reduce-path rewrite validated with 9 committed tests — covers all time-gate branches, void-on-thin-survivors, second-scratch re-application
✅ Dead-link bug fix root-caused via live Supabase query (7+ confirmed dangling `superseded_by_batch_id` references) before code was changed
✅ Shadow scorer rebuild validated against real 2026-07-09 legs before deployment — all four prop types directionally correct, caps enforced
✅ K/9 range confirmed by user (5.5–11.0) rather than deployed on assumption — per session prompt requirement

### Yellow Flags
✅ ~~Sessions 22, 23, AND 24's entire body of work is uncommitted as of this doc's own writing~~ — **corrected Session 25:** this was already stale when written; confirmed via `git log` that Sessions 22-24's combined work was committed and deployed as `1db8918` on 2026-07-31. Worth re-verifying git state at the start of every session per this project's workflow rules, rather than trusting a prior doc update's status without re-checking.
✅ ~~`mlb_parlay_legs_v2` shows zero new legs for any `run_date` from 2026-07-24 through 2026-07-30 (last activity 2026-07-23)~~ — **RESOLVED Session 25:** root-caused (unbounded `statsapi.*` network calls, no timeout, silently blocking the pipeline thread — see top of this doc and `ARCHITECTURE_DECISIONS.md` §37) and fixed. Confirmed live via two forced full-pipeline runs completing cleanly.
⚠️ Coverage-vs-matchup analysis (Session 24) found `coverage_overall`/`composite_score` only reflect the current scoring pipeline from 2026-06-09 onward — pre-6/9 rows use a different, non-comparable scoring formula. Worth checking whether other historical analyses in this document implicitly mixed both eras without accounting for it.
⚠️ src/pipelines/prop_legs_capture.py's wiring into the real production run_pipeline() has not itself been exercised — only tested via standalone scripts that replicate the relevant steps. Watch the first live 9 AM run post-deploy (Session 23)
⚠️ mlb_parlay_recommendations_v2.source values are literally 'midday'/'evening' instead of the documented 'auto_12pm'/'auto_530pm' — pre-existing, found not fixed (Session 23)
⚠️ get_totals_props() has a wrong key prefix (runs- vs. the actual points-) — confirmed dormant/unused, found not fixed (Session 23)
⚠️ mlb_scored_legs.game_pk mismatch found for 8/1,320 checked rows (games attached to the wrong, future game_pk) — flagged, not root-caused or fixed (Session 22)
⚠️ Diamond Line dashboard step 4 (player/team drill-down cards) not built — deferred by operator choice, not blocked (Session 22)
⚠️ Pitcher ERA signal confirmed inverted but not yet fixed — rebuild scoped (recent-starts ERA), explicitly deferred by operator this session, still active and unchanged in production
✅ ~~Session 21 fixes on branch, not yet merged/deployed~~ — **corrected Session 24:** confirmed via `git merge-base --is-ancestor` that this branch IS an ancestor of current `master` (`65ce276`) — already merged and deployed. This flag had been carried stale across Sessions 22 and 23 without being re-verified against actual git state.
⚠️ lineup_consistency Step 5b filter's actual live behavior (vs. its persistence, now fixed) still unconfirmed — needs a Railway log check
⚠️ Whether the fixed-4-leg revert fully restores pre-redesign profitability is unconfirmed — simulation suggested a partial gap (−$0.25 to −$0.34 EV vs. the pre-redesign +$0.128), possibly noise, possibly a second unisolated factor
⚠️ Batter OBP/BA/K%/BB% ranges in enriched scorer use league-average estimates — need validation after first shadow runs
⚠️ New shadow scorer running live but no performance comparison possible yet — check after 3-4 weeks
⚠️ Manual pick end-to-end flow (submit → resolve) still never actually tested (carried 4 sessions)
⚠️ SO/over pool softening — still unresolved (carried, High Priority) — Session 21 didn't add a clean additional read either direction
⚠️ TB/under construction-strategy numbers may now be valid again since the builder reverted to fixed-4-legs — needs confirming before re-running
🔲 SGO Pro subscription cancellation still not confirmed (carried multiple sessions)
⚠️ hits/over ~80% coverage ceiling still not implemented (carried, reconfirmed)
⚠️ void_reason logging gap still not fixed (carried)

### Red Flags
None currently

---

## Session 17 Handoff (July 7, 2026) — Preserved for Reference

✅ CLV tracking layer removed — no demonstrated predictive value, was 52% of total SGO volume (78% of July)
✅ Fix deployed: commit `d3a642c`
✅ Retrospective validation: ~1,080-1,350 projected objects/month, both under the 2,500/month free-tier cap
🔲 SGO Pro subscription cancellation itself not yet confirmed — carried to Session 18, still not done

See the prior version of this document (or git history) for full Session 17 detail, including the CLV predictive-value test methodology, the measurement-artifact catch (June 16 catch-up burst), and Session 16's batting-order slot-gate removal analysis.

---

**Last Review:** August 4, 2026 (Session 26)
**System Status:** ✅ Operational — both the 12-day silent parlay-pipeline stall (Session 25, `ARCHITECTURE_DECISIONS.md` §37) and the parlay builder's zero-recovery-on-missed-floor bug (Session 26, §38) are root-caused, fixed, deployed, and confirmed live. Session 26's live trigger wrote 5 real parlays to `mlb_parlay_recommendations_v2`/`mlb_parlay_legs_v2` for today, confirmed via direct SQL query — the strongest available evidence short of the real scheduled trigger. Sessions 22, 23, and 24's work was already live as of `1db8918` (2026-07-31). Session 21's fixes remain confirmed merged and deployed. Still not directly observed: a real scheduled-run (9 AM/5:30 PM ET, not a manual trigger) producing parlays end-to-end.
**Next Review:** Watch the next real scheduled run (9 AM/5:30 PM ET) confirm parlays get built and saved without any manual trigger — the one verification step neither Session 25 nor 26 could perform directly / watch the first live 9 AM prop-line capture run and confirm the 8/1 SGO tier downgrade tracks the ~744/month projection / re-run the coverage-vs-matchup analysis 2026-08-06 / then decide: continue to Diamond Line dashboard step 4, or return to the remaining Session 21-era queue (confirm lineup_consistency Step 5b filter live, watch leg-cap-revert performance, build the pitcher ERA rebuild, complete manual-pick end-to-end test — carried multiple sessions now)
**Pending Decisions:** Whether to continue straight to dashboard step 4 or the older queue first (operator's call), whether/when to root-cause the mlb_scored_legs game_pk mismatch (Session 22), whether the `'midday'`/`'evening'` source-labeling gap and the dormant `get_totals_props()` bug are worth fixing (both Session 23, both low priority/pre-existing), Pitcher ERA rebuild scope and timeline (scoped Session 21, not started), whether/how to promote totalBases to production given the coverage-vs-matchup analysis's supportive finding for that bet type (Session 24, operator's call), SGO Pro cancellation (user action, deadline 2026-08-01)
