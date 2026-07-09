# MLB Parlay Agent — Session Handoff
**Last Updated:** July 8, 2026 (Session 18 — Performance Deep-Dive, Parlay Builder Redesign, Manual Parlay Dashboard)

## Current Status
✅ **OPERATIONAL — SESSION 18 DEPLOYED (pending final visual confirmation on one fix — see below)**
✅ **Parlay builder redesigned: fixed 4-leg / +400-+700 band replaced with 4-6 legs / +400 floor only**
✅ **New: Manual Parlay Dashboard at `/manual` — full-signal batter+pitcher table, human leg selection, logs to the same resolution pipeline as automated picks**
🔲 **Pending user action (carried from Session 17): cancel SGO Pro subscription ($149/mo) — code change validated, account downgrade itself not yet confirmed**
🔲 **Pending: confirm the final `/manual` sticky-header CSS fix was actually committed and pushed — see "Open Item" below**
🔲 **Pending: first true end-to-end test of the manual pick flow (submit → resolve) has still not been completed — see Pending Items #1**
⚠️ **Automated builder's real-world performance under the new floor-only/4-6-leg logic has zero days of live data yet — old backtest only confirmed no crash, not performance**

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

## Pending Items — Next Session

### 1. Complete the manual-pick end-to-end test (High Priority — never actually completed this session)
Submit one real parlay from `/manual`, confirm it lands in `mlb_parlay_recommendations_v2` with `source = 'manual_pick'` and correct leg data in `mlb_parlay_legs_v2`, then confirm it resolves correctly (not left `pending`) after the next 9am run. This was set up as the very reason for building the dashboard and got deferred repeatedly this session in favor of bug fixes. Do this first.

### 2. Confirm the sticky-header fix commit (High Priority)
`git log -1 --format="%H %s"` — get the real hash, confirm it's the flex-column structural fix, confirm it's live on Railway, update this doc's Session 18 Commits table.

### 3. Commit a real regression test file for the greedy parlay builder (High Priority)
The 7 synthetic test cases that validated the builder rewrite (4-6 leg range, floor enforcement, no ceiling, per-game/per-player constraints) were run from an ad hoc `/tmp` script during the build session and were never committed — they no longer exist. This is the single biggest behavioral change in the project's history and currently has zero persisted regression coverage. Turn those cases into `tests/test_parlay_builder.py`. Note: `pytest` isn't installed in the venv — `pip install pytest` will be needed too.

### 4. Backtest the new floor-only/4-6-leg builder against real performance (High Priority)
`scripts/run_backtest.py` was run this session but only proved the new builder doesn't crash when called — its existing variants (EV-sort, slot gate) test different things, not leg-count/odds-floor logic. The actual performance case for the redesign came from a one-off day-level analysis earlier in this session (top-5-by-score clears +400-700 naturally on 81% of days, comparable-or-better win rate). Once a week or so of live data exists under the new builder, do a proper pre/post comparison the way the slot-gate fix was rechecked.

### 5. Re-evaluate TB/under construction strategy under the new builder (Medium Priority — supersedes prior TB/under items)
The combinatorial-drag numbers (15.8% with TB/under leg vs 26.7% without, shadow) were generated under the *old* fixed-4-leg builder. With 4-6 legs now possible, the tradeoff math may have changed — a TB/under leg mixed into a 5-6 leg parlay isn't the same problem as one mixed into a fixed 4-leg parlay. Re-run this analysis before any promotion decision.

### 6. SO/over pool softening — recheck with a full week (Medium Priority, carried from this session)
The composite score's ability to differentiate strong from weak SO/over matchups nearly vanished post-slot-gate-fix (K/9 rank gap collapsed from 17.3-vs-43.9 to 15.7-vs-18.8). Only ~1 week of post-fix data exists. Recheck once more volume accumulates — could be a real pool-composition shift or noise.

### 7. Cancel SGO Pro subscription (High Priority, carried from Session 17, still not done)
Code change validated (~1,080-1,350 projected objects/month, well under the 2,500 free-tier cap). Account-level downgrade is a manual action outside the codebase and still hasn't been confirmed done.

### 8. Add hits/over coverage ceiling at ~80% (High Priority, carried from Session 15, reconfirmed this session)
Full-history data still shows the same climb-then-cliff pattern (72.0% at 75-79.7%, 62.3% at 80-84.6%). Not yet implemented.

### 9. Re-evaluate K/9 and WHIP signals with starter-only data (Medium Priority, carried from Session 15)
This session's bucket analysis added a new, small-sample data point suggesting the K/9-rank-to-win-rate relationship may be non-monotonic or reversed at the extremes — feeds into this already-pending item.

### 10. Fix void_reason logging gap (Medium Priority, carried from Session 16, still not done)
`void_reason` on `mlb_scored_legs` is still NULL for the large majority of voided legs.

### 11. Project file cleanup (Low priority, carried, still not done)
Retire `README_10.md` (superseded by this file + `BUILD_STATUS.md`) and other stale files from Project Knowledge.

---

## System Health Indicators

### Green Lights
✅ Parlay builder redesign validated against real data before deployment (this session) — old-vs-new comparison run on real July 7 pool, proved the exact substitution mechanism the redesign targets
✅ Manual dashboard's resolution-pipeline compatibility confirmed via code read, not assumption — `parlay_outcome_resolver.py` has no source filter
✅ Decimal serialization bug root-caused precisely (not guessed) via a live query against production data before the fix was written
✅ Field-name bugs (best_line/best_odds/opposing_pitcher_name) root-caused by reading the live file and cross-checking real DB field names before fixing, not guessing
✅ 85b5bd5 mystery commit (open since Session 16) resolved — confirmed docs-only, no code
✅ hits/under's alarming 14-day read (36.4% WR) correctly identified as noise once extended to 35 days (57.9% WR) — caught before it drove a bad decision
✅ Slot-gate fix's void-rate improvement confirmed exactly as designed (58.3%→20.3%)

### Yellow Flags
⚠️ Sticky-header fix push status unconfirmed — no commit hash captured, needs verification first thing next session
⚠️ New builder logic has zero live-data performance validation yet — only regression-tested (no crash), not performance-tested
⚠️ Manual pick end-to-end flow (submit → resolve) still never actually tested despite being the whole point of the dashboard
⚠️ Builder's 7-case regression test suite was never committed — currently zero persisted test coverage for the biggest architecture change in the project
⚠️ SO/over pool softening — real effect or noise, undetermined, ~1 week of data
⚠️ TB/under construction-strategy numbers now stale relative to the new builder — needs rerun before any promotion decision
🔲 SGO Pro subscription cancellation still not confirmed (carried multiple sessions)
⚠️ hits/over ~80% coverage ceiling still not implemented (carried, reconfirmed)
⚠️ K/9/WHIP signal re-evaluation still pending, new data point (possible reversal) adds urgency
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

**Last Review:** July 8, 2026
**System Status:** ✅ Operational — Builder Redesigned, Manual Dashboard Live (pending final visual-fix confirmation)
**Next Review:** Confirm sticky-header commit + complete manual-pick end-to-end test (both first-priority, both trivial to close out)
**Pending Decisions:** TB/under construction strategy under new builder (rerun analysis first), SO/over softening recheck (~1 more week), SGO Pro cancellation (user action, still not confirmed), hits/over ceiling implementation (carried, no target date set)
