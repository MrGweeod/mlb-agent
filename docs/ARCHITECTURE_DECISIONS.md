# MLB Parlay Agent — Architecture Decisions
**Last Updated:** June 16, 2026 (Session 13 — CLV Activation, Shadow Resolution Fix, Pitcher Signal Overhaul, Player Cap)

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

# Production parlays (TB/under excluded):
production_legs = [l for l in qualifying_legs if l.get("stat") != "totalBases"]
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
### **Phase 3.5: Cross-Run 2x Player Cap Production (June 15, 2026)**
### **Phase 3.6: Cross-Run 2x Player Cap Shadow (June 16, 2026) — CURRENT**

**Decision: EV-Sort Discarded by Backtest (June 12, 2026)**

---

## Player Diversity — Cross-Run Cap

### **Decision: 2x Daily Appearance Cap Applied to Both Pipelines (Session 12–13)**

Two separate diversity constraints operate simultaneously:

1. **Intra-batch** (`parlay_builder.py`): Each player appears in at most 1 parlay per build. Enforced via `used_players` set inside `build_parlays()`.

2. **Cross-run** (`main.py` and `run_enriched_pipeline.py`): Each player appears in at most 2 total parlays per calendar day across all sources. Before each build, query `mlb_parlay_legs_v2` (production) or `mlb_parlay_legs_enriched` (shadow) to count today's prior appearances. Players at ≥2 removed from pool before `build_parlays()`.

**Motivation:** June 12 — McGonigle (5 parlays), Hoerner (5), Torres (4) all had bad games simultaneously. Without cross-run cap, a single player's bad game kills multiple parlays from multiple automated runs.

**Known failure mode (discovered June 16):** After 5+ runs, if the cross-run cap removes enough overs that only unders remain in the pool, the 4-leg +400–+700 target becomes mathematically impossible. The fallback threshold (`< 20 legs`) is insufficiently specific — it should check available over legs, not just total legs. **Fix pending next session.**

---

## Odds Cap Decision

**Hard cap: -250 per leg.** Above -250 juice means the book's implied probability is so high that even validated coverage signals can't overcome the vig. A leg at -300 needs 75%+ win rate just to be EV neutral.

---

## Coverage Signal Architecture

Coverage signal is derived from rolling historical outcomes per player per prop type. `coverage_overall` = wins / (wins + losses) over all available history. `coverage_recent_10` = same for last 10 resolved legs. The base signal for all scoring.

**Direction awareness:** Under coverage is structurally lower than over coverage because unders require the player to underperform. Floor gates differ accordingly (40% vs 65%).

---

## Pitcher Signal Pipeline

### **Production (simple_scorer.py)**
- hits props: `whip_rank_adjustment` ±5 (pitcher WHIP rank vs qualified starters pool)
- SO over: `k9_rank_adjustment` ±5 (pitcher K/9 rank vs qualified starters pool)
- Rank normalization: dynamic from current qualified starter pool size

### **Shadow (enriched_scorer.py) — Session 13 Overhaul**

Prop-specific routing with corrected directions:

| Prop | Signal | Direction | Scale |
|---|---|---|---|
| hits/over | Pitcher vulnerability penalty | Low vuln = bad for hits over | -6 if <0.25, -10 if <0.15 |
| hits/under | None | Removed — no signal | — |
| strikeouts/over | K/9 rank | Elite K (rank 1) = boost SO/over | ±5 |
| totalBases/over | WHIP rank | High WHIP = boost TB/over | ±5 |
| totalBases/under | WHIP rank | Low WHIP = boost TB/under | ±5 |

**Key decision: SO/over K/9 direction corrected (Session 13)**
A pitcher with elite K/9 (rank 1) means batters are MORE likely to strikeout — facing an elite strikeout pitcher is GOOD for SO/over bets. The original formula was inverted. `(midpoint - k9_rank)` replaces `(k9_rank - midpoint)`.

**Key decision: hits/over vulnerability penalty (Session 13)**
One day of clean data (June 15) showed 0/3 win rate for hits/over against pitchers with vulnerability <0.25 (Wheeler ERA 2.22, Burns ERA 2.14). These legs appeared in 6 shadow parlays — all lost. Soft penalty applied, not hard exclusion. Thresholds subject to recalibration after June 22.

**Key decision: hits/under pitcher signal removed (Session 13)**
The inverted ERA+K9+WHIP composite for hits/under had no consistent predictive signal in June 15 data. Removed entirely rather than risk noise cancellation.

---

## Shadow Pipeline Strategy

### **Decision: Shadow Pipeline as Signal Validation Layer**

The shadow pipeline runs after every production pipeline. It scores all props (including TB/under) using the enriched scorer with pitcher signals. Parlays are built and tracked but not shown in Discord. Purpose: validate new signals before promoting to production.

**Resolution architecture (Session 13 correction):**
Shadow scored leg resolution now runs via `resolve_all_enriched_legs()` in the daily morning pipeline — same box score path as production's `resolve_all_legs()`. Previously, resolution only flowed through the parlay leg mirror (~20 legs/day), leaving ~140 legs/day permanently null. This made signal validation queries across the full pool impossible.

**Clean data cutoffs:**
- Shadow pitcher signals: Valid from June 15 only (first day with correct dynamic rank normalization in `_calculate_enriched_score()`)
- Production coverage signal: Valid from April 27 (coverage inversion corrected)

---

## Enriched Scoring Signals

All signals in `enriched_scorer.py` use dynamic pool normalization:
```python
n = max(len(pitcher_ranks), 2)
midpoint = (n + 1) / 2.0
# Signal: (rank - midpoint) / (midpoint - 1) * scale
```

This ensures signal is proportional and centered regardless of pitcher pool size (currently 205 qualified starters as of June 16, 2026).

---

## Lineup Confirmation Layer

Event-driven annotation system. After 9AM pipeline, rows are written to `mlb_pending_lineup_checks` for each start-time group at T-45 and T-15. Drain cron polls every minute. On trigger, fetches live lineups via statsapi hydrate. Annotates each parlay leg with `batting_order` and `lineup_check_status` (CONFIRMED/OUT_OF_RANGE/SCRATCHED/MISSING). If SCRATCHED or OUT_OF_RANGE detected, triggers CONFIRMED_LINEUP_RESOLUTION rebuild with upstream-only replacement pool.

First confirmed live annotation: June 15, 2026.

---

## CLV Tracking Layer

After 9AM pipeline, CLV rows are scheduled at T-1 for each start-time group. On trigger, `clv_tracker.py` re-fetches SGO odds and writes `closing_odds` + `closing_odds_captured_at` to `mlb_scored_legs` for matched legs. First live capture: June 16, 2026. First meaningful read: ~June 26.

**Deployment note:** `clv_tracker.py` was committed June 16 (Session 13) after existing only locally since Session 10. Always verify Railway has the file: `git show HEAD:src/apis/clv_tracker.py`.

---

## Backtest Harness

Variant testing on 533-leg clean June 1-10 production pool:

| Variant | Leg Δ | Parlay Δ | Verdict |
|---|---|---|---|
| EV-sort | +0.0pp | -6.2pp | Discarded |
| Slot gate | -0.0pp | -9.7pp | Discarded |
| Combined | -0.1pp | -8.6pp | Discarded |

Coverage-derived EV does not discriminate within an already-validated pool. Filtering on a 533-leg pool causes construction collapse (191 parlays → 43).

---

## Outcome Resolution

### **Production:** `resolve_all_legs(run_date)` — box score path, one API call per game. Primary path. Runs every 9AM pipeline.

### **Shadow (Session 13):** `resolve_all_enriched_legs(run_date)` — same box score path targeting `mlb_scored_legs_enriched`. Natural key `(run_date, odd_id)` — never `id` (NULL for all rows). Runs every 9AM pipeline immediately after `resolve_all_legs()`.

### **Shadow parlay mirror:** `resolve_enriched_parlays(run_date)` — syncs outcomes from `mlb_parlay_legs_enriched` back to `mlb_scored_legs_enriched` for parlay legs specifically. Direction filter required: `AND direction = %s` in both the lookup and UPDATE (Session 13 fix).

---

## Database Design

### **Natural Keys vs Surrogate Keys**
`mlb_scored_legs_enriched.id` is NULL for all rows. All updates must use natural key `(run_date, odd_id)`. Never reference `id` in UPDATE statements targeting this table.

### **PostgreSQL Conventions**
- Never `ROUND()` — use `::numeric(p,s)`
- `RealDictCursor` everywhere — `row["col"]`, never `row[0]`
- `run_date` is TEXT in `mlb_scored_legs_enriched` — filter as `run_date = '2026-06-16'`

### **game_pks Column Format**
`mlb_pending_lineup_checks.game_pks` is a TEXT column storing a PostgreSQL array literal: `{822724,823371}`. Must be serialized as `"{" + ",".join(str(pk) for pk in game_pks) + "}"`.

### **New Columns Added Session 13**
No schema changes this session — all fixes were code-only.

### **New Columns Added Session 12**
No schema changes.

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

### **Clean Shadow Signal Cutoff: June 15, 2026**
Dynamic rank normalization deployed June 15. Shadow pitcher vulnerability scores are only valid from June 15 onward. Do not run vulnerability bucket analysis on pre-June 15 shadow data.

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
25. **A broken feature that never ran is not the same as a working feature.** `lineup_scheduler.py` and `clv_tracker.py` were both wired into `main.py` and referenced correctly, but neither file existed on Railway. The try/except made them silent. Always verify with `git show HEAD:src/path/to/file.py`.
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
36. **Direction filters in resolution queries are not optional.** A join on `(player_name, stat, run_date)` without `direction` will silently return the wrong result for any player with both an over and under leg scored on the same day. `LIMIT 1` is not a safety net — it picks arbitrarily.
37. **Prop-specific pitcher signals must account for which direction improves outcomes.** Facing an elite K/9 pitcher is bad for hits/over (fewer hits) but good for SO/over (more strikeouts). A single vulnerability composite applied uniformly to all bet types cancels itself out. Route signals by prop type and direction.
38. **Player cap fallback logic must check prop type composition, not just leg count.** After multiple pipeline runs, the cap may leave a pool of 20+ legs that are all unders. 29 under legs with -180 juice cannot combine to reach +400 — the builder returns 0 parlays despite the fallback threshold not triggering. The fallback should verify a minimum number of over legs remain, not just total legs.
39. **Locally present files are not deployed files.** `clv_tracker.py` existed and worked locally for weeks. Railway never had it because `git status` showed `??` (untracked). Always run `git status` after a session and commit everything that should be on Railway.

---

## Future Considerations

### **1. Fix Player Cap Pool-Thinning Fallback (Immediate — Next Session)**
Fallback condition `len(pool) < 20` must be extended to also check `len(over_legs) < N`. If only unders remain after capping, restore the full pool. N ≈ 10 as a starting point. Apply same fix to both `main.py` (production) and `run_enriched_pipeline.py` (shadow).

### **2. Add 84% Coverage Ceiling (Quick Win — Highest Priority)**
One-line fix in `main.py`. Trap confirmed by training data. Not yet implemented despite being flagged since Session 9.

### **3. Vulnerability Penalty Calibration (~June 22)**
June 15 is only clean day. Thresholds (<0.15 → -10, <0.25 → -6) are starting point based on 3 legs. Re-run full hits/over vulnerability gradient analysis on June 15–22 data before finalizing.

### **4. Stack Bonus Promotion Decision (After June 20)**
Current: 72.7% vs 55.3% (11 legs). Need 7 clean days and all three promotion criteria met.

### **5. CLV Signal Read (~June 26)**
First meaningful read on whether SO/over and hits/over beat the close. Expected: SO/over positive CLV, hits/over near zero.

### **6. TB Under Promotion Decision (Late June)**
Shadow: 56.1% win rate in scored legs, 52.6% in parlays. WHIP signal validation ongoing.

### **7. Pool Expansion Strategy**
Real improvement requires pool expansion, not filtering. Priority: (1) TB under after WHIP validation, (2) pitcher SO market integration, (3) additional validated hitter props.

### **8. Pitcher SO Market Integration (Phase 2)**
Pitcher strikeout total props require new SGO market parameter + pitcher coverage logic.

### **9. Hits/Over Reassessment After CLV**
Current: 66.9% win rate June 12-14 (above breakeven at -202), but 59.9% on June 1-10 clean window (below breakeven). CLV will provide a cleaner verdict.

### **10. Learning Loop**
Once 500+ resolved legs exist under current scoring, regression on signals vs outcomes. Recalibrate weights from data.

---

**Architecture Status:** ✅ STABLE
**Last Major Change:** June 16, 2026 (Shadow pitcher signal overhaul, shadow resolution fix, player cap extended to shadow)
**Next Architecture Review:** After June 20 shadow data review + CLV first read (~June 26)
