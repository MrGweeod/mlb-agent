# MLB Parlay Agent — Session Handoff
**Last Updated:** July 20, 2026 (Session 21 — Post-All-Star-break production investigation: parlay-builder leg-count EV regression found and reverted, lineup_consistency DB-persistence bug found and fixed, pitcher ERA signal confirmed inverted (rebuild scoped, not implemented), coverage_recent_10 sample floor added)

## Current Status
✅ **OPERATIONAL — SESSION 21 FIXES ON BRANCH, PENDING MERGE TO MASTER**
✅ **Parlay builder reverted: MAX_LEGS 6→4 (fixed 4-leg structure restored) — Session 18's floor-only/4-6-leg redesign proven -EV against live data, reverted this session**
✅ **`lineup_consistency` DB-persistence bug fixed — `db.py`'s INSERT into `mlb_scored_legs` never included the column; had been silently NULL for 100% of ~18,000+ rows since project inception**
✅ **`coverage_recent_10` sample-size floor added (`MIN_RECENT_GAMES = 5`) — previously any recent_games > 0 (even 1) produced a trusted value; fixed in both hitter and pitcher paths (shared code, benefits shadow too)**
✅ **14 new tests committed (`tests/test_bug_fixes.py`) — 76 total passing (62 original + 14 new)**
⚠️ **Pitcher ERA signal confirmed inverted via controlled analysis (holding base coverage constant) — same root-cause pattern as the WHIP signal removed Session 15 (both pulled from the same uncapped, role-blind, 5.0-IP-floor cumulative season stat). Rebuild scoped (recent-starts ERA via a new `get_pitcher_game_log()`, higher IP floor, backtest before shipping) but explicitly NOT implemented this session — deferred by user decision. Still ACTIVE and unchanged in `simple_scorer.py`.**
⚠️ **K/9-rank signal shares the same underlying data-source risk as ERA (same `_fetch_pitcher_season_stats()` call) but controlled testing came back mixed/inconclusive, not clearly inverted — monitor, no action taken**
🔲 **Pending: confirm the Step 5b lineup_consistency pre-filter in `main.py` is actually running successfully against live Railway logs — persistence bug fix doesn't tell us whether the upstream filter itself has been silently no-op'ing this whole time**
🔲 **Pending user action (carried from Session 17): cancel SGO Pro subscription ($149/mo)**
🔲 **Pending: first true end-to-end test of the manual pick flow (submit → resolve) — still not done**

**Carried from Session 20 (still true, no change this session):**
✅ Scratch handling rewritten: time-gated reduce-path (drop legs, keep parlay) vs. rebuild-path
✅ Shadow scoring rebuilt: absolute-value linear-scale pitcher/batter signals replace rank buckets
✅ Issue A (game_start_time UTC/ET contamination) and Issue B (Brandon Lowe/matchup_adj NULL) — both resolved, reconfirmed clean this session (health-check query re-run, zero conflicts since 7/10)
⚠️ New shadow scorer running live — compare shadow vs. production win rate after a few weeks (still pending, see Pending Items)

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

### 1. Merge Session 21 branch to master and deploy (High Priority — blocks everything below that needs live data)
`fix/leg-cap-lineup-consistency-streak-floor` is reviewed and ready (diffs verified line-by-line) but not yet merged as of this doc update. Nothing below involving new data can start until this is live.

### 2. Confirm the lineup_consistency Step 5b filter is actually running (High Priority, new Session 21)
The DB-persistence fix means `lineup_consistency` will start populating going forward, but that doesn't confirm the upstream filter in `main.py` (Step 5b — removes legs with `lineup_consistency < 0.70` unless injury-exception) has been successfully calling the MLB Stats API this whole time. The whole block is wrapped in a broad `try/except` that would silently swallow an import or runtime error. Check a live Railway log for `[5b]`/`[lineup_consistency]` print output on a recent run to confirm it's actually executing and removing legs, not silently hitting the except branch every run.

### 3. Watch leg-cap revert live performance (High Priority, new Session 21)
Parlay win rate should move back toward the 15-20% range within days of the fixed-4-leg revert going live. If it doesn't, that's a signal the "doesn't fully restore pre-redesign EV" gap found in this session's simulation (Investigation 3) is real and not just small-sample noise — worth a fresh pre/post comparison after ~1-2 weeks.

### 4. Scope and build the pitcher ERA signal rebuild (High Priority, new Session 21, explicitly deferred by operator this session)
Replace cumulative season ERA with recent-starts ERA: build `get_pitcher_game_log()` (same StatsAPI gameLog pattern as the existing batter function), compute ERA over the pitcher's last 5 starts, raise the minimum sample floor from 5.0 IP to ~3 starts. Backtest with the same controlled-band method used this session (bucket by base coverage, compare win rate across ERA tiers) before wiring it into `simple_scorer.py` — do not ship without that validation, since the original signal never got this treatment and that's exactly how it went unnoticed this long.

### 5. Re-validate lineup_consistency's 0.70 filter threshold once data accumulates (Medium Priority, new Session 21)
No historical data exists to backtest the 0.70 cutoff itself — it's never been persisted before this session's fix. Once a few weeks of live data exist, check whether 0.70 is actually the right line, the same way other thresholds in this project have been tuned from real data rather than left at their original guess.

### 6. Monitor K9-rank signal with more data (Medium Priority, new Session 21)
Shares the same theoretical data-source risk as the now-confirmed-inverted ERA signal (same `_fetch_pitcher_season_stats()` call), but controlled testing this session was mixed/inconclusive rather than clearly backwards. No action taken — revisit with a larger sample before deciding either way.

### 7. Complete the manual-pick end-to-end test (High Priority — never actually completed)
Submit one real parlay from `/manual`, confirm it lands in `mlb_parlay_recommendations_v2` with `source = 'manual_pick'` and correct leg data in `mlb_parlay_legs_v2`, then confirm it resolves correctly (not left `pending`) after the next 9am run. Deferred through Sessions 18, 19, 20, and 21.

### 8. Validate batter ranges for shadow scorer after first shadow run (High Priority, new Session 19)
The batter OBP/BA/K%/BB% ranges in `enriched_scorer.py` use league-average estimates. After the first few shadow runs, pull actual p5/p95 from the populated batter stats and update `_OBP_MID/_OBP_HALF` etc. to match the real range of this leg pool (same methodology as the pitcher ranges were derived from actual DB data).

### 9. Compare shadow vs. production win rate after a few weeks (Medium Priority, new Session 19)
The enriched scorer rebuild is live in shadow. Check it against the comparison queries in this doc and `SUPABASE_SCHEMA_REFERENCE.md` after 3-4 weeks of shadow runs. Look for: shadow win rate > production win rate on the same prop types, and shadow edge (WR vs. odds-implied probability) vs. production edge. Session 21 note: the 7/17-19 window showed shadow's best week (19.4%) vs. production's worst (6.1%) — biggest gap of the season, but still only n=36, same small-sample caveat as everything else this window.

### 10. Re-evaluate TB/under construction strategy under the new builder (Medium Priority, carried)
Combinatorial-drag numbers were generated under the old fixed-4-leg builder. Session 21 note: the builder is now back to fixed-4-legs (reverted), so this analysis's original fixed-4-leg assumption is valid again — may not need re-running after all now that Session 18's 4-6-leg structure has been reverted. Confirm before spending time on this.

### 11. SO/over pool softening — recheck with more volume (Priority: High, carried from Session 18/20)
The composite score's K/9-rank differentiation weakened post-slot-gate-fix. Three consecutive weak reads as of Session 20 (Session 18's ~1 week + 7/8 33.3% + 7/9 45.5%, all vs. ~61.6% baseline). Session 21's leg-level check on 7/17-19 didn't add a clean fourth read in either direction — strikeouts/over dipped to 51.5% the week of 7/6 but recovered to 68.4% the week of 7/13 — so this remains unresolved, not newly confirmed or newly cleared.

### 12. Cancel SGO Pro subscription (High Priority, carried from Session 17, still not done)
Code change validated. Account-level downgrade is a manual action outside the codebase.

### 13. Add hits/over coverage ceiling at ~80% (High Priority, carried from Session 15, reconfirmed)
Full-history data still shows the climb-then-cliff pattern (72.0% at 75-79.7%, 62.3% at 80-84.6%). Not yet implemented.

### 14. Fix void_reason logging gap (Medium Priority, carried from Session 16, still not done)
`void_reason` on `mlb_scored_legs` is still NULL for the large majority of voided legs.

### 15. Project file cleanup (Low priority, carried, still not done)
Retire `README_10.md` and other stale files from Project Knowledge.

---

## System Health Indicators

### Green Lights
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
⚠️ Pitcher ERA signal confirmed inverted but not yet fixed — rebuild scoped (recent-starts ERA), explicitly deferred by operator this session, still active and unchanged in production
⚠️ Session 21 fixes on branch, not yet merged/deployed as of this doc update — nothing involving new data can be checked until live
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

**Last Review:** July 20, 2026 (Session 21)
**System Status:** ✅ Operational — Session 21 closed out (parlay-builder leg-count EV regression found and reverted, lineup_consistency DB-persistence bug fixed, coverage_recent_10 sample floor added, pitcher ERA signal confirmed inverted and scoped for rebuild but not yet implemented). Fixes on branch `fix/leg-cap-lineup-consistency-streak-floor`, pending merge/deploy.
**Next Review:** Confirm Session 21 branch merged and deployed, first thing / watch leg-cap-revert live performance over 1-2 weeks / confirm lineup_consistency Step 5b filter via Railway logs / build and backtest the pitcher ERA rebuild / complete manual-pick end-to-end test (carried 4 sessions) / compare shadow vs. production win rate after ~3-4 weeks
**Pending Decisions:** Pitcher ERA rebuild scope and timeline (scoped Session 21, not started), whether the leg-cap revert alone restores full pre-redesign EV or a second factor is also at play (needs live data), SO/over softening — still unresolved, TB/under construction strategy re-run (may be moot now that the builder reverted — confirm first), SGO Pro cancellation (user action, still not confirmed), hits/over ceiling implementation (carried, no target date set)
