# MLB Parlay Agent — Architecture Decisions
**Last Updated:** August 4, 2026 (Session 26 — fixed the parlay builder's zero-recovery-on-missed-floor bug via a bounded single-leg-swap search; live-verified writing 5 real parlays to the database)

---

## Table of Contents
1. [Core Philosophy](#core-philosophy)
2. [Scoring System Evolution](#scoring-system-evolution)
3. [Prop Selection — Data-Driven Whitelist](#prop-selection--data-driven-whitelist)
4. [Coverage Gating Architecture](#coverage-gating-architecture)
5. [Parlay Construction Evolution](#parlay-construction-evolution)
6. [Player Diversity — Cross-Run Cap](#player-diversity--cross-run-cap)
7. [Odds Cap Decision](#odds-cap-decision)
8. [Coverage Signal Architecture](#coverage-signal-architecture)
9. [Pitcher Signal Pipeline](#pitcher-signal-pipeline)
10. [Shadow Pipeline Strategy](#shadow-pipeline-strategy)
11. [Enriched Scoring Signals](#enriched-scoring-signals)
12. [Lineup Confirmation Layer](#lineup-confirmation-layer)
13. [CLV Tracking Layer](#clv-tracking-layer)
14. [Backtest Harness](#backtest-harness)
15. [Outcome Resolution](#outcome-resolution)
16. [Database Design](#database-design)
17. [Pipeline Architecture](#pipeline-architecture)
18. [Batting Order Slot Gate — Removal (Session 16)](#batting-order-slot-gate--removal-session-16)
19. [TB/under Parlay-Level Combinatorial Drag (Session 16)](#tbunder-parlay-level-combinatorial-drag-session-16)
20. [SportsGameOdds Cost Optimization — CLV Layer Removal (Session 17)](#sportsgameodds-cost-optimization--clv-layer-removal-session-17)
21. [Parlay Builder Redesign — Floor-Only Odds, Flexible Leg Count (Session 18)](#parlay-builder-redesign--floor-only-odds-flexible-leg-count-session-18)
22. [Manual Parlay Dashboard (Session 18)](#manual-parlay-dashboard-session-18)
23. [Scratch Handling Rewrite — Time-Gated Reduce-Path (Session 19)](#scratch-handling-rewrite--time-gated-reduce-path-session-19)
24. [Shadow Scoring Rebuild — Linear-Scale Matchup Signals (Session 19)](#shadow-scoring-rebuild--linear-scale-matchup-signals-session-19)
25. [game_start_time UTC/ET Contamination — Remediation (Session 20)](#game_start_time-utcet-contamination--remediation-session-20)
26. [Parlay Builder — Leg-Count Reverted to Fixed 4 (Session 21)](#parlay-builder--leg-count-reverted-to-fixed-4-session-21)
27. [lineup_consistency — DB Persistence Bug Fixed (Session 21)](#lineup_consistency--db-persistence-bug-fixed-session-21)
28. [coverage_recent_10 — Minimum Sample Floor Added (Session 21)](#coverage_recent_10--minimum-sample-floor-added-session-21)
29. [Pitcher ERA Signal — Contamination Confirmed, Rebuild Scoped (Session 21)](#pitcher-era-signal--contamination-confirmed-rebuild-scoped-session-21)
30. [Reference Data Schema — Backfill Architecture (Session 22)](#reference-data-schema--backfill-architecture-session-22)
31. [Diamond Line Dashboard Rework — Standings, Leaderboards, and the Generated-Frontend Constraint (Session 22)](#diamond-line-dashboard-rework--standings-leaderboards-and-the-generated-frontend-constraint-session-22)
32. [SGO Billing Verification Methodology (Session 23)](#sgo-billing-verification-methodology-session-23)
33. [Pipeline Schedule Cut — 3 Runs/Day to 2 (Session 23)](#pipeline-schedule-cut--3-runsday-to-2-session-23)
34. [Full Prop-Line Capture Architecture — mlb_prop_legs_history (Session 23)](#full-prop-line-capture-architecture--mlb_prop_legs_history-session-23)
35. [Point-in-Time Stat Backfill + Opposing-Pitcher Capture Fixed Forward (Session 24)](#point-in-time-stat-backfill--opposing-pitcher-capture-fixed-forward-session-24)
36. [Coverage Threshold vs. Matchup Quality — Analysis, Re-Run Pending (Session 24)](#coverage-threshold-vs-matchup-quality--analysis-re-run-pending-session-24)
37. [Silent Pipeline Stall — Unbounded statsapi.* Network Calls (Session 25)](#silent-pipeline-stall--unbounded-statsapi-network-calls-session-25)
38. [Parlay Builder — Floor-Recovery via Bounded Leg Swap (Session 26)](#parlay-builder--floor-recovery-via-bounded-leg-swap-session-26)
39. [Lessons Learned](#lessons-learned)
40. [Future Considerations](#future-considerations)

---

## Core Philosophy

### **Decision: Optimize for Validated Edge, Not Feature Complexity**

The system exists to find props where historical coverage rate predicts actual outcomes, and combine them into parlays with positive expected value. Every design decision should be evaluated against this goal.

*(Unchanged from prior version — see Session 15 entries for validated-edge figures per prop as of June 18. Session 18 re-validated the core props' pool-level edge is still real — see `SESSION_HANDOFF.md` Session 18 for current figures.)*

---

## Scoring System Evolution

### **Phase 0: ML Model (April–May 2026) — ABANDONED**
### **Phase 1: Simple Coverage-Based Scoring (May 20, 2026) — CURRENT PRODUCTION**

```python
score = coverage_overall          # always the base
     + coverage_vs_hand_delta     # ±3 max (30% weight of delta from overall)
     + consistency_adjustment     # gap-based ±6/±4/±2/+2/+1 — recency floor added Session 21, see §28
     + era_adjustment             # ±5 for hits props — CONFIRMED INVERTED Session 21, rebuild scoped not implemented, see §29
     + whip_rank_adjustment       # ±5 for hits props — REMOVED Session 15
     + k9_rank_adjustment         # ±5 for SO props (pitcher_k9_rank) — same data-source risk as ERA flagged Session 21, evidence inconclusive, monitoring only
     + lineup_stability           # -5 if lineup_consistency < 0.50 — was silently no-op'ing for the entire season, DB-persistence bug fixed Session 21, see §27
     + slot_gate_penalty          # -8 if unfavorable batting_order — REMOVED Session 16
```

**Session 21 status:** no formula weights or thresholds changed this session. Two bugs were fixed that affect whether existing adjustments actually apply (`lineup_consistency` persistence, `coverage_recent_10` sample floor); one adjustment (`era_adjustment`) was confirmed broken via controlled analysis but deliberately left in place pending a scoped rebuild (operator wants ERA retained as a signal, not removed — see §29). Composite score remains the sort key the (now-reverted-to-fixed-4-leg) builder walks.

---

## Prop Selection — Data-Driven Whitelist

*(Unchanged from Session 15 — see that section for current whitelist and breakeven figures.)*

**Session 18 note:** hits/under's pool-scarcity issue (only 1-3 players/day clear the 65% coverage floor most days) was newly characterized this session — see Lessons Learned #50. Not a whitelist change, a characterization of why that prop behaves noisily in small samples.

---

## Coverage Gating Architecture

*(Unchanged from Session 15.)*

---

## Parlay Construction Evolution

### **Phase 3.7: CLR Player Cap + TB Exclusion + Fallback Composition Fix (June 18, 2026)**
### **Phase 3.8: Batting Order Slot Gate Removed From Both Scoring and CLR Trigger (July 2, 2026)**
### **Phase 4: Floor-Only Odds, Flexible Leg Count (July 8, 2026) — CURRENT**

See [Parlay Builder Redesign](#parlay-builder-redesign--floor-only-odds-flexible-leg-count-session-18) below for full detail.

---

## Player Diversity — Cross-Run Cap

*(Unchanged from Session 15. Session 18 note: the new builder preserves both the max-2-legs-per-game and one-leg-per-player-per-parlay constraints unchanged — only the leg-count and target-odds logic changed.)*

---

## Odds Cap Decision

*(Unchanged — the -250/+150 per-leg pool eligibility range was not touched this session. Only the combined-parlay-odds target changed; see Session 18.)*

---

## Coverage Signal Architecture

*(Unchanged.)*

---

## Pitcher Signal Pipeline

*(Unchanged from Session 15 — see that section for the K/9-direction correction and hits/over vulnerability penalty detail. Session 18 added one new, small-sample data point: a 21-day K/9-rank bucket analysis showed a possible non-monotonic/reversed pattern at the extremes, feeding into the still-pending "re-evaluate K/9 and WHIP with starter-only data" item.)*

---

## Shadow Pipeline Strategy

### **Decision: Shadow Pipeline as Signal Validation Layer**

*(Unchanged framing from Session 15. Session 18 reconfirmed the offense stack bonus is live and firing with a positive early read — 64.4% WR when applied (n=101) vs 58.8% when not (n=2,153) — correcting a stale README status that still listed it as "not yet built.")*

---

## Enriched Scoring Signals

**Session 19 full rebuild — see [Shadow Scoring Rebuild](#shadow-scoring-rebuild--linear-scale-matchup-signals-session-19) below.** The rank-based K/9, WHIP, and pitcher-vulnerability scoring blocks in `_calculate_enriched_score` were replaced with a continuous linear-scale matchup adjustment. Coverage floors and the final 5–95 composite clamp are unchanged.

---

## Lineup Confirmation Layer

**Session 19 rewrite — see [Scratch Handling Rewrite](#scratch-handling-rewrite--time-gated-reduce-path-session-19) below for full detail.** The prior SCRATCHED-only rebuild logic was replaced with a time-gated reduce-path. The dead-link `superseded_by_batch_id` bug was fixed in the same pass.

---

## CLV Tracking Layer

**REMOVED — Session 17.** See prior version for full detail.

---

## Backtest Harness

*(Unchanged structurally from Session 15. Session 18 note: `scripts/run_backtest.py`'s existing variants — EV-sort, slot gate — test different questions than the Session 18 builder redesign. Running it against the new builder this session confirmed no crash/regression, but did not validate the new floor-only/4-6-leg logic's actual performance. A proper backtest of that specific change is still pending — see `SESSION_HANDOFF.md` Session 18 Pending Items.)*

---

## Outcome Resolution

*(Unchanged. Session 18 explicitly re-confirmed `parlay_outcome_resolver.py` has no `source` filter — it resolves any `outcome='pending'` row for the run_date regardless of source — which is what makes the manual parlay dashboard's auto-resolution work with zero resolver changes. See [Manual Parlay Dashboard](#manual-parlay-dashboard-session-18).)*

**void_reason is still not fixed** (Session 16 finding, carried through Sessions 17 and 18 without action).

---

## Database Design

*(Unchanged — see prior version for natural key rules, PostgreSQL conventions, schema change log, and clean-data cutoffs. Session 18 note: no schema migrations were applied this session. The manual parlay dashboard reuses the existing `source` free-text column on `mlb_parlay_recommendations_v2` with a new value, `'manual_pick'` — distinct from the pre-existing `'manual'` value, which is the "Regenerate Now" button (still runs the algorithm, just on demand) and predates this session; conflating the two would have made manual-vs-automated comparison meaningless.)*

---

## Pipeline Architecture

*(Unchanged structurally. See [Manual Parlay Dashboard](#manual-parlay-dashboard-session-18) for the new `/manual` route additions, which sit alongside the existing pipeline rather than modifying it.)*

- **On SCRATCHED only** — CONFIRMED_LINEUP_RESOLUTION rebuild (TB/under excluded, 1x player cap). *(Unchanged since Session 16.)*

---

## Batting Order Slot Gate — Removal (Session 16)

*(Unchanged — see prior version for full detail: the June 12/July 2 contradiction, the void-cost quantification, and the removal decision.)*

---

## TB/under Parlay-Level Combinatorial Drag (Session 16)

*(Unchanged from Session 16 for the original finding. **Session 18 update:** re-ran the same with/without-TB-leg comparison on fresh 14-day data — 15.8% win rate with a TB/under leg vs. 26.7% without (shadow) — same direction, smaller gap than Session 16's 13.8%/40.0%. Important caveat added this session: these numbers were all generated under the *old* fixed-4-leg builder. With the Session 18 redesign now allowing 4-6 legs, the combinatorial-drag math this finding is based on may not transfer directly — a TB/under leg diluting a fixed 4-leg parlay is a different problem than one diluting a 5-6 leg parlay. Re-run before any promotion decision — see Future Considerations #12 (updated).)*

---

## SportsGameOdds Cost Optimization — CLV Layer Removal (Session 17)

*(Unchanged — see prior version for full detail.)*

---

## Parlay Builder Redesign — Floor-Only Odds, Flexible Leg Count (Session 18)

### **Decision: Replace the Fixed 4-Leg, +400/+700-Banded Combinatorial Search With a 4-6 Leg, +400-Floor-Only Greedy Selector**

**Background — the "math problem" hypothesis, tested before acting on it.** The old builder (`src/engine/parlay_builder.py`) sorted the eligible pool by `composite_score` and ran a branch-and-bound search for exactly 4 legs whose combined odds fell inside +400–+700. The concern raised: forcing a specific payout band could regularly require substituting a lower-scored, higher-odds leg for a better-scored, lower-odds one purely to fit the band — sacrificing leg quality for payout shape.

**This was tested directly against real data before any code changed, not assumed:**
- Ranked eligible legs (coverage ≥65%, odds -250/+150) purely by `composite_score` for each of the last 21 days and computed what the top-4's combined odds would be, with zero odds-engineering.
- **Result: the top-4-by-score combination cleared the old +400 floor on only 3 of 21 days (14%).** The other 18 days, the single best 4-leg combination the pool contained would have priced below +400 — meaning the old builder was structurally guaranteed to reach past its own top picks on the large majority of days.
- Confirmed the specific mechanism with a live before/after run against the real July 7 pool: the old builder's top parlay used Rafaela/Walker/Gelof/Turner (composite scores 77.9/77/76.2/74.9, +405) — dropping Abreu (composite 75.9, higher than Turner) specifically because including both would have pushed the 4-leg combination past +700 or, with a different 4th leg, left it short of +400. There was no way to include both of the two best remaining legs at exactly 4 legs and land in the band.

**Leg-count fix tested the same way, not assumed:**
- Top-4 pure-quality picks cleared +400 on 3/21 days (14%).
- **Top-5 pure-quality picks cleared +400–+700 naturally on 17/21 days (81%)**, with no odds engineering at all.
- Top-6 pure-quality picks badly overshot the old +700 ceiling on nearly every day (800–1,500+) — 6 was too many, 4 was too few, 5 was close to a natural sweet spot.
- Sanity-checked against actual historical outcomes (not just odds math): a pure top-4/top-5 pick would have hit as a full parlay on 4/21 and 3/21 days respectively (19.0%/14.3%) — in the same range as actual production's 17.5% over the identical window. Removing the payout-band constraint did not cost win rate in this sample.

**Decision:** eliminate the +700 ceiling entirely. Keep a +400 floor. Replace the fixed 4-leg requirement with a 4-6 leg range. Leave the max-2-legs-per-game and one-leg-per-player-per-parlay constraints unchanged.

**Implementation.** `src/engine/parlay_builder.py`'s branch-and-bound search (recursive, with `MAX_CANDIDATES`/`TIMEOUT_SECS` bookkeeping, upper/lower bound pruning via suffix-sorted decimal odds, and post-hoc deduplication across candidates — roughly 180 lines) was replaced with a much simpler greedy selector: sort the eligible pool by `composite_score` descending, walk it applying the existing per-game/per-player constraints, and stop as soon as both (a) at least `MIN_LEGS` (4) legs are selected and (b) the running combined odds clears `MIN_PARLAY_ODDS` (+400) — only continuing past 4 legs when the floor isn't cleared yet, capped at `MAX_LEGS` (6). If the best 6 available legs still don't clear +400, that parlay slot produces nothing, matching the old "insufficient pool" behavior. `TOTAL_LEGS` is retained as a backward-compatible alias for `MIN_LEGS`, since `src/apis/lineup_confirmation.py` imports it for a "do we have enough legs to attempt a CLR rebuild" check. Both the shadow pipeline (`run_enriched_pipeline.py`) and CLR rebuilds (`lineup_confirmation.py`) call this same `build_parlays()` function, so the fix applies to all three call sites with no separate changes needed anywhere else.

**Validated against real data before deployment:** re-ran old vs. new builder logic against the identical real July 7 pool (62 eligible legs). New Parlay 1 includes both Abreu and Turner (5 legs, +661) rather than choosing between them — the exact substitution the redesign targeted no longer happens.

**Known gap:** a standalone 7-case regression test (4-6 leg range, floor enforcement, no ceiling, per-game/per-player constraint preservation) validated the rewrite during the build session but was run from an ad hoc `/tmp` script and never committed — it no longer exists. This is the single largest behavioral change in the project's history and currently has zero persisted regression coverage. Flagged as a high-priority Session 19 item.

**Also known gap:** `scripts/run_backtest.py` was run against the new builder post-deployment and confirmed it doesn't crash, but its existing variants (EV-sort, slot gate) don't test leg-count/odds-floor logic specifically. The actual performance case for this redesign rests on the pre-deployment day-level analysis above, not a proper backtest. A live-data performance recheck (the same style as the Session 16 slot-gate recheck) is pending once roughly a week of data exists under the new logic.

---

## Manual Parlay Dashboard (Session 18)

### **Decision: Build a Human-in-the-Loop Parlay Tool on the Same Data, Not a Replacement for Automation**

**Background.** Alongside the builder redesign, the operator raised a broader concern: low confidence that the automated agent alone could reliably select the best legs, and interest in a manual, data-backed selection tool as either a permanent approach or an interim one while the automated system's track record is rebuilt. The recommendation made and adopted: don't choose between automation and manual selection — build both. The builder redesign fixes a scoped, evidenced architectural flaw; the manual dashboard gives immediate visibility and control on the same underlying data, and creates a real comparison point (manual vs. automated win rate over time) that didn't exist before.

**Design principle:** the dashboard is a second, independent view onto data the automated pipeline already produces — it does not introduce a separate query path, a separate scoring path, or any new schema. Everything shown is exactly what `mlb_scored_legs` (and, where available, `mlb_scored_legs_enriched`) already contains.

**Data layer.** `get_manual_legs(run_date)` in `src/utils/db.py` reuses the same dedup logic as the existing `get_scored_legs()` and LEFT JOINs `mlb_scored_legs_enriched` by `odd_id` for `pitcher_vulnerability`, `park_factor`, and `blended_era_rank` — nullable, since the shadow pipeline may not have scored a given leg yet. No new table, no migration.

**Routes.** `src/web/server.py` adds `GET /manual` (the page), `GET /api/manual/legs` (data, auth required), and `POST /api/manual/parlay` (submit, auth required). The submit handler re-fetches all leg data server-side from `mlb_scored_legs` by `odd_id` rather than trusting anything the client sends except *which* `odd_id`s were picked — odds, scores, and coverage used in the saved parlay can't be spoofed from the browser. Validates 4-6 legs, no duplicate batter, max 2 legs per `game_pk` — the same structural constraints as the automated builder.

**Persistence and resolution.** Saves via the existing `save_parlay_recommendations_v2()` helper with a new, distinct `source='manual_pick'` value — separate from the pre-existing `'manual'` source, which is the "Regenerate Now" button (still runs the algorithm, just on demand) and predates this session; conflating the two would have made manual-vs-automated comparison meaningless. Before building this, confirmed by reading `parlay_outcome_resolver.py` directly that resolution has **no `source` filter at all** — it resolves any row with `outcome='pending'` for the given `run_date`. This means manual picks resolve automatically in the existing 9am run with zero resolver changes required — verified by reading the code, not assumed.

**+400 floor applied to manual picks: deliberately non-blocking.** The first implementation hard-rejected manual submissions below +400 combined odds. On review, this was reversed — hard-blocking a human's confident 4-leg pick that happens to price at, say, +320 would reintroduce, for human judgment, the exact problem the builder redesign exists to fix for the algorithm: forcing a payout target to override a genuine quality judgment. The leg-count range (4-6) stays a hard requirement, since that's structural and keeps manual and automated parlays comparable; the odds floor became a non-blocking `meets_floor` boolean surfaced in the UI instead.

**Iteration history — each fix driven by actual review or live testing, not speculation:**
1. **Auth hardening, done proactively during first build:** the auth probe was tightened to grant access only on an exact HTTP 200, rather than "anything but 401" — the looser version would have let a request through on, e.g., a transient 500.
2. **Decimal/JSON serialization bug**, surfaced as a false "wrong password" report. Root-caused by directly querying the live database with the exact SQL `get_manual_legs()` uses (confirming the query itself was fine) before concluding the bug was client-side — `pitcher_era`/`pitcher_k9`/`pitcher_whip`/`pitcher_vulnerability`/`blended_era_rank` are Postgres `NUMERIC` columns, returned by psycopg2 as Python `Decimal`, which `json.dumps()` cannot serialize by default. The resulting 500 was — correctly, per the auth hardening above — being displayed as "Authentication failed," masking the real bug. Fixed with `json.dumps(legs, default=str)`, matching the convention already used elsewhere in the file, plus differentiated error messaging so a future non-auth failure won't look like a login problem again.
3. **Field-name mismatches**, found by reading the live file and cross-checking real DB field names rather than guessing at the fix: the UI referenced `best_line`/`best_odds`/`opposing_pitcher_name`, but `get_manual_legs()` returns raw `mlb_scored_legs` columns named `line`/`odds`/`pitcher_name` (the `best_*`/`opposing_pitcher_name` naming exists elsewhere in the codebase, on in-memory pipeline dicts before persistence and on `mlb_parlay_legs_v2`, but not on the source table this dashboard reads from). Six call sites had the bug, not just the visible table.
4. **Sticky table header — two attempts.** First attempt used a JS function measuring `header.offsetHeight` at render time and setting the header's `top` accordingly; this made the visual bug *worse* (a partially-clipped row became visible under the header, indicating overlap, not just misalignment), which correctly triggered abandoning the tuning approach rather than trying a third pixel value. The JS-measured-offset method itself was diagnosed as inherently fragile (timing- and content-dependent). Second attempt restructured the page layout entirely: `body` became a `height: 100vh` flex column, `header` took its natural height, and `.table-wrap` became its own bounded, independently-scrolling container (`flex: 1; overflow-y: auto`) — making `thead { position: sticky; top: 0 }` correct by construction, with no measurement or JS involved. Neither Claude Code nor Claude (chat) had a way to render or screenshot this fix in-session to confirm visually; given the low risk of a pure CSS/layout change, the operator was asked to push and verify against the live page directly rather than block on a third guess.

**Open item carried to Session 19:** the final structural sticky-header commit's hash and push status were not explicitly confirmed in-session — the operator's "Looks better" strongly implies it was pushed and checked live, but this needs a `git log` confirmation first thing next session.

---

## Scratch Handling Rewrite — Time-Gated Reduce-Path (Session 19)

### **Decision: Replace Unconditional Void-and-Rebuild With a Time-Gated Reduce Path**

**Background.** The old scratch handler (`src/apis/lineup_confirmation.py`) voided the whole parlay and attempted a full rebuild from a fresh player pool on any SCRATCHED leg. This created two problems: (1) rebuilding a parlay when some surviving legs' games were already minutes from first pitch was functionally pointless — the replacement legs would be from the same nearly-locked lineup environment, and there was often no viable pool anyway; (2) even when the pool was too thin to rebuild, `superseded_by_batch_id` was set to the attempted batch's ID, creating a dangling reference (confirmed via live query: 7+ historical batch_ids referenced in `superseded_by_batch_id` don't exist in `mlb_parlay_recommendations_v2`).

**New logic:**
1. Check game start times for all *surviving* (non-scratched) legs.
2. If **all** surviving games are >1 hour out: rebuild (old behavior — unchanged).
3. If **any** surviving game is ≤1 hour out or already started: reduce-path — drop only the scratched leg(s), keep the parlay alive if ≥3 legs remain, void if <3 remain.
4. Voided/dropped individual legs remain as rows in `mlb_parlay_legs_v2` with `outcome='void'` — not deleted — so `num_legs`/`total_odds` can be recalculated off survivors and the resolver correctly skips the void leg when grading.
5. If a second scratch hits an already-reduced parlay: the same rule is applied again against whatever legs currently remain — no special-cased "second scratch" logic.
6. Applied going forward only — no backfill of historical void parlays.

**Dead-link fix:** `superseded_by_batch_id` is now only set when a replacement parlay was actually inserted. On no-rebuild paths (time-gate or thin pool), it stays NULL and `superseded_reason` is set to `'SCRATCHED_NO_REBUILD'` or `'THIN_POOL_NO_REBUILD'` instead. `result_note` on `mlb_pending_lineup_checks` only counts parlays actually rebuilt or reduced-and-kept, not voided-with-nothing-to-show-for-it.

**Tests:** `tests/test_lineup_confirmation.py` — 9 tests covering all branches.

---

## Shadow Scoring Rebuild — Linear-Scale Matchup Signals (Session 19)

### **Decision: Replace Rank Buckets With a Continuous Linear Scale for Pitcher/Batter Signals**

**Background.** The shadow scorer (`src/engine/enriched_scorer.py`) previously used `pitcher_era_rank`, `pitcher_k9_rank`, and `pitcher_whip_rank` — ordinal rank fields (1=best, N=worst among starters that day) — to compute matchup adjustments. These ranks have two structural problems: (a) a pitcher ranked 3rd of 10 starters gets the same signal as a pitcher ranked 3rd of 30, even though those represent very different absolute quality levels; (b) the rank-based buckets produce stepwise adjustments rather than a smooth signal proportional to how extreme the matchup actually is.

Session 18's K/9-rank bucket analysis showed a possibly non-monotonic/reversed pattern (the worst-matchup bucket had the highest win rate) — one more data point suggesting the rank-based signal was unreliable.

**New formula shape:**
```
adjustment = ((value − midpoint) / half_range) × max_weight
             clamped to [−max_weight, +max_weight]
```
For hits/over and hits/under: ERA and WHIP raw contributions are both computed, then proportionally scaled together (not hard-clipped individually) when their sum exceeds the ±7 combined cap — to avoid arbitrarily penalizing one factor relative to the other.

**Ranges (derived from actual `mlb_scored_legs` data, p5/p95, 11,080 legs May–Jul 2026):**
- ERA: midpoint 4.25, half-range 2.75 (1.50–7.00)
- WHIP: midpoint 1.20, half-range 0.50 (0.70–1.70)
- K/9: midpoint 8.25, half-range 2.75 (5.50–11.00) — user-confirmed 2026-07-10; originally proposed range 5.5–11.5 was flagged and confirmed before use per session prompt requirement
- Batter OBP/BA/K%/BB%: league-average estimates — validate after first shadow runs

**Per-prop weight and cap table:**
| Prop | Factors | Cap |
|---|---|---|
| hits/over | ERA ±5, WHIP ±3 (weak pitcher → positive) | ±7 |
| hits/under | ERA ±5, WHIP ±3 (elite pitcher → positive) | ±7 |
| strikeouts/over | K/9 ±5 (high K/9 → positive) | ±5 |
| totalBases/under | ERA ±4, WHIP ±2, K/9 ±1, OBP ±2, K% ±1.5, BB% ±1, BA ±0.5 (elite pitcher / high K%, low OBP/BA/BB% → positive) | ±12 |

**Batter stats:** accumulated from `get_batter_game_log()` season splits. Field names confirmed live: `atBats`, `hits`, `baseOnBalls`, `strikeOuts`, `plateAppearances`, `hitByPitch`. Minimum 50 PA required. Only called for `totalBases/under` legs — not on other prop types — to avoid unnecessary API calls.

**Scope:** shadow pipeline only (`enriched_scorer.py`, `run_enriched_pipeline.py`). Production scoring (`simple_scorer.py`) untouched. Coverage floors unchanged — still the sole gating/qualification criteria.

**Evaluation plan:** no backtest (historical window too thin and was actively misleading in analysis this session). Instead: run shadow for a few weeks, then compare shadow vs. production win rate and edge (win rate vs. odds-implied probability) using the existing comparison queries in `SUPABASE_SCHEMA_REFERENCE.md`. Batter ranges to be validated and updated from real data after the first shadow runs.

**Tests:** `tests/test_enriched_scorer.py` — 37 tests covering all four prop types, cap enforcement, direction signs, and the final 5–95 clamp.

---

## game_start_time UTC/ET Contamination — Remediation (Session 20)

### **Decision: Re-fetch Authoritative UTC from MLB StatsAPI Rather Than Trying to Guess Which Stored Value Is Correct**

**Background.** `scripts/backfill_game_start_time.py` (now retired) stored `game_start_time` in Eastern Time (naive string, no tzinfo) using `.astimezone(ET_TZ)` + `.strftime(...)`, while `src/pipelines/enrich_legs.py` stores raw UTC ISO strings using `utc_time.isoformat()`. Both formats look identical in the database (e.g. `2026-05-15 19:10:00` vs `2026-05-15 23:10:00`) — there is no column-level flag, no offset suffix, no way to distinguish them by value inspection alone. 15 `game_pk`s had two conflicting `game_start_time` values across their legs as a result.

**Why "pick the later one" or "pick the one matching the API" was rejected as a heuristic:** some of the 5 non-4-hour-offset game_pks had values where one happened to match the StatsAPI UTC — but only coincidentally (rescheduled game with new time). Going back to the source (StatsAPI) for every affected `game_pk` is the only approach that doesn't require reasoning about which convention a specific value was written with.

**Implementation:** `scripts/fix_game_start_time_contamination.py` — one-time cleanup script. Loops over all affected `game_pk`s, calls `statsapi.get('game', {'gamePk': game_pk})`, extracts `gameData.datetime.dateTime`, and overwrites every leg for that `game_pk` in both `mlb_scored_legs` and `mlb_scored_legs_enriched`. Supports `--dry-run`. Now retired as a reference artifact — the contamination source (backfill script) is gone and the tables are clean.

**Regression prevention:** a periodic health-check query is documented in `SUPABASE_SCHEMA_REFERENCE.md` under "Data Health Checks." Zero rows is the expected healthy result; any rows indicate a re-introduction of the bug pattern (a new write-path storing ET values into a UTC column).

**Write-path convention going forward:** `game_start_time` is UTC ISO — use `utc_time.isoformat()` as `enrich_legs.py` does. Never convert to local time before storing.

---

## Parlay Builder — Leg-Count Reverted to Fixed 4 (Session 21)

### **Decision: Revert MAX_LEGS from 6 back to 4, Restoring the Pre-Session-18 Fixed-4-Leg Structure**

**Background.** A post-All-Star-break performance review (requested by the operator, who suspected the Session 19/20 changes) traced the actual cause of a multi-week production win-rate decline to the Session 18 builder redesign (§21) instead — confirmed via git history that no code shipped between 7/10 and 7/20 except a docs-only commit, ruling out the operator's original hypothesis.

**Evidence.** Weekly production parlay win rate declined from 26.3% (week of 6/8) to 6.1% (week of 7/13) — a decline that started before the Session 18 redesign's effects would show and continued after. The fingerprint: avg legs/parlay jumped from a fixed 4.00 (100% 4-leg, June) to 4.4-4.5 (only ~45% 4-leg) exactly coincident with the 7/8 deploy. Leg-level win rates stayed healthy throughout (58-68% weekly) — this was a parlay-construction problem, not a scoring problem. Actual EV per $1 staked: pre-redesign 4-leg +$0.128 (n=486) vs. post-redesign 4-leg −$0.662 (n=28) and 5-leg −$0.416 (n=58). The higher payout on longer parlays does not compensate for the mechanically lower AND-probability win rate.

**A simulation (top-4-by-`composite_score` within each actual post-redesign parlay) suggested a hard revert wouldn't fully restore the pre-redesign +$0.128 EV** — two overlapping test windows came back at −$0.25 and −$0.34 EV/$1 respectively, disagreeing with each other by roughly 10 points of win rate, which is itself evidence the sample is too thin to resolve further by backtesting alone. Rather than keep backtesting an already-thin signal, the decision was to revert based on the strong, large-sample pre-redesign baseline and **treat "does this fully restore profitability" as a live-tracking question**, not a pre-deployment backtest question — see Pending Item in `SESSION_HANDOFF.md`.

**Implementation:** `src/engine/parlay_builder.py` — `MAX_LEGS` constant changed from 6 to 4, so `MIN_LEGS == MAX_LEGS == 4`. No other constants changed (`MIN_PARLAY_ODDS` stays 400, no ceiling). The greedy-selection loop in `build_parlays()` was verified by direct code read (not just test-suite trust) to handle the `MIN_LEGS == MAX_LEGS` collapse correctly: the early-exit condition (`len(legs) >= MIN_LEGS and combined_dec >= floor`) and the hard cap (`len(legs) >= MAX_LEGS`) now converge at the same point in the loop, with no off-by-one or infinite-loop risk. This preserves the "floor-only, no ceiling" philosophy from §21 — a parlay still fails outright (rather than force-substituting) if 4 legs don't clear +400 — it just no longer extends past 4 to try to clear the floor.

**What this does *not* revert:** the underlying rationale for removing the +700 ceiling in §21 (forced substitution of a higher-scored leg for a lower-scored, longer-odds one purely to fit a band) is still considered valid — that problem isn't being reintroduced. Only the *flexible leg count* half of the Session 18 redesign is reverted; the floor-only odds philosophy stays.

**Tests:** `tests/test_bug_fixes.py::TestParlay4LegCap` — confirms 4-leg parlays build correctly, no 5+ leg parlay is ever produced, and <4 legs available produces no parlay. Existing test suite (76 total) passes with no regressions.

---

## lineup_consistency — DB Persistence Bug Fixed (Session 21)

### **Decision: Fix the INSERT, Don't Touch the Filter or Scoring Logic**

**Background.** `lineup_consistency` was found to be NULL for 100% of all ~18,356 scored legs since the project's inception (April 17 through this session). Two mechanisms exist involving this field: (1) a pre-scoring filter in `main.py` (Step 5b) that removes any batter leg with `lineup_consistency < 0.70` from the pool before it reaches the scorer, unless an injury-expanded-role exception applies; (2) a scoring-time `-5` penalty in `simple_scorer.py` for `lineup_consistency < 0.50`, which — because of the upstream 0.70 filter — can only ever fire for the rare injury-exception-kept legs, making it near-dead-code by construction even when working correctly.

**Root cause.** `main.py` correctly computes `lineup_consistency` in memory and sets it on the leg dict in both places Step 5b runs. But `src/utils/db.py`'s `log_scored_legs()` — the function that INSERTs each run's scored legs into `mlb_scored_legs` — never included `lineup_consistency` in its column list or values tuple, despite the column existing in the schema. The computed value was silently discarded between "computed in memory" and "written to disk." This is a straightforward miss, not a logic bug: the person who built the Step 5b filter likely assumed the generic insert function would pick up the new field automatically; it's a hand-maintained explicit column list and wasn't updated.

**Fix.** Added `lineup_consistency` to the column list, the values tuple (`leg.get("lineup_consistency")`), and the `ON CONFLICT` `COALESCE` clause in `db.py`. Confirmed only one `INSERT INTO mlb_scored_legs` exists in the file — no second insert path was missed.

**Important limitation — persistence ≠ confirmed-working filter.** Fixing the write path means the value will start populating going forward, but it does **not** confirm that the upstream Step 5b filter has actually been successfully calling the MLB Stats API and removing low-consistency legs all along. The whole Step 5b block is wrapped in a broad `try/except` that would silently swallow an import or runtime error and skip the filter entirely — this failure mode is architecturally identical to the one already documented and reconstructed for Issue B in Session 20 (§25's related write-up in `SESSION_HANDOFF.md`). A Railway log check for the `[5b]`/`[lineup_consistency]` print output on a live run is needed to close this out — see Pending Items in `SESSION_HANDOFF.md`.

**Tests:** `tests/test_bug_fixes.py::TestLineupConsistencyDbInsert` — source-inspection tests confirming the column list, values tuple, and `COALESCE` conflict clause all reference `lineup_consistency`.

---

## coverage_recent_10 — Minimum Sample Floor Added (Session 21)

### **Decision: Add MIN_RECENT_GAMES = 5, Matching the Existing Floor Pattern on coverage_overall**

**Background.** The consistency/streak adjustment in `simple_scorer.py` (±6/±4/±2/+1/+2 based on the gap between `coverage_overall` and `coverage_recent_10`) showed a weak, non-monotonic relationship with actual win rate in controlled testing this session — the "severe cold" bucket (−6 penalty) actually outperformed the "moderate cold" bucket (−4 penalty): 61.5% vs 57.1%.

**Root cause.** `src/engine/coverage.py`'s `_hitter_coverage()` already enforces `get_season_minimum(overall_games)` before trusting `coverage_overall` — but the equivalent `coverage_recent_10` calculation had no floor at all: any player with `recent_games > 0` (even a single logged game) produced a trusted value, which then fed directly into the tiered adjustment. Players early in a stint (recent call-ups, returning from IL, recently expanded role) are exactly the cases most likely to show a large season-vs-recent gap — and exactly the cases where "recent 10" might really mean "recent 1-3," making the gap mostly sampling noise rather than a real hot/cold signal.

**Fix.** Added `MIN_RECENT_GAMES = 5` as a module-level constant in `coverage.py`. `coverage_recent_10` now returns `None` (skipping the adjustment entirely, same as the existing None-handling in the scorer) when `recent_games < 5`, in both `_hitter_coverage()` and `_pitcher_coverage()` — the agent implementing this fix found and corrected the pitcher-path duplicate on its own, which wasn't explicitly called out in the fix scope but is the same underlying issue.

**Scope note:** `coverage.py` is shared code — both `simple_scorer.py` (production) and `enriched_scorer.py` (shadow) consume `coverage_recent_10` from the same function, so this fix benefits both pipelines without a separate change needed on either scorer.

**Tests:** `tests/test_bug_fixes.py::TestCoverageRecent10Floor` — confirms `None` returned when `recent_games < 5` and a real value when `recent_games >= 5`, on both the hitter and pitcher code paths.

---

## Pitcher ERA Signal — Contamination Confirmed, Rebuild Scoped (Session 21)

### **Decision: Confirm the Problem, Scope a Fix, Explicitly Do Not Ship a Fix This Session**

**Background.** Controlled analysis (bucketing by base coverage band, to rule out the selection-bias risk of comparing across a `composite_score >= 65` floor) confirmed the pitcher-ERA hits/over adjustment is currently backwards: the "weak pitcher" bucket (ERA > 5.0, gets a +5 boost) underperformed "neutral" (no adjustment) in every coverage band tested, and underperformed "ace pitcher" (ERA < 3.0, −5 penalty) in 3 of 4 bands. E.g. at ~72 base coverage: ace 63.8% (n=80), neutral 59.8% (n=246), weak-pitcher 54.2% (n=59).

**Root cause.** `pitcher_era` is sourced from `_fetch_pitcher_season_stats()` in `src/apis/matchup.py` — cumulative full-season ERA via `stats=season`, gated only by a 5.0 IP minimum (roughly one start). This is the **same function and the same raw stat split** that `pitcher_whip` was pulled from before WHIP was removed on June 25 for the documented reason of reliever/small-sample contamination in the full-season pool. ERA never received the same scrutiny at the time — it shares the identical structural risk (no role separation, no recency weighting, thin sample floor) and the controlled test this session shows it manifesting the same way.

**Why this wasn't removed outright, unlike WHIP.** Operator pushback, and reasonably so — pitcher quality plausibly does bear on hits-prop outcomes; the problem is the specific stat feeding the adjustment, not the concept. Decision: scope a rebuild rather than delete the signal.

**Rebuild plan (not started this session):**
1. Raise the IP floor from 5.0 to roughly 3 starts (~15-18 IP) — cheap, immediate, low-risk first step, same principle as the `MIN_RECENT_GAMES` fix applied to the streak signal.
2. Build `get_pitcher_game_log()` — same MLB-StatsAPI `gameLog` pattern already used by the existing batter-side `get_batter_game_log()`, applied to pitchers.
3. Compute ERA over the pitcher's last 5 starts instead of the full season, mirroring how `coverage_recent_10` already handles recency for batters.
4. **Backtest the replacement with the same controlled-band method used to find this problem** (bucket by base coverage, compare win rate across ERA tiers) before wiring it into `simple_scorer.py`. The original signal — and WHIP before it — never received this treatment before shipping, which is a meaningful part of why the problem went unnoticed this long.

**K9-rank note.** `pitcher_k9_rank` shares the same source function and theoretical risk, but the same controlled-band test came back mixed rather than consistently inverted (one band showed the expected direction, another reversed it) — plausibly because K/9 is a more stable, less luck/defense-dependent stat than ERA. No action taken; monitor with more data before deciding whether it needs the same treatment.

**Shared-code note:** `enriched_scorer.py` (shadow) computes its own ERA-based signal (`opp_pitcher_era_rank`) but pulls from the same `_fetch_pitcher_season_stats()` source — so this is not a "production has a bug, shadow already fixed it" situation. Both pipelines share the root cause. The rebuild, when scheduled, should live in the shared matchup-profile code so both benefit from one fix rather than two.

**Status: confirmed broken, rebuild scoped, explicitly deferred.** See Pending Items in `SESSION_HANDOFF.md`.

---

## Reference Data Schema — Backfill Architecture (Session 22)

### **Decision: Reuse Existing Tested API Helpers, Fix Bugs Found by Testing Against Live Responses Rather Than Trusting Docstrings, Rely on MLB's Own Qualified-Players Filter Instead of Reimplementing It**

**Background.** A new, normalized reference schema (`mlb_teams`, `mlb_players`, `mlb_games`, `mlb_player_batting_logs`, `mlb_player_pitching_logs`, `mlb_team_standings`+`_splits`, `mlb_player_season_batting_stats`+`_pitching_stats`, `mlb_prop_legs_history`) was applied directly to the live Supabase database before this session started — no migration file exists in the repo for it, same out-of-band pattern the original reference schema itself was applied under. Purpose: give the Diamond Line dashboard (and any future analysis) fast local access to MLB.com-equivalent stats/standings/game-logs without a live API call per request, and to capture opposing-pitcher data for every batter in a game (not just qualified starters) via game-level box scores rather than per-player calls.

**Decision 1 — reuse, don't reimplement, the API layer.** A draft backfill script (handed off unrun, with a documented caveat that it had never touched the network) already called `src/apis/mlb_stats.py`'s existing `get_schedule()`/`get_box_score()` rather than making new raw API calls. Kept this design — but treated the draft's field-name assumptions as unverified until checked against live responses, not as correct because they were plausible-looking.

**Decision 2 — verify against live data before running anything at scale.** Rather than trust `statsapi.boxscore_data()`'s docstring or the draft's comments, made live calls to inspect the actual response structure directly. This surfaced three real bugs the draft had (see §29's sibling section in `SESSION_HANDOFF.md`'s Session 22 entry for full detail — condensed here): `statsapi.boxscore_data()` has its own hardcoded `fields` API-parameter whitelist that silently strips fields that look like they should be present (`plateAppearances`, `hitByPitch`, `gamesStarted`) — the draft's batting-log insert gate and its `is_starter` check both depended on fields that are *never* returned via this specific call path, meaning neither would have worked at all if run as originally written. This is the general lesson: a "this looks right" field-name read of API-wrapper code is not the same claim as "confirmed present in the actual response," and the two should not be conflated before a multi-hundred-day, multi-thousand-row backfill runs unattended.

**Decision 3 — don't reimplement a qualification threshold the source API already computes.** The handoff spec asked for the "Qualified Players" PA≥3.1×team-games / IP≥1.0×team-games threshold to be recomputed daily against that day's actual team-games-played. Investigated live first: `stats=season&group=hitting|pitching` on `statsapi.mlb.com` defaults to `playerPool=QUALIFIED` server-side, and the returned pool's minimum PA lined up with the expected threshold on a spot-checked date. This is the literal same computation MLB.com's own leaderboards (the source of the screenshots this whole task was scoped from) use. Decision: call the API with its own default filter rather than duplicate MLB's qualification math client-side — less code, and no risk of drifting out of sync with MLB's own rules (doubleheaders, suspended games, etc.) that a reimplementation would need to track.

**Decision 4 — a two-pass insert per game, not one, to satisfy foreign keys correctly regardless of processing order.** `mlb_player_batting_logs.opposing_pitcher_id` is a real FK to `mlb_players`. A single-pass, side-by-side insert (process home roster fully, then away) would fail or silently skip whenever a home-side batter's `opposing_pitcher_id` pointed at an away-side pitcher not yet upserted. Fixed by upserting both full rosters into `mlb_players` before inserting any log row for either side, per game.

**Decision 5 — a discovered sign-loss bug (`wildCardGamesBack`) got a numeric-sign fix, not a new column.** MLB's raw API returns a literal `'+7.0'` string for a team currently holding a wildcard spot (vs. a plain `'7.0'` for a team chasing one) — a real, load-bearing distinction that a naive `float()` cast collapses. Rather than add a second boolean column to track "holds a spot," stored the "+"-case as a negative number (the column is otherwise never negative) and reconstructed the display `+` from the sign in the dashboard's shaping layer. Kept the schema smaller at the cost of a documented, non-obvious convention — flagged clearly in both the backfill script and the dashboard code that reads it.

**Status: backfilled season-to-date (2026-03-25–2026-07-29), validated via 3 independent live spot-checks and a `game_pk` cross-check against `mlb_scored_legs`. Daily refresh written, wired into `server.py`'s scheduler, not yet deployed.** See `SESSION_HANDOFF.md`'s Session 22 entry for full validation detail and `scripts/backfill_reference_data.py` / `scripts/backfill_reference_snapshots.py` / `scripts/daily_reference_refresh.py` module docstrings for field-level notes.

**Correction (Session 24):** the "not yet deployed" status above referred to `daily_reference_refresh.py`'s own scheduler wiring, which is still accurate — but a *separate* claim carried in this doc's own footer and in `BUILD_STATUS.md` ("Session 21 fixes on branch, pending merge/deploy") was checked directly against git history this session and found stale: `git merge-base --is-ancestor origin/fix/leg-cap-lineup-consistency-streak-floor master` returns true — the Session 21 branch (`62a3c39` and its docs commits) is an ancestor of `master`'s current HEAD (`65ce276`), i.e. **already merged and deployed**, along with additional `dashboard_api` "Phase 1" work on top of it. The "pending merge" language throughout this doc and `BUILD_STATUS.md` predates that merge and was never updated afterward — corrected in both docs this session. Lesson: a status carried across several session-handoff updates without being re-verified against the actual repo state can go stale silently — worth a quick `git merge-base --is-ancestor` check before repeating an inherited "pending" claim.

---

## Diamond Line Dashboard Rework — Standings, Leaderboards, and the Generated-Frontend Constraint (Session 22)

### **Decision: New Dashboard Views Ship as Separate Static Pages, Not Extensions of the Existing Frontend Bundle**

**Background.** Handoff asked for the Diamond Line dashboard (`dashboard_api/`, previously scoped as a props-focused Matchup/Batters/Pitchers tool — see the undocumented Phase 1 commits noted in `SESSION_HANDOFF.md`'s Session 22 entry) to grow MLB.com-style Hitting/Pitching/Standings leaderboard tables plus player/team drill-down cards, sourced from the new reference schema above. A scoping plan was presented and explicitly approved before any dashboard code was written, per the handoff's own instruction not to treat this as a given.

**Finding that reshaped the plan.** `dashboard_api/static/support.js` (68K, the existing frontend's interactive runtime) opens with `// GENERATED from dc-runtime/src/*.ts — do not edit. Rebuild with 'cd dc-runtime && bun run build'.` A repo-wide search confirmed `dc-runtime/` does not exist anywhere in the repository — only the compiled output was ever committed. `index.html` is a custom `<x-dc>`/`{{ }}`-templated document (React-based, `sc-if` conditionals) that this generated runtime parses client-side; there is no accessible source to edit and rebuild from.

**Decision: treat "extend the existing bundle" as unavailable, not merely inadvisable.** Hand-editing a minified, generated JS bundle with no source to regenerate from is not a sustainable path for adding new stateful views — any edit would be permanent technical debt with no way to cleanly re-derive it later. Built all three new views this session (Standings, Hitting leaderboard, Pitching leaderboard) as separate, self-contained static files (plain HTML/CSS/vanilla JS) instead, reusing `styles.css`'s existing design-token system (CSS custom properties + component classes — plain CSS, no build step, genuinely reusable) for visual consistency without any dependency on the generated runtime. `main.py`'s existing `StaticFiles(..., html=True)` mount serves any file dropped into `static/` automatically — zero backend routing changes were needed to add pages. Cross-page navigation uses plain `<a>` tags; `index.html`'s own nav bar is template *markup*, not compiled logic, so adding links there was a safe, isolated edit that doesn't touch `support.js`.

**Corollary decision — `season_stats.py`'s live-call reduction kept a fallback, deliberately, rather than a clean full swap.** The new reference tables (`mlb_player_season_batting_stats`/`_pitching_stats`) are qualified-players-only by design (~150 hitters/~60 pitchers on a given day — see the sibling architecture section above). The dashboard's pre-existing Batters/Pitchers tabs are NOT restricted to qualified players — any player with a prop leg today appears, including below-threshold part-timers. A DB-only swap would have silently gone blank for exactly the players least likely to already be well known to the operator, which is a real regression disguised as a performance improvement, not a neutral change. Decision: DB-first read, live-API fallback only for players not found in the reference table — full coverage preserved, only the common case (qualified players, the majority of any day's props) skips the network round trip.

**Sequencing decision (agreed with operator before building): standings first (smallest surface, proves the pattern end-to-end) → `season_stats.py` reduction (contained, no UI change) → hitting/pitching leaderboards (same pattern as standings, more columns) → player/team drill-down cards (most complex — real interactivity, modal/route design — deferred, not blocked on anything found this session).**

**Status: steps 1-3 built and validated (each against the operator's own MLB.com screenshots, field-for-field). Step 4 explicitly deferred, operator's choice. Nothing committed or deployed as of this doc update.**

---

## SGO Billing Verification Methodology (Session 23)

### **Decision: Test Against SGO's Own Account-Level Usage Counter, Not the Codebase's Own Local Event-Count Logging**

**Background.** A cost-driven handoff (SportsGameOdds Pro→Amateur tier downgrade taking effect 2026-08-01, dropping the monthly object cap from ~100K to 2,500) needed to confirm whether SGO bills per-event or per-market before deciding how aggressively to cut call volume and scope a new full-capture feature. The handoff's own supporting evidence was `mlb_sgo_request_log.entities_consumed` tracking day-to-day game counts (9-16) across months of production logs.

**Why that evidence was weaker than it looked.** `entities_consumed` is computed **locally**, inside `sportsgameodds.py`'s `_sgo_get()`, as `len(response['data'])` — a count of items in the `/events` response's top-level array. Since `/events` structurally returns one object per game/event, with every market for that game nested inside that single object's `odds` dict, this count equals game count almost by construction, **regardless of how SGO actually bills** — the local log never counted markets at all, so it can't distinguish per-event from per-market billing on its own. Trusting it further without an independent check would have been trusting a metric that was never capable of answering the question being asked of it.

**Decision: test against SGO's own server-side usage ledger, not application-level logging.** Called `/account/usage` (documented as not counting against limits) immediately before and immediately after one real `/events` call, and compared the delta to both events-returned and total-markets-returned in that same response. Result: delta = 18, events returned = 18 (ratio 1.00, an exact match), while total markets across those 18 events was 25,486 (ratio 0.0007). This is the only test that could actually distinguish the two billing models — a local response-size count structurally cannot, no matter how many months of history back it.

**General lesson:** when verifying a third-party billing/rate-limit model, prefer the third party's own account-level counter (if one exists) over any locally-derived proxy metric, even a long-running one — a metric's historical consistency says nothing about whether it was ever capable of measuring the specific thing being asked of it.

**Status: confirmed per-event, unambiguously. Schedule-cut and full-capture scope decisions built on top of this result — see the two following sections.**

---

## Pipeline Schedule Cut — 3 Runs/Day to 2 (Session 23)

### **Decision: Drop the 12 PM Slot, Keep 9 AM + 5:30 PM, Verified Against Real Historical Data Rather Than the Handoff's Own Projection**

**Background.** With per-event billing confirmed (see previous section) and the Amateur tier's 2,500/month cap taking effect 2026-08-01, the handoff proposed dropping the pipeline's midday run to cut SGO call volume roughly a third.

**Decision: verify the actual historical contribution before trusting the ~1/3 estimate.** Pulled 7 days of real `mlb_sgo_request_log` data, bucketed by ET time-of-day, rather than accepting the handoff's own back-of-envelope math at face value. Result: 12 PM averaged 14.6 of 39.4 total daily objects (~37%) — close enough to confirm the estimate, precise enough to produce a tighter post-cut projection (~744/month) than the handoff's own (~1,110/month), using the project's own real data rather than a generic assumption.

**Side finding surfaced by this investigation, not fixed:** `mlb_parlay_recommendations_v2.source` values for the 12 PM/5:30 PM slots are literally the raw scheduler label (`'midday'`/`'evening'`) rather than the documented `'auto_12pm'`/`'auto_530pm'` convention — the 9 AM slot passes no explicit `source` and falls through to an hour-based fallback that correctly produces `'auto_9am'`, but `run_full_refresh_pipeline(source=slot_label)` passes the other two slots' raw labels straight through to `run_pipeline()`, bypassing that fallback entirely. Pre-existing (not introduced by this session's schedule-cut edit), unrelated to the change being made, and low-priority now that `'midday'` no longer fires at all — flagged in the schema reference doc rather than fixed, since fixing it wasn't asked for and touches a production data-labeling convention outside this handoff's scope.

**Implementation:** removed the `(dtime(12, 0), "midday")` tuple from `src/web/server.py`'s `_PIPELINE_SCHEDULE` — the scheduler loop is fully data-driven from that list, so no other logic change was needed. Updated the accompanying docstrings/comments/print statements and one stale reference in `main.py`'s `run_morning_pipeline()` docstring.

**Status: implemented, syntax-verified, not yet deployed.**

---

## Full Prop-Line Capture Architecture — mlb_prop_legs_history (Session 23)

### **Decision: Reuse the Existing Morning Run's Already-Fetched SGO Data (Zero New API Calls), Isolate Fully From Production Scoring, Test Both Halves Independently Before Trusting Either**

**Background.** With per-event billing confirmed, market count within a call is effectively free — the handoff's premise for asking for genuinely comprehensive prop-line capture (every player with a posted line, not just currently-qualified players) into `mlb_prop_legs_history`, a table created empty as part of Session 22's reference-schema migration. Explicitly scoped as a ground-up-rebuild calibration dataset, deliberately isolated from all production/shadow scoring and win-rate reporting — not a new signal, a new independent dataset.

**Decision 1 — reuse the existing 9 AM run's already-fetched data, make zero new SGO calls.** `main.py`'s `run_pipeline()` already fetches `sgo_games` and builds `all_sgo_props` at Step 3, every run. `capture_full_prop_lines()` takes that same data as arguments rather than re-fetching — called from inside `run_pipeline()`, gated on `not skip_resolution` (true only for the 9 AM morning run), immediately after Step 3 and before `_filter_useless_props()` narrows the pool to the production betting criteria (full capture, not gated to the production pool, is the explicit point of this table).

**Decision 2 — isolate via a wholly separate parsing path, not by extending a production-depended-on function.** `get_player_props()` (existing, used by the live production pipeline) normalizes SGO's `batting_strikeouts` and `pitching_strikeouts` raw statIDs to the same internal `'strikeouts'` stat name and discards which prefix matched — a real ambiguity for this capture's purposes (needs to separate a pitcher's own strikeout total from a batter's strikeouts-against line, mirroring an ambiguity already worked around once elsewhere in this codebase for `mlb_scored_legs`/`mlb_training_data`). Rather than add a field to `get_player_props()`'s return value (technically additive, but touching a function the live pipeline depends on, which this handoff was explicit about not doing), `_build_odd_id_role_map()` independently re-scans each game's raw `odds` dict by key prefix and cross-references by `odd_id` — zero change to any existing function's behavior or signature.

**Decision 3 — upsert reference-schema rows (`mlb_teams`/`mlb_players`/`mlb_games`) from this job's own data, don't depend on Session 22's daily refresh being deployed.** Both are separate, independently-uncommitted pieces of work as of this session; making the capture job depend on the other would create an unnecessary deployment-ordering constraint. `ON CONFLICT DO NOTHING` throughout — fills gaps only, never overwrites richer data the other job may also be writing, so behavior is identical regardless of which lands first or whether both ever do.

**Decision 4 — a schema gap in the literal migration spec, caught before it mattered.** The handoff's spec (`player_id` nullable, `market_scope` column) is necessary but not sufficient: Postgres treats every NULL as a distinct value for `UNIQUE` constraint purposes, so the existing `UNIQUE(player_id, game_pk, stat, line, direction, sportsbook)` constraint would never have deduped game-scope rows (`player_id IS NULL`) across repeated capture runs — every run would insert fresh duplicate rows instead of upserting. Added a partial unique index (`(game_pk, stat, line, direction, sportsbook) WHERE player_id IS NULL`) specifically for that case. This is the kind of constraint-semantics gap that's easy to miss reading a spec and easy to catch by actually testing the upsert path against a second run — which is exactly how it was caught (see the `ON CONFLICT` bug below).

**Two real bugs found via live testing, both fixed before this was called done:**
1. **`ON CONFLICT` target didn't match the partial index.** Postgres requires a partial index's `WHERE` predicate to be restated in the `ON CONFLICT` clause itself, not inferred from the column list — omitting it doesn't silently fall back to the base table's constraint, it raises "no unique or exclusion constraint matching" and fails the whole insert. First live test run: **zero rows written**, every game-scope upsert failed with exactly this error (and every matched game's player-leg processing was also skipped, since the per-game `try/except` caught the game-line failure — which runs first in the loop — before player-leg processing could execute at all). A clean illustration of why "wrote a migration, wrote the upsert SQL, syntax-checked it" is not the same claim as "tested the actual upsert path" — the bug only surfaces on execution against the real constraint, not on any static check.
2. **Team-abbreviation matching bug (Athletics).** 5 of 11 SGO games failed to match a schedule-derived `game_pk` on the same first test run. Rather than guess at a fix, added a debug dump of the specific unmatched team-pairs — this immediately separated two different phenomena that a single "5 unmatched" number had conflated: 4 of the 5 were a genuine testing-time artifact (`get_todays_games()` with no date override windows relative to UTC midnight, not Eastern midnight; testing at ~10 PM ET pulled in a few of the *next* Eastern calendar day's games, which obviously wouldn't match "today's" MLB schedule — expected behavior given the test's timing, not a bug, and irrelevant to the real 9 AM ET production run). The 5th was a real, fixable bug: the 2026 Athletics relocation means the team's schedule-side full name is now literally `"Athletics"` (not `"Oakland Athletics"`), which fell through the hardcoded team-abbreviation map's default (`name[:3].upper()` → `"ATH"`) instead of matching SGO's actual short name (`"OAK"`, confirmed live from the raw response). Fixed by mapping the bare name directly. The debug-dump-before-guessing approach is what made it possible to separate "real bug" from "testing artifact" instead of chasing the wrong four games.

**Decision 5 — test both halves (capture, resolution) independently, in isolation from the full production pipeline, before trusting either.** `scripts/test_prop_legs_resolution.py` inserts synthetic rows against a real, already-backfilled completed game with known outcomes (pitcher-K, batter-hits, moneyline, total) and checks the resolved result against the expected one — caught nothing (7/7 passed on first run), but exists specifically so a future change to the resolution formulas has a fast, deterministic regression check that doesn't require waiting a full day for real data to flow through. `scripts/test_prop_legs_capture.py` replicates only the schedule+SGO-fetch steps and calls the capture function directly, without running coverage gating, parlay building, or any write to `mlb_scored_legs`/recommendation tables — this is what let both bugs above be found and fixed without any risk to production data.

**Status: both capture and resolution built and validated. Capture's wiring into the real `main.py` `run_pipeline()` code path has NOT itself been exercised in a live production run — only via the isolated test script. Watch the first live 9 AM run post-deploy.**

---

## Point-in-Time Stat Backfill + Opposing-Pitcher Capture Fixed Forward (Session 24)

### **Decision: Fix the Forward-Going Drop, Decouple the Two Independent Fill Conditions After Live Data Contradicted the First Draft**

**Background.** A prior one-time backfill had already recovered `opposing_pitcher_id` historically into `mlb_training_data` (91% of batter legs, via `(player_id, game_pk) → mlb_player_batting_logs.opposing_pitcher_id`) plus point-in-time ERA/WHIP/K9. That backfill was retrospective only — `opposing_pitcher_id` was still being silently dropped **going forward**: `enrich_legs.py` correctly attaches it to each leg dict, and `mlb_scored_legs`'s own INSERT already persists it correctly, but `db.py`'s `log_training_data_legs()` never included it in its INSERT — the same class of bug as the Session 21 `lineup_consistency` silent-drop (§27).

**Fix 1 — `src/utils/db.py`.** Added `opp_pitcher_id` to `log_training_data_legs()`'s column list and values tuple (`int(leg["opposing_pitcher_id"]) if leg.get("opposing_pitcher_id") else None`). Verified via source-inspection test (`tests/test_bug_fixes.py::TestOppPitcherIdTrainingDataInsert`, mirroring the existing `TestLineupConsistencyDbInsert` pattern) that the column appears exactly once, in both the column list and the values tuple, of the single `INSERT INTO mlb_training_data` statement.

**Fix 2 — `scripts/backfill_point_in_time_stats.py` (new).** Two pieces, chained into `daily_reference_refresh.py` right after it backfills yesterday's game logs:
1. `refresh_cumulative_tables()` — incrementally appends one row per player who played "yesterday" to `mlb_player_batting_cumulative`/`mlb_player_pitching_cumulative` (running season-to-date totals, unique on `(player_id, game_date)`). Handles doubleheaders via `GROUP BY`/`SUM` aggregation before adding to the prior row; safe to re-run for the same day since "prior" is always strictly `< day`.
2. `backfill_training_data_point_in_time()` — fills `mlb_training_data.resolved_player_id`/`pt_role`/`pt_avg`/`pt_obp`/`pt_slg`/`pt_ops`/`pt_k_pct`/`pt_bb_pct`/`pt_era`/`pt_whip`/`pt_k9`/`pt_innings_pitched`/`opp_pt_*` using the two cumulative tables plus `mlb_players.primary_position` for the batter-vs-pitcher role disambiguation on `stat='strikeouts'` (`hitsAllowed`/`earnedRuns` are unambiguous pitcher-only stats needing no lookup).

**A real bug caught by testing against live data, not just logic review.** The first draft gated the opposing-pitcher (`opp_pt_*`) fill on successfully resolving the row's *own* `player_id` to a numeric ID — reasonable-looking, wrong. Querying the actual backlog (12,207 rows with `opp_pitcher_id` set but `opp_pt_era` still NULL) showed the overwhelming majority carry a pre-this-fix SGO-style string `player_id` (e.g. `"MICHAEL_MCGREEVY_1_MLB"`, from `scripts/backfill_training_data.py`'s original insert) — their `pt_role` had already been resolved by the *original* one-time backfill's own name-based crosswalk (out of scope to reproduce here), but the draft's coupling meant `opp_pt_*` would never get filled for any of them just because this script's simple int-cast couldn't *also* resolve `player_id`. Fixed by decoupling: own-role/`pt_*` fill and `opp_pt_*` fill are now independent per row, each computed from whatever inputs it actually needs.

**Live-data validation before trusting the design (read-only queries against Supabase, no test writes):** confirmed `pt_avg`/ERA/WHIP/K9 formulas by hand against `mlb_player_batting_cumulative`/`_pitching_cumulative` rows; confirmed the cumulative-refresh CTEs handle a real doubleheader correctly (2 games aggregated into 1 day's row); then ran the actual backfill against production. Results: `pt_role` coverage 104,507/105,728 (98.8%) — matches the historical rate exactly, and **0 new rows were filled by this run** — the remaining 1,221 are 100% legacy string-`player_id` rows, confirmed via `player_id ~ '^\d+$'`, correctly out of scope for this forward-going fix (as intended — `resolved_player_id` is a safety-net int-cast, not a full name crosswalk). `opp_pt_era`: 78,863/91,070 filled (86.6% overall) but **100% of the remaining 12,207 are opening-weekend (3/28–3/31, ~79% of the gap) or individual pitcher-debut games with zero prior in-season starts** — confirmed via `EXISTS`-checking every one of them against `mlb_player_pitching_cumulative`, both before and after the run: 0/12,207 had prior data either time. Excluding that structurally-unfillable set, fill rate is 100%. The decoupling fix doesn't retroactively create data that doesn't exist — its payoff is forward-looking: the next start any of those pitchers make will have real prior data and, because the fill no longer depends on the row's own messy `player_id`, will get filled on the very next daily run instead of being silently skipped.

**Constraint honored:** read-only/additive only — `simple_scorer.py`, `enriched_scorer.py`, `parlay_builder.py`, and `mlb_scored_legs`'s own (already-correct) `opposing_pitcher_id` handling were not touched.

**Status: implemented, tested via source-inspection (pytest itself not runnable in this environment — no local `DATABASE_URL`, Supabase creds live in Railway only, and `pytest` wasn't installed in the local `.venv`; verified via direct `inspect`/text-based source checks instead), and run once against production with the results above.** Chained into `daily_reference_refresh.py`, not yet deployed (see commit status in `SESSION_HANDOFF.md`/`BUILD_STATUS.md`).

---

## Coverage Threshold vs. Matchup Quality — Analysis, Re-Run Pending (Session 24)

**First pass (7/30/2026) found the `coverage_overall` hard floor (65% for `over` props, 40% for `under` props, enforced pre-scoring by `main.py`'s Gate 1) structurally excludes genuinely-low-coverage legs from `mlb_scored_legs`/`mlb_training_data` for hits/over and batter-K — making the low-coverage/good-matchup vs. high-coverage/bad-matchup comparison untestable for those two bet types.** `mlb_prop_legs_history` (Session 23) captures both directions of every market line, ungated, and is confirmed running as of today (1,014 rows logged 7/30) — but only has 1 day of history as of 7/30.

**Re-run target: 2026-08-06** (1 week of accumulation). Join `mlb_prop_legs_history` against `mlb_player_batting_cumulative`/`_pitching_cumulative` (already built, no crosswalk needed — clean `player_id` from day one) and repeat the coverage-band × matchup-band grid, interaction model, and Q3-vs-Q2 quadrant test from the first pass.

**First-pass results for reference (full detail in `docs/COVERAGE_VS_MATCHUP_ANALYSIS.md`):** hits/over showed no support for loosening the gate (Q3 lost to Q2 by 8.4pp, interaction p=0.765). totalBases showed real support (Q3 beat Q2 by 11.5pp / ~$0.21 EV per $1, on adequate n) but is shadow-only, not live production. Batter-K was directionally supportive (Q3 beat Q2 by 10pp, significant interaction in both coverage proxies tested) but every relevant cell sits under the project's own n<50 reliability bar. Pitcher-K is untestable — no opposing-matchup metric applies to a pitcher-role leg (it faces a lineup, not one opposing pitcher).

**A second, independent methodological finding from the same pass:** `coverage_overall`/`composite_score` are only consistently defined from **2026-06-09** onward — before that, a different (pre-current) scoring pipeline was in effect, confirmed via `composite_score` values (as low as 1.36) that are mathematically impossible under the current `calculate_composite_score()` formula given a 65%+ base-coverage floor. The full baseline correlation table this task started from (Pearson 0.00–0.08 across signals) mixed both eras — restricting to the internally-consistent post-6/9 regime alone raised measured win rates from 50–53% to 58–63%, meaning the original near-zero correlations partly reflect era-mixing, not proof the whole system is signal-free. Re-verify this cutover is still the right boundary (or has moved) before the 8/6 re-run, rather than assuming the date carries forward unchanged.

**Status: analysis complete and written up, re-run explicitly scheduled, not a scoring change** — per the task's own constraint, no changes were made to `simple_scorer.py`/`parlay_builder.py`/`_filter_legs()`. See `docs/COVERAGE_VS_MATCHUP_ANALYSIS.md` for the full Step 1/2/3 methodology, all four bet types' grids, and the complete recommendation.

---

## Silent Pipeline Stall — Unbounded statsapi.* Network Calls (Session 25)

### **Decision: Wrap Every statsapi.* Call Site in a Hard Wall-Clock Timeout, Rather Than Trust the Third-Party Library's Docstrings**

**Background.** Both the production (`mlb_parlay_recommendations_v2`/`mlb_parlay_legs_v2`) and shadow (`mlb_parlay_recommendations_enriched`/`mlb_parlay_legs_enriched`) pipelines had written zero new rows since **2026-07-23 17:27:51 UTC** — the exact gap Session 24 flagged as a pending item without root-causing (§36/`SESSION_HANDOFF.md` Pending Items). `mlb_scored_legs` stayed fully healthy the entire 12-day gap (51-73/165+ pool-eligible legs/day) — only the step past scoring was affected. Every affected run (both morning and evening scheduled slots, every day) logged `[7/8] Computing trend signals...` and then produced **zero further output** — no exception, no traceback, no DB write, CPU/memory flat at idle — until the process was eventually superseded by the next scheduled trigger, which stalled at the identical spot.

**The leading hypothesis going in was wrong, and was disproven with direct evidence before any fix was written (per this project's evidence-first rule).** The natural read of "stalls right after `[7/8] Computing trend signals...`" is that `_attach_trend_signals()`'s per-leg loop (`get_batter_game_log()`, one HTTP call per batter leg, ~150-180/day, fully sequential) was hanging. That function already has `requests.get(timeout=15)` on its underlying call. To confirm or rule this out with real evidence rather than plausible-sounding reasoning, added flush-forced per-call instrumentation to the loop, deployed it, and triggered a live run via the admin API — it processed all 162 legs cleanly, in well under a second of application time. The stall was not there.

**Root cause, confirmed by tracing forward from where the live run actually did stop.** The very next step — `get_pitcher_ranks()`/`get_team_offensive_ranks()` (`src/apis/pitcher_stats.py`, `src/apis/team_stats.py`), looping over ~245 qualified pitchers and 30 teams — calls the third-party `statsapi` package's wrapper functions (`statsapi.get()`, `statsapi.player_stat_data()`). Reading that package's source directly (`.venv/Lib/site-packages/statsapi/__init__.py:1785`) rather than trusting its docstrings showed every one of these wrappers calls `requests.get(url, **request_kwargs)` with `request_kwargs={}` as the default — **no timeout, anywhere, with no parameter exposed by most of the wrapper functions to set one.** `requests` documents plainly that a call with no timeout can hang forever. A repo-wide grep found the identical pattern at ~20 call sites across both the production and shadow pipelines (`mlb_stats.py`'s `schedule`/`standings_data`/`boxscore_data`/`get`, `pitcher_stats.py`, `team_stats.py`, `lineup_confirmation.py`, `enrich_legs.py`, `run_enriched_pipeline.py`, `main.py`'s own direct calls) — this is why both pipelines stalled together on 2026-07-23: they share this code, not two independent bugs.

**Caveat, stated explicitly rather than papered over:** a live full-pipeline trigger on the fixed deploy did **not** reproduce a hang — it ran end-to-end in both the pre-fix (~3.5 min) and post-fix (~2m52s) tests, differing only in that the pitcher/team-ranks step completed normally both times rather than stalling. The failure is evidently intermittent, gated by real-world MLB Stats API conditions at the moment of the call (consistent with production stalling specifically at the 9 AM/5:30 PM ET trigger windows every day, not at an off-schedule manual trigger). The missing-timeout defect itself is 100% code-confirmed regardless of whether a live hang was personally caught mid-flight — see [§67 in Lessons Learned](#lessons-learned) for the general principle this leaves behind.

**Fix — `src/utils/net.py` (new), `call_with_timeout()`.** Most `statsapi` wrapper functions (`player_stat_data`, `schedule`, `boxscore_data`, `standings_data`, `lookup_player`) don't expose a way to pass a timeout through at all — only the low-level `statsapi.get()` accepts `request_kwargs`. Rather than fork the third-party library or reimplement its response parsing, `call_with_timeout()` runs the wrapped call in a dedicated daemon thread and enforces a wall-clock deadline via a `queue.Queue.get(timeout=...)`, returning a caller-supplied default and logging clearly (`[net] TIMEOUT: ...`) instead of blocking forever. **Each call gets its own thread rather than a shared pool** — a shared `ThreadPoolExecutor` would let enough permanently-hung calls exhaust the pool's worker slots, turning "some calls are slow" into "all future calls block forever waiting for a free worker," which would just move the same failure mode one layer up.

**Applied at every live-pipeline `statsapi.*` call site** (both prod and shadow), each bounded to 15s — matching the bound `mlb_stats.py`'s own direct `requests.get()` calls already used. Additionally added an overall wall-clock deadline (90s) to the three long sequential loops (`_attach_trend_signals`, `get_pitcher_ranks`, `get_team_offensive_ranks`) so a run where every individual call happens to time out still fails loudly and continues with partial data, rather than taking up to an hour in the worst case.

**Verification.** `tests/test_net_timeout.py` (new) proves a call that never returns is bounded to ~`timeout` seconds and returns cleanly rather than blocking (5/5 passing). Full existing suite could only be partially run locally — `tests/test_bug_fixes.py`/`test_enriched_scorer.py`/`test_lineup_confirmation.py` import `src/utils/db.py`, which connects to Postgres at module load time, and no `DATABASE_URL` was available in this session's local environment; `tests/test_time_utils.py` (12) plus the new suite (5) — 17/17 — ran and passed locally. Deployed to both Railway services (`mlb-agent`, `dashboard-api`), confirmed live via `list-deployments`/`get-status`, then verified with two consecutive forced full-pipeline runs on the fixed code (`run_morning_pipeline` — the exact function the scheduler itself calls) — both completed all 8/9 steps cleanly, including the previously-hanging pitcher/team-ranks step, with no hang. Zero new parlay recommendation rows landed on either verification run, but for an unrelated, legitimate reason (best 4-leg combination only reached +337/+342 odds vs. the +400 minimum) — confirmed identical on both the pre-fix and post-fix runs, so not a symptom of this bug.

---

## Parlay Builder — Floor-Recovery via Bounded Leg Swap (Session 26)

### **Decision: Search for an Alternative 4-Leg Combination Before Giving Up, Bounded to the Full Remaining Pool Rather Than a Score-Sorted Slice**

**Background.** Session 25's caveat ("zero new parlay recommendation rows landed... best 4-leg combination only reached +337/+342 odds") turned out not to be a one-off — every subsequent live trigger of the fixed pipeline kept missing the +400 floor by a small margin (+337, +342, +332 across several runs that day) and producing 0 parlays. `src/engine/parlay_builder.py`'s `build_parlays()` picks legs by a single greedy pass sorted only by `composite_score`, checks the odds floor only after 4 legs are locked in, and — critically — `break`s the entire per-rank loop on the first miss, abandoning every remaining parlay slot in the batch too.

**Design intent preserved, per operator confirmation before any code was written:** score-first selection stays the primary criterion (odds are a constraint on the *combination*, not a selection criterion for individual legs); the fixed 4-leg structure stays fixed (`MIN_LEGS == MAX_LEGS == 4`, not reintroducing the 5-6-leg range reverted in [§26](#parlay-builder--leg-count-reverted-to-fixed-4-session-21)); the 3-5-parlays-per-run target and all existing per-player/per-game/cross-parlay-diversity constraints stay unchanged.

**Fix — `_attempt_swap_recovery()`.** When the greedy top-4 pick misses the floor, tries replacing each of the 4 selected legs with each remaining eligible alternative in the pool, checking the same per-player/per-game/no-duplicate-odd_id constraints (`_leg_fits()`) the greedy pass enforces. Among all swaps that clear the floor, keeps the one with the highest total `composite_score` across all 4 legs — not just the first found — which is what keeps the fix "score-first" even in the recovery path: a swap search that stopped at the first floor-clearing combination would silently trade away score for whatever alternative happened to be checked first. Bounded to `len(legs) * SWAP_CANDIDATE_LIMIT` attempts, never unbounded; each outcome (`clean top-4 pass` / `recovered via swap — N attempt(s)` / `no combination found — N attempt(s)`) is logged explicitly rather than failing silently.

**A real gap found via live-data testing, before trusting the first version of the fix.** The task's own suggested implementation shape — "try swapping each position against the next 5-10 best alternatives" — was implemented literally first: `SWAP_CANDIDATE_LIMIT = 10`, candidates drawn from the next 10 best-*scored* remaining legs. A live full-pipeline trigger on this version still produced 0 parlays (`no combination found — 40 attempt(s)`, exactly `4 × 10`, confirming the bound itself was working correctly — it just wasn't wide enough). Rather than accept "no combination found" as a legitimate outcome without checking, pulled today's actual eligible pool directly from `mlb_scored_legs` and checked by hand: a real floor-clearing combination existed — Jake Cronenworth (-123), Ryan Waldschmidt (-139), Seiya Suzuki (-158), Ezequiel Tovar (-161) → **+725 combined**, comfortably clearing +400 — but those four legs ranked **18th, 20th, 32nd, and 18th** by `composite_score` respectively, well outside a top-10-by-score cutoff. The underlying cause: `composite_score` and odds are not correlated in this system — score also reflects coverage/trend/matchup signals independent of raw win probability, so a modest-score leg can carry much better (longer) odds than a top-scored one, and vice versa. A search restricted to "next-best by score" structurally cannot find that leg, no matter how wide the cutoff, if the cutoff is small relative to how far down the pool a good-odds leg happens to rank.

**Corrected fix.** Widened the search to the full remaining pool per position instead of a score-sorted top-N slice — `SWAP_CANDIDATE_LIMIT` raised from 10 to 200, reframed as a safety cap on total attempts (protecting against a hypothetical very large pool), not a score-based relevance cutoff. Real eligible pools in this system run ~30-180 legs (matching every pool size observed across Sessions 25 and 26's live triggers), so a worst case of `4 × 180 ≈ 720` checks stays cheap and instantaneous — nowhere near what the task's own "not an unbounded search" constraint was guarding against.

**Verified against real data twice before calling it done, not just against synthetic test cases.** First, replayed today's actual 39-leg eligible pool (pulled directly from `mlb_scored_legs`, not reconstructed or approximated) through the corrected `build_parlays()` locally: produced 5 valid parlays, every one recovered via swap, hitting the top of the 3-5 target — before spending a deploy cycle on it. Second, after deploying, triggered the real `run_morning_pipeline()` (the exact function the 9 AM/5:30 PM ET scheduler calls) and confirmed via direct SQL query against `mlb_parlay_recommendations_v2`/`mlb_parlay_legs_v2` — not log output alone, per this task's own explicit instruction that a past session's "completed cleanly" claim had not matched what was actually in the database: **5 parlays written** for `run_date = 2026-08-04` (+450, +402, +421, +413, +427), every one using the swap-recovery path, each pairing 3 short-odds/high-score legs with one longer-odds/lower-score leg (e.g. Trea Turner -137, Ryan Waldschmidt -142, Jake Cronenworth -127, Jonathan Aranda -178, Ben Rice -173) — the exact pattern the fix was designed to recover.

**Status: implemented, tested (10/10 passing in `tests/test_parlay_builder.py`, including a regression test locking in the good-odds/low-score gap found above), deployed to both Railway services, and confirmed live via a real database write** — not yet observed via an unattended 9 AM/5:30 PM ET scheduled trigger specifically (only via manual admin-endpoint triggers, both before and after this fix), which remains the last open verification step shared with Session 25's own unclosed loop.

---

## Lessons Learned

*(Items 1-54 unchanged from prior version — see full list in git history / prior document version.)*

50. **A concentrated, thin sample can flip its own conclusion with more data, and the concentration itself can be the more useful finding.** hits/under's 14-day dedup read (36.4% WR, n=11, dominated by two repeat players) looked like a real problem. Extending to 35 days reversed it entirely (57.9% WR, n=57). The root cause underneath both reads was the same either way — only 1-3 players/day clear the 65% coverage floor for this prop — which turned out to be the actually durable, actionable finding (pool scarcity), independent of which win-rate read was "right." When a sample is this thin, characterizing *why* it's thin is often more useful than trusting either read of the win rate.

51. **A "verified via code review" claim on a visual bug is not verification.** The sticky-header bug was declared fixed twice via CSS/JS reasoning alone, and was wrong or worse both times — the second attempt's fix produced a *more* broken result (an overlapping, clipped row) than the first. Neither Claude Code nor Claude (chat) had rendering tools available in either case; both correctly said so explicitly on request, rather than asserting confidence they didn't have — but the pattern of reasoning-only "verification" on a rendering bug should have been questioned sooner, ideally by pushing to the real environment after the first failed attempt instead of the second.

52. **Testing a hypothesis against real data before writing any code is cheaper than debugging the alternative afterward.** The entire parlay-builder redesign — a large rewrite touching leg-count logic, odds targeting, and three call sites — was preceded by a single, cheap SQL-and-arithmetic check (top-4-by-score clears +400 on 14% of days) that either would have validated or killed the hypothesis before any code was written. It validated it, and the same technique (test the proposed fix's leg count against real data before building it) found the actual right leg count (5, not the originally-proposed "4-6 as a range with no further guidance") in the same pass.

53. **A fix for one failure mode (a security hole) can create a new failure mode (misleading diagnostics) elsewhere, and both can be correct decisions in isolation.** Tightening the auth check to require an exact 200 was the right fix for a real hole (a 500 previously granted access). But it also meant every future non-auth 500 would display as "wrong password" until the Decimal bug surfaced this directly. Neither decision was wrong; the interaction between them just wasn't visible until it was tested live. Worth deliberately asking "what does this failure mode look like to the user" whenever tightening an error-handling boundary, not just "does this close the hole."

54. **Applying the same principle consistently sometimes means reversing your own recent decision.** The entire justification for the builder redesign was "don't force a payout target to override leg quality." Two exchanges later, the manual dashboard's first draft did exactly that to human picks (hard-blocking anything below +400). Recognizing the inconsistency and reversing it (floor becomes advisory, not blocking) took applying the same standard already established minutes earlier, not new analysis.

55. **Two different write paths to the same column, using different conventions, with identical-looking values, are a latent time bomb.** `game_start_time` stored UTC in one path and Eastern Time in another — same naive timestamp string format, no distinguishable suffix. Didn't blow up immediately; blew up silently (503 affected rows, 15 game_pks with split values) after weeks of accumulated data. Defense: enforce a single canonical write function for any column with a non-obvious convention (timezone, unit, encoding), imported from one place, rather than independently reimplementing the write in each script that touches the column.

56. **"Root cause confirmed" and "root cause reconstructed" are different claims — be precise about which one you're making.** The Brandon Lowe `matchup_adj = NULL` issue appeared resolved after `6bdd86b` deployed, with a coherent explanation: the pytz crash at line 510 prevented `_log_enriched_legs` from running, so `matchup_adj` was computed but never persisted. This explanation is consistent with the code structure, the commit timing, and the live DB result — but it was never confirmed by a log line showing the exception. The actual debug run captured all three checkpoints behaving correctly because it ran after the fix. Railway logs for the broken timeframe were not retrieved. The explanation should be held as "most likely, reconstructed from code analysis" rather than "confirmed." When a fix works and the failure mode was never directly observed, say so explicitly instead of retrofitting certainty.

57. **A gating threshold on the comparison metric can hide inside what looks like a controlled test.** Comparing win rate across buckets of an adjustment (e.g. "weak pitcher" vs. "neutral") looks like a fair test, but if the pool is already filtered on `composite_score >= 65`, a bonused leg only needed a lower base coverage to clear the floor than a non-bonused leg did — making the bonused bucket look weaker (or a penalized bucket look stronger) purely from selection, independent of whether the adjustment itself is right. The fix was cheap once named: re-bucket within narrow bands of the *base* coverage value, not the post-adjustment composite score, before trusting a directional read.

58. **A signal built the same way as a known-broken signal deserves the same scrutiny, proactively, not just when someone complains.** The pitcher ERA adjustment came from the exact same function and raw stat split (`_fetch_pitcher_season_stats()`, cumulative season, 5.0 IP floor) as the WHIP signal that was found contaminated and removed on June 25. ERA sat unexamined for weeks afterward simply because nobody had asked the same question of it yet — the shared-source relationship alone was reason enough to check, and once checked, it showed the identical failure signature.

59. **A completed persistence bug and a completed backtest can both be individually correct while creating a compounding blind spot.** `lineup_consistency`'s DB column being silently unpopulated for the entire season meant there was zero historical data available to ever backtest whether its 0.70 filter threshold does anything useful — the fix (persistence) has to happen before the analysis (does the threshold work) can even be attempted, and it's worth being explicit that these are two separate, sequential pieces of work rather than treating "fixed the bug" as "validated the signal."

60. **A large historical sample under the old configuration can justify reverting a change even when a live simulation of the revert comes back ambiguous.** The fixed-4-leg era had 486 resolved parlays at +$0.128 EV/$1 — a strong, low-noise baseline. A same-session simulation of "what would a hard revert look like against current signals" produced two overlapping windows disagreeing with each other by ~10 points of win rate (n=48, n=69) — too thin to resolve further by backtesting. Rather than keep testing an already-exhausted small sample, the honest move was to revert on the strength of the large historical baseline and treat "does it fully restore profitability" as a live-tracking question, flagged explicitly as open rather than papered over with a confident-sounding simulation result.

61. **A wrapper library's docstring describes intent; the actual network response is the only thing worth trusting before a large, unattended batch job.** `statsapi.boxscore_data()`'s own docstring implied `plateAppearances`/`gamesStarted` would be present in per-player stat dicts — reasonable to assume, since those are standard MLB box score fields. Live inspection showed the function's own hardcoded `fields` API-parameter whitelist silently strips both. A draft script built against the plausible-but-unverified assumption would have run "successfully" (no errors, no crash) while inserting zero batting logs and always computing `is_starter = False` — a failure mode that produces no error message at all, only quietly wrong data, which is the worst kind to catch after the fact on a 150-day backfill. The fix was cheap (a few live test calls) relative to the cost of discovering this after running the full range. (Session 22)

62. **A generated build artifact with no committed source isn't "extend cautiously," it's "cannot extend."** `dashboard_api/static/support.js`'s own header names the exact rebuild command (`cd dc-runtime && bun run build`) and source path — but that source directory doesn't exist in the repository. This is a stronger finding than "this file is risky to hand-edit"; it means the normal edit-source/rebuild workflow is categorically unavailable, not just inadvisable. Worth explicitly checking whether a generated file's declared source actually exists before scoping any work that assumes it can be extended — the file's own header comment is exactly the right place to look, and confirming or refuting it takes one `find`/`glob` call. (Session 22)

63. **A performance optimization that changes which records are reachable is a regression wearing a performance optimization's clothes.** Swapping a live per-request API call for a local DB read looks like a strict improvement — same data, faster path. It isn't strictly the same data when the DB table has a narrower scope (qualified-players-only) than the live API call did (any player). Recognizing this before shipping, and keeping a fallback for the excluded case rather than accepting the narrower scope as an acceptable trade-off, is what kept this from being a silent coverage regression dressed up as a speedup. Worth checking the *scope* of a replacement data source against the *scope* of what it's replacing, not just whether the values match for the cases both sources cover. (Session 22)

64. **A metric's long, consistent history says nothing about whether it was ever capable of answering the question being asked of it.** `mlb_sgo_request_log.entities_consumed` had tracked game count across months of production logs — consistent, plausible-looking evidence for per-event billing. But it's a local count of `/events` response items, which trivially equals game count by construction (one object per event) regardless of how SGO actually bills; it never counted markets, so it structurally couldn't distinguish the two billing models it was being cited as evidence for. The only test that could actually answer the question was the third party's own account-level usage counter, checked before/after one real call. When verifying a claim about an external system's behavior, ask whether the evidence being relied on was ever capable of falsifying that claim — not just whether it's been consistent. (Session 23)

65. **A response of "0" from a new code path is itself a signal worth investigating, not a completeness finding to report as-is.** `get_totals_props()` returning 0 game-total legs across 18 real games looked, at first, like a genuine absence of game-level markets — a plausible-sounding completeness gap for a response-completeness check to surface. It was actually a wrong key prefix in unused code (`runs-*` vs. the live `points-*`), confirmed by dumping the raw keys rather than accepting the zero. The general habit: an unexpected zero from newly-exercised code is exactly as likely to be a bug in the new code as a real absence in the data — check which before reporting either as fact. (Session 23)

66. **A migration that satisfies the literal spec can still be incomplete if it doesn't account for how the database enforces uniqueness.** "Make player_id nullable, add a scope column" (the literal ask) is necessary but not sufficient for game-scope rows to actually dedupe across repeated runs — Postgres treats every NULL as distinct for `UNIQUE` purposes, a fact that doesn't show up anywhere in a plain reading of the requested column changes. The gap was invisible until the upsert path was actually executed twice against real data; a single test run wouldn't have caught it either (the first run's `ON CONFLICT` bug masked it entirely — the constraint mismatch failed before the NULL-uniqueness question ever got exercised). Worth explicitly asking "how does the database's own conflict-resolution behave for the nullable column in this constraint" whenever a nullable column is being added to something with a `UNIQUE`/`ON CONFLICT` story, not just whether the column change itself compiles. (Session 23)

67. **Debug output that separates "which specific cases failed" from "how many failed" turns a guessing game into a two-minute diagnosis.** 5 of 11 games not matching looked like one problem (a team-abbreviation bug) and would have been chased as one — the fix attempt would likely have started with the Athletics, found it, declared victory, and left 4 residual failures unexplained. Dumping the actual unmatched pairs immediately split it into two unrelated phenomena (a real bug affecting 1 pair, a testing-time artifact affecting the other 4) that needed completely different responses (fix one, ignore the other as expected). The cost of adding that dump was trivial; the alternative was a much longer trial-and-error loop, or worse, a wrong conclusion that the matching logic was still broken after the real fix landed. (Session 23)

68. **The most plausible-sounding hang location and the actual hang location can be one step apart — instrument and confirm before fixing, don't stop at "looks right."** The natural read of a stall immediately after `[7/8] Computing trend signals...` printed was that the trend-signals loop itself was hanging — reasonable, specific, and wrong. Live instrumentation showed that function completing cleanly; the real defect was one step downstream, in a different module, using a different network-call pattern (a third-party library with no timeout at all, vs. the trend-signals loop's already-bounded `requests.get(timeout=15)`). Both defects share a root cause (unbounded network calls in a sequential per-item loop) but are not the same code, and a fix aimed at the first hypothesis would have shipped, looked plausible, and done nothing — the pipeline would have kept silently stalling at the exact same real spot. Also worth naming as its own lesson: a fix can be code-confirmed correct (a genuinely-missing timeout, proven by reading the dependency's source) without ever personally catching the failure in the act, when the failure is gated by real-world conditions (here, upstream API behavior at specific times of day) that a single verification run may simply not hit — "confirmed defect" and "reproduced the failure" are different claims, and it's fine to ship the fix on the strength of the first while being explicit that the second didn't happen this time. (Session 25)

69. **A bound copied faithfully from a task's own suggested example can still be wrong for the real data, and the only way to know is to check the real data.** The parlay-builder floor-recovery fix's first version implemented the task's own suggested shape almost verbatim — "swap against the next 5-10 best alternatives" became `SWAP_CANDIDATE_LIMIT = 10`. It compiled, passed its unit tests (which used synthetic data shaped to fit within that bound), and deployed cleanly — then still produced 0 parlays live, because in the real pool the legs with the best odds ranked 18th-33rd by score, outside the top-10 window the bound assumed was "close enough." The bound wasn't unreasonable in isolation; it was wrong specifically because it assumed two variables (composite_score and odds) would stay correlated enough that a score-sorted slice would also be an odds-good slice, and that assumption was never actually true in this system's scoring model. The fix wasn't "raise the number a little" — it was recognizing the bound's *shape* (a score-sorted cutoff) was the wrong filter entirely, not just miscalibrated. A task's own suggested implementation is a starting hypothesis, not a spec to trust unverified — especially when it encodes an implicit assumption about how two fields relate. (Session 26)

70. **Verifying against the database, not the log line that claims success, is what actually catches a fix that only looks like it worked.** `build_parlays()`'s own log output ("Parlay 1 selection: recovered via swap") would have read as success on the very first (too-narrow) version of the swap-recovery fix, right up until the final line reported 0 parlays — the log was accurate, just for a step that wasn't the one that mattered. The task's own instruction to query `mlb_parlay_recommendations_v2` directly, rather than trust a "completed cleanly" claim, is what turned "the code ran without error" into "the code produced the actual outcome it was built to produce" — a distinction this project has hit before (Session 25's own pipeline-stall verification) and is worth treating as a standing rule for this codebase, not a one-off precaution. (Session 26)

---

## Future Considerations

*(Items 1-11 carried over from Session 15 — see prior version. Items 12-17 carried from Session 16/17. Updated/new items below.)*

### **12. TB/under Parlay Construction Strategy — Rerun Required Under New Builder (Session 16, updated Session 18, likely moot as of Session 21)**
The original combinatorial-drag numbers (with/without TB leg) were generated entirely under the old fixed-4-leg builder. Session 21 reverted the builder back to fixed-4-leg (see [§26](#parlay-builder--leg-count-reverted-to-fixed-4-session-21)) — the original numbers may be valid again without a rerun. Confirm this before spending time re-analyzing.

### **13. Fix void_reason Logging Gap (Session 16, still not done)**
Unchanged from prior version.

### **14. Re-evaluate Batting Order Slot Data With an Unbiased Sample (Post-Removal, still pending)**
Unchanged from prior version.

### **15. Confirm Origin of Commit 85b5bd5 — RESOLVED Session 18**
Confirmed via direct inspection: docs-only commit (`Update SESSION_HANDOFF.md`), no code content. No further action needed. Removed from active pending items.

### **16. Investigate Unexplained April/May SGO Traffic (Session 17, still not investigated)**
Unchanged from prior version.

### **17. Add mlb_sgo_request_log and sgo_request_log to SUPABASE_SCHEMA_REFERENCE.md — DONE (Session 17)**
Confirmed present in the current schema reference doc.

### **18. Commit a Persisted Regression Test Suite for parlay_builder.py (New, Session 18, High Priority)**
The greedy selector rewrite's 7-case validation was run ad hoc and never committed. Build `tests/test_parlay_builder.py` covering: 4-6 leg range enforcement, floor clearance without a ceiling, per-game cap, per-player cap, and the "insufficient pool" no-op case. `pytest` is not currently installed in the venv.

### **19. Live-Data Performance Recheck of the New Builder — RESOLVED Session 21**
Completed. The 4-6-leg floor-only builder was found to be running at negative EV (−$0.42 to −$0.66 per $1 staked, vs. +$0.128 under the old fixed-4-leg structure). `MAX_LEGS` reverted to 4 — see [§26](#parlay-builder--leg-count-reverted-to-fixed-4-session-21). Follow-up open item: confirm the revert restores full pre-redesign EV via live tracking (a same-session simulation suggested a possible partial gap, unresolved — see `SESSION_HANDOFF.md` Pending Items).

### **23. Confirm lineup_consistency Step 5b Filter Is Actually Executing (New, Session 21, High Priority)**
The DB-persistence fix (§27) means the field will populate going forward, but doesn't confirm the upstream filter in `main.py` has been successfully calling the MLB Stats API rather than silently hitting its wrapping `try/except` on every run. Needs a Railway log check for `[5b]`/`[lineup_consistency]` output on a live run.

### **24. Build and Backtest the Pitcher ERA Signal Rebuild (New, Session 21, High Priority)**
Scoped in full at [§29](#pitcher-era-signal--contamination-confirmed-rebuild-scoped-session-21) — recent-starts ERA via a new `get_pitcher_game_log()`, raised IP floor, controlled-band backtest before shipping. Not started. Explicitly deferred by operator decision this session (wanted the signal rebuilt, not removed).

### **25. Re-Validate lineup_consistency's 0.70 Filter Threshold Once Data Accumulates (New, Session 21, Medium Priority)**
No historical data has ever existed to check whether 0.70 is the right cutoff — the field was never persisted before this session. Revisit once a few weeks of live data exist post-fix.

### **26. Monitor K9-Rank Signal With More Data (New, Session 21, Medium Priority)**
Shares the same data-source risk as the now-confirmed-inverted ERA signal, but controlled testing this session was inconclusive rather than clearly backwards. No action taken pending a larger sample.

### **20. SO/over Pool-Composition Softening (New, Session 18, Medium Priority)**
The composite score's K/9-rank differentiation between selected and non-selected SO/over legs nearly vanished coincident with the July 2 slot-gate fix. Unclear if this is a real pool-composition shift or noise from ~1 week of data. Recheck with more volume.

### **21. Validate Batter Stat Ranges for Shadow Scorer (New, Session 19, High Priority)**
The OBP/BA/K%/BB% midpoints and half-ranges in `enriched_scorer.py` use league-average estimates (`_OBP_MID=0.350, _OBP_HALF=0.070` etc.). After the first few shadow runs, pull actual p5/p95 from the computed batter stats in the shadow run logs and update these constants to match the real range of this leg pool — the same methodology used to derive ERA/WHIP/K9 ranges from `mlb_scored_legs` data.

### **22. Shadow vs. Production Win Rate Comparison (New, Session 19, Medium Priority)**
No backtest — historical window too thin and was actively misleading in analysis during Session 19. Instead: run shadow for 3-4 weeks, then compare shadow vs. production win rate and edge (WR vs. odds-implied probability) using existing comparison queries in `SUPABASE_SCHEMA_REFERENCE.md`.

---

**Architecture Status:** ✅ OPERATIONAL — the silent pipeline stall (§37) and the parlay builder's zero-recovery-on-missed-floor bug (§38) are both fixed, deployed, and confirmed live — the latter via a real database write of 5 parlays from a manually-triggered run of the scheduler's own function. Sessions 22, 23, and 24's combined work remains validated and was already live as of `1db8918` (2026-07-31) — see `SESSION_HANDOFF.md`/`BUILD_STATUS.md` for commit status.
**Last Major Change:** August 4, 2026 (Session 26) — fixed the parlay builder giving up entirely (all remaining parlay slots too) when the top-4-by-score pick missed the +400 odds floor by a small margin. `_attempt_swap_recovery()` searches the full remaining eligible pool for a floor-clearing single-leg swap, bounded to `len(legs) * SWAP_CANDIDATE_LIMIT` attempts; a too-narrow first version (candidates limited to the next 10 best-scored alternatives) was caught via live-data testing and widened before shipping, since odds and composite_score aren't correlated in this system (§38)
**Prior Major Change:** August 4, 2026 (Session 25) — root-caused and fixed the 12-day silent parlay-pipeline stall: every `statsapi.*` call in the live pipeline (~20 call sites, both prod and shadow) now has a bounded timeout via the new `src/utils/net.py::call_with_timeout()`, plus an overall wall-clock deadline on the three long per-item loops (§37)
**Next Architecture Review:** Commit and push Sessions 22-24's combined work (in progress as of this update) / re-run the coverage-vs-matchup analysis 2026-08-06 / investigate why `mlb_parlay_legs_v2` shows no new legs since 2026-07-23 (found during Session 24's analysis, not yet root-caused) / confirm lineup_consistency Step 5b filter is actually executing via Railway logs / build and backtest the pitcher ERA rebuild / validate batter stat ranges after first shadow runs
