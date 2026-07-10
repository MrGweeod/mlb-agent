# MLB Parlay Agent — Architecture Decisions
**Last Updated:** July 10, 2026 (Session 19 — Scratch Rewrite + Dead-Link Fix; Shadow Scoring Rebuild; Manual Dashboard Coverage Column)

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
25. [Lessons Learned](#lessons-learned)
26. [Future Considerations](#future-considerations)

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
     + consistency_adjustment     # gap-based ±6/±4/±2/+2/+1
     + era_adjustment             # ±5 for hits props (raw pitcher_era — pending revalidation)
     + whip_rank_adjustment       # ±5 for hits props — REMOVED Session 15
     + k9_rank_adjustment         # ±5 for SO props (pitcher_k9_rank)
     + lineup_stability           # -5 if lineup_consistency < 0.50
     + slot_gate_penalty          # -8 if unfavorable batting_order — REMOVED Session 16
```

**Unchanged this session** — Session 18 touched leg *selection* (how many legs, what odds target), not leg *scoring* (the composite_score formula above). Composite score remains the sort key the new builder walks. See Session 18's finding that the score's K/9-rank differentiation weakened post-slot-gate-fix — a scoring-quality question, still open, not addressed by the Session 18 selection-logic change.

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

## Lessons Learned

*(Items 1-54 unchanged from prior version — see full list in git history / prior document version.)*

50. **A concentrated, thin sample can flip its own conclusion with more data, and the concentration itself can be the more useful finding.** hits/under's 14-day dedup read (36.4% WR, n=11, dominated by two repeat players) looked like a real problem. Extending to 35 days reversed it entirely (57.9% WR, n=57). The root cause underneath both reads was the same either way — only 1-3 players/day clear the 65% coverage floor for this prop — which turned out to be the actually durable, actionable finding (pool scarcity), independent of which win-rate read was "right." When a sample is this thin, characterizing *why* it's thin is often more useful than trusting either read of the win rate.

51. **A "verified via code review" claim on a visual bug is not verification.** The sticky-header bug was declared fixed twice via CSS/JS reasoning alone, and was wrong or worse both times — the second attempt's fix produced a *more* broken result (an overlapping, clipped row) than the first. Neither Claude Code nor Claude (chat) had rendering tools available in either case; both correctly said so explicitly on request, rather than asserting confidence they didn't have — but the pattern of reasoning-only "verification" on a rendering bug should have been questioned sooner, ideally by pushing to the real environment after the first failed attempt instead of the second.

52. **Testing a hypothesis against real data before writing any code is cheaper than debugging the alternative afterward.** The entire parlay-builder redesign — a large rewrite touching leg-count logic, odds targeting, and three call sites — was preceded by a single, cheap SQL-and-arithmetic check (top-4-by-score clears +400 on 14% of days) that either would have validated or killed the hypothesis before any code was written. It validated it, and the same technique (test the proposed fix's leg count against real data before building it) found the actual right leg count (5, not the originally-proposed "4-6 as a range with no further guidance") in the same pass.

53. **A fix for one failure mode (a security hole) can create a new failure mode (misleading diagnostics) elsewhere, and both can be correct decisions in isolation.** Tightening the auth check to require an exact 200 was the right fix for a real hole (a 500 previously granted access). But it also meant every future non-auth 500 would display as "wrong password" until the Decimal bug surfaced this directly. Neither decision was wrong; the interaction between them just wasn't visible until it was tested live. Worth deliberately asking "what does this failure mode look like to the user" whenever tightening an error-handling boundary, not just "does this close the hole."

54. **Applying the same principle consistently sometimes means reversing your own recent decision.** The entire justification for the builder redesign was "don't force a payout target to override leg quality." Two exchanges later, the manual dashboard's first draft did exactly that to human picks (hard-blocking anything below +400). Recognizing the inconsistency and reversing it (floor becomes advisory, not blocking) took applying the same standard already established minutes earlier, not new analysis.

---

## Future Considerations

*(Items 1-11 carried over from Session 15 — see prior version. Items 12-17 carried from Session 16/17. Updated/new items below.)*

### **12. TB/under Parlay Construction Strategy — Rerun Required Under New Builder (Session 16, updated Session 18)**
The original combinatorial-drag numbers (with/without TB leg) were generated entirely under the old fixed-4-leg builder. Rerun this analysis under the new 4-6-leg, floor-only builder before any promotion decision — the tradeoff shape may no longer be the same.

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

### **19. Live-Data Performance Recheck of the New Builder (New, Session 18, High Priority)**
Once roughly a week of production data exists under the floor-only/4-6-leg logic, run the same style of pre/post comparison used for the Session 16 slot-gate recheck — parlay win rate, leg-count distribution, void rate — against the old builder's equivalent window.

### **20. SO/over Pool-Composition Softening (New, Session 18, Medium Priority)**
The composite score's K/9-rank differentiation between selected and non-selected SO/over legs nearly vanished coincident with the July 2 slot-gate fix. Unclear if this is a real pool-composition shift or noise from ~1 week of data. Recheck with more volume.

### **21. Validate Batter Stat Ranges for Shadow Scorer (New, Session 19, High Priority)**
The OBP/BA/K%/BB% midpoints and half-ranges in `enriched_scorer.py` use league-average estimates (`_OBP_MID=0.350, _OBP_HALF=0.070` etc.). After the first few shadow runs, pull actual p5/p95 from the computed batter stats in the shadow run logs and update these constants to match the real range of this leg pool — the same methodology used to derive ERA/WHIP/K9 ranges from `mlb_scored_legs` data.

### **22. Shadow vs. Production Win Rate Comparison (New, Session 19, Medium Priority)**
No backtest — historical window too thin and was actively misleading in analysis during Session 19. Instead: run shadow for 3-4 weeks, then compare shadow vs. production win rate and edge (WR vs. odds-implied probability) using existing comparison queries in `SUPABASE_SCHEMA_REFERENCE.md`.

---

**Architecture Status:** ✅ STABLE
**Last Major Change:** July 10, 2026 — scratch handler rewritten with time-gated reduce path; shadow scorer rebuilt with linear-scale matchup signals; manual dashboard added coverage_overall column
**Next Architecture Review:** Validate batter stat ranges after first shadow runs / shadow vs. production comparison after ~3-4 weeks / TB/under construction-strategy rerun under new builder (before any promotion decision)
