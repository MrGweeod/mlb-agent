# MLB Parlay Agent — Architecture Decisions
**Last Updated:** June 15, 2026 (Session 12 — Weekend Review, Shadow Audit, Pipeline Fixes)

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
18. [Lessons Learned](#lessons-learned)
19. [Future Considerations](#future-considerations)

---

## Core Philosophy

### **Decision: Optimize for Validated Edge, Not Feature Complexity**

The system exists to find props where historical coverage rate predicts actual outcomes, and combine them into parlays with positive expected value. Every design decision should be evaluated against this goal.

**Validated as of June 2026:**
- `SO over 0.5` (hitter) at 65%+ coverage: genuine +2.8pp edge above breakeven confirmed on clean June 1-10 data. June 12-14 clean window: 87.1% win rate (31 legs)
- Same-game correlation: 20.0% parlay win rate with same-game pair vs 12.6% without — +7.4pp confirmed
- Park factor: 30-point win rate spread between pitcher parks (40%) and hitter parks (70%)

**Revised June 12, 2026:**
- `hits over 0.5` at 65%+ coverage: **at or below breakeven** on clean June data (59.9% win rate vs 66.9% breakeven at -202 odds). June 12-14: 66.9% (145 legs) — above breakeven but CLV data needed for final verdict.
- Coverage-derived EV does not discriminate within the validated production leg pool — EV-sort provides +0.0pp improvement on clean 533-leg pool.

---

## Scoring System Evolution

### **Phase 0: ML Model (April–May 2026) — ABANDONED**
GradientBoostingClassifier, 77K samples, direction feature at 77% importance. Score-outcome correlation was inverted. Parlay win rate: 7.6%.

### **Phase 1: Simple Coverage-Based Scoring (May 20, 2026) — CURRENT PRODUCTION**

```python
score = coverage_overall          # always the base
     + coverage_vs_hand_delta     # ±3 max (30% weight of delta from overall)
     + consistency_adjustment     # gap-based ±6/±4/±2/+2/+1
     + era_adjustment             # ±5 for hits props (raw pitcher_era — pending revalidation)
     + whip_rank_adjustment       # ±5 for hits props (pitcher_whip_rank)
     + k9_rank_adjustment         # ±5 for SO props (pitcher_k9_rank)
     + lineup_stability           # -5 if lineup_consistency < 0.50
     + slot_gate_penalty          # -8 if batting_order known + outside BATTING_ORDER_FAVORABLE range
```

### **Key Scoring Decision: Slot Gate as Soft Penalty (June 12, 2026)**

Batting order data captured via lineup confirmation layer. Known unfavorable slot applies −8 scoring penalty, not hard exclusion. Absence of data never penalizes. Backtest showed hypothesis contradicted by current data (slots 6-9 won at 66.7% vs slots 1-5 at 61.2%) — keep annotation, don't implement production gate from contradicted hypothesis.

---

## Prop Selection — Data-Driven Whitelist

### **Decision: Strict Whitelist Based on Outcome Analysis**

Only props showing edge above breakeven with a predictive coverage signal are included.

**Current production whitelist:**
```python
ALLOWED_PROPS = {
    ("hits",       "over",  0.5),
    ("hits",       "under", 0.5),
    ("strikeouts", "over",  0.5),  # hitter only
    ("totalBases", "under", 1.5),  # shadow validation only — excluded from production parlays
}
```

**Removed/deferred props:**

| Prop | Reason |
|---|---|
| `rbi under 0.5` | Flat signal — book prices edge away |
| Pitcher SO (all) | Zero pitcher legs in DB — only batter SO scored |
| `walks`, `homeRuns`, `stolenBases` | Insufficient sample / negative edge |
| Strikeouts under | Not available on DraftKings |
| TB over | No edge at any coverage level — excluded permanently June 9 |

**Decision: TB Under — Shadow Validation Continues (Session 12 update)**

TB under shadow data (June 4–14): 56.1% win rate in scored legs. Shadow parlays containing TB/under win at 52.6% (103 appearances). Every resolved shadow parlay contained at least one TB/under leg — it dominates shadow construction. Do not promote until shadow parlay win rate ≥ production without TB/under contribution, and WHIP tier spread ≥10pp confirmed (~late June).

---

## Coverage Gating Architecture

### **Decision: Direction-Aware Two-Gate System (June 8, 2026)**

```python
if direction == "over" and coverage_overall < 65.0: continue
if direction == "under" and coverage_overall < 40.0: continue
```

### **Decision: 85%+ Coverage Is a Trap — Ceiling Pending**

Clean training data confirmed win rates collapse above 84%: hits over drops from 71.8% (75-84% bucket) to 31.5% (85%+). Gate fix (`coverage_overall <= 84%`) confirmed needed but not yet implemented. **Quick win for next session.**

---

## Parlay Construction Evolution

### **Phase 1: ML-based (April–May 2026) — ABANDONED**
### **Phase 2: Anchor/Swing Two-Pool (May 28, 2026) — REPLACED**
### **Phase 3: Single Flat Pool 4-Leg +400–+700 (June 1, 2026)**
### **Phase 3.1: Score-Sort + MAX_CANDIDATES 50 (June 5, 2026)**
### **Phase 3.2: Direction-Aware Score Floor (June 8, 2026)**
### **Phase 3.3: TB Under Excluded from Production Parlays (June 9, 2026)**
### **Phase 3.4: Slot Gate Soft Penalty Added (June 12, 2026)**
### **Phase 3.5: Cross-Run 2x Player Cap (June 15, 2026) — CURRENT**

**Decision: EV-Sort Discarded by Backtest (June 12, 2026)**

EV-sort tested on clean 533-leg production pool: +0.0pp leg improvement, -6.2pp parlay win rate. Pool thinning drops parlays from 191 to 49. Revisit only after pool expands or CLV provides a better edge signal.

**Decision: Slot Gate Discarded by Backtest (June 12, 2026)**

Slot gate tested on clean pool: -9.7pp parlay win rate. Batting order hypothesis contradicted by current data. Slot annotation continues as free data; production gate not implemented.

**Decision: Backtest Must Use Whitelist-Filtered Pool (June 12, 2026)**

First backtest run used 960-leg pool vs correct 533-leg production pool. EV-sort appeared to show +6.3pp leg improvement — entirely from filtering bad props, not from reranking good ones. All future backtests must apply the production whitelist filter before running variants.

---

## Player Diversity — Cross-Run Cap

### **Decision: Replace Manual-Only Exclusion with Cross-Run 2x Cap (June 15, 2026)**

**Prior system:** Manual regen excluded players from the most recent single batch. Automated runs (9AM, midday, evening) had zero cross-run diversification.

**Problem observed:** June 12 — McGonigle appeared in 5 separate parlays, Hoerner in 5, Torres in 4. All had bad games. Multiple parlays sank simultaneously. The system's natural tendency to gravitate toward highest-scored players meant the same names appeared across every run of the day.

**New system:** Two constraints working together:
1. **Intra-run:** 1 player per parlay (existing constraint — unchanged)
2. **Cross-run:** Max 2 total parlay appearances per player per day. Once a player has appeared in 2 parlays today (across any combination of runs), they are removed from the selection pool for all future runs that day.

**Implementation:** Before each build, queries `mlb_parlay_legs_v2` for today's prior appearances per player (`HAVING COUNT(*) >= 2`). Applies to all sources — manual, auto_9am, auto_12pm, auto_530pm.

**Fallback:** If cap leaves fewer than 20 legs, restores full pool with `[player_cap] Pool too thin` warning log. Prevents construction failure on thin slates.

**Trade-off acknowledged:** Evening run may select slightly lower-scored players after top names are capped. Diversification benefit (correlated losses prevented) outweighs small scoring quality reduction.

---

## Odds Cap Decision

### **Decision: -250 Hard Cap Per Leg (June 1, 2026)**

At -250, breakeven is 71.4%. Edge exists for validated props at high coverage. At -300, breakeven is 75.0% — edge disappears.

---

## Coverage Signal Architecture

### **Decision: `coverage_vs_hand` as Delta, Not Base (June 5, 2026)**

`coverage_overall` = gate and base. `coverage_vs_hand` = delta at 30% weight, ±3 cap.

### **Decision: coverage_vs_hand Falls Back to coverage_overall When None (June 9, 2026)**

---

## Pitcher Signal Pipeline

### **Decision: Per-Start IP Filter (June 5, 2026)**
3+ starts, 3.0+ IP/start. Pool: ~20-25 → 192 qualified starters.

### **Decision: WHIP Rank Signal for Hits Props (June 8, 2026)**

Shadow data (June 12-14): WHIP completely flat across all buckets for hits/over, hits/under, and SO/over. Signal may need to be removed from hits scoring pending more clean data with corrected rank normalization.

### **Decision: K9 Rank Signal for Batter Strikeout Props**

Shadow data (June 12-14): K9 for SO/over shows weak-K pitchers producing 52.2% win rate vs above-avg K at 66.7% — directionally correct. Signal was previously broken by hardcoded 30-pitcher scale; first clean read will be available June 16+ after dynamic normalization fix.

### **Decision: Prop-Specific Pitcher Signal Routing in Shadow Scorer (June 9, 2026)**

| Prop | Signals | Cap |
|---|---|---|
| `totalBases under 1.5` | WHIP rank only | ±5 |
| `strikeouts over 0.5` | K/9 rank only | ±5 |
| `hits over/under 0.5` | ERA + K/9 + WHIP | ±2 each (±6 max) |

### **Decision: Dynamic Rank Normalization Required (Session 11 + Session 12)**

All rank-based adjustments must use the dynamic pool size from `len(pitcher_ranks)`, not a hardcoded value.

**History of this bug:**
- Session 11: Fixed in `pitcher_vulnerability()` (stack bonus function) — applied `(rank - 1) / (max_rank - 1)`
- Session 12: Found same bug in three separate paths inside `_calculate_enriched_score()` — all using hardcoded midpoint of 15.5 (assumes 30 pitchers). Fixed all four paths with `midpoint = (n + 1) / 2.0`.

**Rule:** Any code that normalizes pitcher ranks must compute pool size at runtime from the actual `pitcher_ranks` dict. Hardcoding 30, 15.5, 29, or any other fixed value is wrong.

### **Decision: Pitcher Vulnerability Composite Score (June 13, 2026 — LIVE)**

For offense stack detection in shadow pipeline, `pitcher_vulnerability()` aggregates ERA rank (inverted), K/9 rank (inverted), WHIP rank — normalized 0-1 using dynamic max-rank. Threshold `>= 0.60` identifies bottom-40% pitchers as qualifying stack targets. Falls back to raw `pitcher_era` when ranks NULL.

---

## Shadow Pipeline Strategy

### **Decision: Shadow Before Promoting**

Significant scoring changes run in shadow for 5-7 days before production promotion.

### **Decision: Offense Stack Bonus — Shadow Only (June 13, 2026 — LIVE)**

Same-game correlation confirmed empirically (20.0% vs 12.6% parlay win rate Q3 diagnostic). Stack bonus is a post-scoring pass in `run_enriched_pipeline.py`. Shadow-only until promotion criteria met:
- Stack legs win ≥5pp more than non-stack legs
- Shadow parlay win rate ≥ production parlay win rate
- ≥2 qualifying stacks per day average

Current read (11 legs): 72.7% vs 55.3% — direction confirmed, sample too small.

### **Decision: mlb_scored_legs_enriched as Shadow Source of Truth (June 15, 2026)**

Shadow signal validation should use `mlb_scored_legs_enriched.result` (individual leg outcomes), not `mlb_parlay_legs_enriched.outcome` (parlay-level outcomes). Parlay outcomes are affected by construction — one bad leg sinks the whole parlay. Scored leg outcomes evaluate signals at the individual leg level.

**Note:** `mlb_scored_legs_enriched.result` was NULL for June 4–14 due to a missing mirror step in the resolver. Fixed June 15 with 11-day backfill. All signal validation prior to this session used parlay leg outcomes only — this is a less granular but still valid signal for win rates. Going forward, use scored legs for signal analysis.

### **Decision: Shadow Clean Comparison Clock**

| Event | Date | Notes |
|-------|------|-------|
| K/9 direction fix | June 13 | Prior SO over shadow legs were anti-selected |
| Rank normalization fix | June 16 | First clean day with correct pitcher signal scaling |

Use June 16+ data for all signal validation going forward.

---

## Enriched Scoring Signals

### **Signal 1: Blended ERA Rank (Active — scale corrected June 15)**
Season ERA rank × 0.5 + last-3-start ERA rank × 0.5. Dynamic normalization now correct. First clean read June 16+.

**Known issue:** ERA rank nearly all landing in elite (1-50) bucket in June 12-14 data — likely due to hardcoded scale. Re-evaluate with June 16+ data after fix.

### **Signal 2: Opponent-Specific Coverage (Active — thin data)**
Batter hit rate vs tonight's specific opponent. ~20-35% population rate early season. Requires min 3 games vs opponent.

### **Signal 3: Ballpark Factor (Active — validated)**
30-row static table. 30-point win rate spread confirmed. Correctly persisted.

### **Signal 4: Prop-Specific Pitcher Routing (Active — corrected June 15)**
ERA+K9+WHIP→hits, K9→SO, WHIP→TB. All rank normalization paths now use dynamic pool size.

**WHIP signal status:** Completely flat across all buckets for hits props in June 12-14 data. Pending re-evaluation with June 16+ clean data. May need to be removed from hits scoring if flat result persists.

**K/9 direction for hits/over:** Counterintuitive correlation found — weak K pitchers produce lower hits/over win rate (40%) than elite K pitchers (76.7%). Scale was broken before June 16. Re-evaluate direction after clean data accumulates.

### **Signal 5: Offense Stack Bonus (Active — June 13, 2026)**
Post-scoring pass. `STACK_BONUS = 4.0` points for legs in qualifying offense stack. `STACK_VULNERABILITY_THRESHOLD = 0.60`. `STACK_ELIGIBLE_PROPS = {("hits", "over")}`. Shadow only — pending promotion evaluation after June 20.

---

## Lineup Confirmation Layer

### **Decision: Event-Driven Scheduler, Database-Backed (June 12, 2026)**

Fixed 3×/day pipeline cannot catch lineups posting after 5:30 PM. Per-game-group checks fired at `game_start_time − 45 minutes`. Scheduler persisted to `mlb_pending_lineup_checks` (restart-safe). Drain: 1-minute async loop in `server.py`.

### **Decision: Annotation-Only, No Hard Blocking (June 12, 2026)**

Four states: `MISSING_LINEUP_CONFIRMATION`, `LINEUP_CONFIRMED`, `BATTING_ORDER_OUT_OF_RANGE`, `SCRATCHED`. Pipeline never blocked on unconfirmed lineups.

### **Decision: CONFIRMED_LINEUP_RESOLUTION Run Type (June 12, 2026)**

When selected player confirmed SCRATCHED or OUT_OF_RANGE, affected parlay voided and rebuilt from upcoming-games-only replacement pool. Scratched 7 PM player can never be replaced by a 1 PM leg whose game is over.

### **Decision: T-45 Offset, Configurable (June 12, 2026)**

`LINEUP_CHECK_OFFSET_MINUTES = 45`. Configurable because actual lineup posting times at T-45 are unvalidated — flip `LINEUP_CHECK_SECOND_PASS = True` for T-15 confirmation pass if lineups not posted at T-45.

### **Decision: Lineup Scheduler as Separate Module (June 15, 2026)**

`lineup_scheduler.py` was always referenced as a separate module in `src/pipelines/` but was never committed. The `try/except` wrapper around `log_slate_start_times()` swallowed the ImportError silently — correct non-fatal behavior for a non-critical layer, but made the failure invisible for weeks.

**Rule established:** Any new module added to `src/pipelines/` must be verified in git status before considering it deployed. `git show HEAD:src/pipelines/<filename>.py` is the correct verification.

---

## CLV Tracking Layer

### **Decision: Scheduled at T-1, Reusing Lineup Scheduler (June 12, 2026)**

CLV snapshot fires at `game_start_time − CLV_OFFSET_MINUTES` (default 1). Reuses `mlb_pending_lineup_checks` with `check_type = 'clv'`. Same drain, same atomic-claim pattern, same restart-safety.

### **Decision: All Scored Legs, Not Just Parlay Legs (June 12, 2026)**

Full pool captured for recalibration and signal validation. CLV is forward-only — clock started June 15 (first working night after lineup_scheduler.py deployed). First meaningful read ~June 26.

### **Decision: Option B — Odds + Closing Odds Only (June 12, 2026)**

`odds` = selection-time. `closing_odds` + `closing_odds_captured_at` added. CLV = implied_prob(closing_odds) − implied_prob(odds). Positive = beat the close = real edge.

---

## Backtest Harness

### **Decision: Read-Only Replay Against Real History (June 12, 2026)**

`scripts/run_backtest.py` replays June 1-10 against variants using real recorded `result` values. No future-looking. Baseline = real recorded parlay outcomes.

### **Decision: Always Whitelist-Filter Before Running Variants (June 12, 2026)**

Backtest must filter scored-leg pool to production whitelist before computing variants.

### **Decision: Report Confidence Intervals Explicitly (June 12, 2026)**

With ~191 parlays, CI ≈ ±6.6pp. A change must exceed the CI to be considered signal. Leg-level claims (533 legs) carry ±4pp CI.

---

## Outcome Resolution

### **Decision: Fail-Safe EEP with Explicit Presence Check (June 1, 2026)**

### **Decision: Shadow Table Resolution Parity (June 5, 2026)**

### **Decision: Mirror Enriched Scored Leg Results (June 15, 2026)**

`outcome_resolver.py` must update both `mlb_parlay_legs_enriched.outcome` AND `mlb_scored_legs_enriched.result` in the same resolution pass. Prior code only updated parlay leg outcomes, leaving scored leg results permanently NULL. The scored leg table is the correct source of truth for signal validation (individual leg outcomes, not parlay-level outcomes).

---

## Database Design

### **Critical Type Rules**

- `mlb_scored_legs.run_date`: TEXT — string comparisons only
- `mlb_scored_legs.odds`: TEXT — cast `::numeric` for math
- `mlb_scored_legs.closing_odds`: TEXT — same as odds, cast `::numeric` for CLV math
- `mlb_scored_legs.player_id`: TEXT — cast `int()` at API boundary
- `mlb_parlay_legs_v2.player_id`: INTEGER
- `mlb_parlay_recommendations_v2.run_date`: DATE — no cast needed
- `mlb_training_data.result`: `'hit'/'miss'/'void'` — different from parlay tables' `'won'/'lost'`
- `mlb_scored_legs_enriched.id`: NULL for all rows — use natural key `(run_date, odd_id)` for all writes
- Never `ROUND()` — use `::numeric(p,s)`
- `RealDictCursor` everywhere — `row["col"]`, never `row[0]`

### **game_pks Column Format (June 15, 2026)**

`mlb_pending_lineup_checks.game_pks` is a TEXT column that stores a PostgreSQL array literal: `{822724,823371}`. Must be serialized as `"{" + ",".join(str(pk) for pk in game_pks) + "}"` — NOT as a comma-separated string.

### **New Columns Added Session 12**
No schema changes this session — all fixes were code-only.

### **New Columns Added Session 11**
`mlb_scored_legs_enriched`: `stack_bonus_applied` (boolean, default false), `pitcher_vulnerability` (numeric, 0.0–1.0)

### **New Columns Added Session 10**
`mlb_scored_legs`: `batting_order`, `lineup_check_status`, `lineup_checked_at`, `closing_odds`, `closing_odds_captured_at`
`mlb_parlay_legs_v2`: `batting_order`, `lineup_check_status`, `lineup_checked_at`
`mlb_parlay_recommendations_v2`: `superseded_by_batch_id`, `superseded_reason`
`mlb_pending_lineup_checks`: `check_type` (text, default 'lineup')

New table: `mlb_pending_lineup_checks` (id, run_date, start_time_group, game_pks, trigger_at, offset_minutes, pass_number, check_type, status, fired_at, completed_at, result_note, created_at)

### **Training Data Schema (Post Session 9)**
`coverage_overall`, `coverage_recent_10`, `pitcher_era_rank`, `pitcher_k9_rank`, `pitcher_whip_rank`, `whip_adj`, `k9_adj`, `era_adj` all now persisted.

### **Clean Training Data Cutoff: April 27, 2026**
Coverage calculation was inverted before April 27. All signal validation must use `game_date >= '2026-04-27'`.

### **Anti-Pattern: ORDER BY before UNION ALL**
```sql
-- WRONG
SELECT ... ORDER BY x UNION ALL SELECT ... ORDER BY x;
-- CORRECT
SELECT ... UNION ALL SELECT ... ORDER BY x;
```

---

## Pipeline Architecture

### **3× Daily + Shadow After Every Run + Event-Driven Lineup/CLV Checks**
- 9:00 AM ET — Resolution + fresh parlays + schedule lineup/CLV checks (shadow runs after)
- 12:00 PM ET — Midday refresh (shadow runs after)
- 5:30 PM ET — Evening refresh (shadow runs after)
- Manual Regenerate — cross-run cap applied, shadow runs after
- **T-45 per game group** — lineup annotation check
- **T-1 per game group** — CLV closing odds snapshot
- **On SCRATCHED/OUT_OF_RANGE** — CONFIRMED_LINEUP_RESOLUTION rebuild

---

## Lessons Learned

1. **Coverage alone is not edge.** The book also knows historical coverage rates. Edge exists only where predicted win probability exceeds the book's implied probability.
2. **Flat coverage signals mean cut, not raise the floor.**
3. **Pool size determines parlay structure.** Any filtering on a 533-leg pool drops parlays from 191 to 43-49. The bottleneck is pool depth, not selection quality.
4. **Sort order determines parlay quality, not just efficiency.**
5. **Candidate limit determines search depth.** MAX_CANDIDATES=15 caused B&B to stop too early.
6. **IP thresholds can silently exclude the best data.**
7. **Function names can mislead.** `_attach_pitcher_rank_signals()` only attached to pitcher prop legs initially.
8. **Shadow pipeline must have outcome resolution — at the scored leg level, not just parlay level.**
9. **Resolution bugs compound quickly.**
10. **stat-name-based routing is fragile.**
11. **API defaults can silently corrupt logic.**
12. **High-score player saturation kills manual parlays.**
13. **Cross-run diversification matters as much as intra-run diversity.** The same player appearing in 5 automated parlays is the same failure mode as the same player appearing in 5 legs of a single parlay.
14. **A gate that works for overs can be structurally impossible for unders.**
15. **Score scales must be comparable before competing in the same pool.**
16. **Rank scale bugs are invisible without spot-checking values.** The 30-pitcher hardcoded scale bug existed in two separate functions — `pitcher_vulnerability()` (fixed Session 11) and `_calculate_enriched_score()` (fixed Session 12). Always verify that rank normalization uses `len(pitcher_ranks)` at runtime.
17. **Backfill scripts should build lookup maps, not make per-leg API calls.**
18. **API abbreviations drift from internal tables.** Always maintain `ABR_ALIASES`.
19. **Training data schema must match scoring schema.**
20. **Corrupted training data must be date-gated before analysis.** April 27 cutoff is confirmed.
21. **Deprecated write paths cause silent pipeline failures.**
22. **RealDictCursor rows require string keys, not integer indexes.**
23. **Stacking pitcher signals across all prop types causes cancellation.**
24. **85%+ coverage is a trap.**
25. **A broken feature that never ran is not the same as a working feature.** lineup_scheduler.py was wired into main.py and referenced correctly, but the file didn't exist on Railway. The try/except made it silent. Verify with `git show HEAD:src/pipelines/<file>.py`.
26. **Backtest pool contamination produces confidently wrong conclusions.** Running variants against a pool wider than production makes filtering appear to improve leg quality when it's actually filtering out props the production system never used.
27. **EV-sort requires a signal that discriminates within the validated pool.** coverage_overall-derived EV does not rank legs differently within an already-validated pool.
28. **Same-game correlation is empirically net positive for all-or-nothing bets.** Q3 diagnostic confirmed: same-game parlays win 20.0% vs 12.6% for distinct-game.
29. **Multi-loss clustering is expected math, not a signal of system failure.** At 65% per-leg, conditional on a 4-leg parlay losing, ~53% of losses have 2+ losing legs.
30. **Database-backed schedulers are worth the extra table.** An in-memory APScheduler job is one Railway restart away from disappearing. Postgres-backed drain with 1-minute poll makes the scheduler restart-proof.
31. **Verify parsers against real API responses before trusting them.** Lineup hydrate parser explicitly verified against real `battingOrder` response (19/19 slot match).
32. **The hypothesis you're testing must match the data you're testing it on.** Slot gate hypothesis contradicted by current data — keep annotation, don't gate.
33. **The same bug can exist in two separate functions.** The 30-pitcher rank normalization bug was fixed in `pitcher_vulnerability()` in Session 11 but missed in `_calculate_enriched_score()`. When fixing a class of bug, search all occurrences of the pattern before closing the fix.
34. **Backfill scripts that go through application logic may fail on already-resolved data.** The first enriched scored legs backfill tried calling `resolve_enriched_parlays()` — which found no pending legs and exited. Direct SQL (`UPDATE ... FROM` JOIN) bypasses the application-level state machine entirely and is the correct approach for data repair.
35. **Shadow scored legs and shadow parlay legs are different sources of truth.** Parlay leg outcomes (`mlb_parlay_legs_enriched.outcome`) are valid for win rate analysis but conflate signal quality with construction quality. Scored leg outcomes (`mlb_scored_legs_enriched.result`) isolate signal quality at the individual leg level. Both are needed; use the right one for the right question.

---

## Future Considerations

### **1. Add 84% Coverage Ceiling (Quick Win — Highest Priority)**
One-line fix in `main.py`. Trap confirmed by training data. Not yet implemented despite being flagged since Session 9.

### **2. K/9 Direction for hits/over — Reassess After June 20**
Shadow data shows weak K pitchers produce 40% hits/over win rate vs elite K at 76.7%. Counterintuitive — likely explained by strong K pitchers facing tougher lineups with higher coverage rates. Two options: (a) remove K/9 from hits scoring entirely, or (b) invert direction. Evaluate after June 16+ clean data accumulates.

### **3. WHIP Signal for hits/over — Remove If Still Flat**
WHIP rank completely flat across all buckets in June 12-14 data. Re-evaluate with June 16+ data. If still flat, remove from hits scoring — noise is worse than absence.

### **4. CLV Signal Read (~June 26)**
First meaningful read on whether SO/over and hits/over beat the close. Expected: SO/over positive CLV, hits/over near zero. Will either confirm hits/over removal from whitelist or provide evidence to keep it.

### **5. Stack Bonus Promotion Decision (After June 20)**
Current: 72.7% vs 55.3% (11 legs). Need 7 clean days and all three promotion criteria met.

### **6. TB Under Promotion Decision (Late June)**
Shadow: 56.1% win rate in scored legs, 52.6% in parlays. Current data does not support promotion. WHIP signal validation ongoing (~June 26 read). Needs elite WHIP tier winning ≥5pp above weak tier.

### **7. Pool Expansion Strategy**
Backtest confirmed: filtering a 533-leg pool causes construction collapse. Real improvement requires pool expansion. Priority order: (1) TB under after WHIP validation, (2) pitcher SO market integration, (3) additional validated hitter props.

### **8. Pitcher SO Market Integration (Phase 2)**
Pitcher strikeout total props require new SGO market parameter + pitcher coverage logic. Not a whitelist addition; a new data integration.

### **9. Hits/Over Reassessment After CLV**
Current: 66.9% win rate June 12-14 (above breakeven at -202), but 59.9% on June 1-10 clean window (below breakeven). CLV will provide a cleaner verdict. If hits/over CLV is consistently negative, consider removing from production whitelist.

### **10. Learning Loop**
Once 500+ resolved legs exist under current scoring, regression on signals vs outcomes. Recalibrate weights from data.

---

**Architecture Status:** ✅ STABLE
**Last Major Change:** June 15, 2026 (Cross-run player cap, enriched resolver fix, rank normalization fix)
**Next Architecture Review:** After June 20 shadow data review (K/9 direction, WHIP signal, stack bonus promotion) and CLV first read (~June 26)
