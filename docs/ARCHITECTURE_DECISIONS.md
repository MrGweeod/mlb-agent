# MLB Parlay Agent — Architecture Decisions
**Last Updated:** June 18, 2026 (Session 14 — CLR Bug Fix, Coverage Ceiling Analysis, Shadow Performance Review)

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
- `SO over 0.5` (hitter) at 65%+ coverage: genuine +4.2pp edge above breakeven (444 legs, clean window Apr 27+). June 12-14: 87.1% win rate (31 legs). No coverage ceiling — monotonically improving through 84%+.
- June 1 restructure working: Jun 1-7 +5.4pp edge, Jun 8-14 +8.1pp edge at +443-481 avg odds.
- Park factor: 30-point win rate spread between pitcher parks (40%) and hitter parks (70%).
- Vulnerability signal works for hits/over: won legs avg 0.386 vs lost legs avg 0.492 (Jun 16-17).

**Revised June 18, 2026:**
- `hits over 0.5`: marginally below breakeven (-1.2pp) on full clean window (618 legs at 65.7% vs 66.9% breakeven). CLV data pending final verdict.
- `totalBases under 1.5` (shadow only): +8.9pp edge confirmed (89 legs), but park_factor and opp_coverage signals not populating — fix required before promotion.
- **Coverage ceiling effect is prop-specific.** Universal ceiling not being implemented. See Coverage Gating Architecture section.

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

**Decision: TB Under — Shadow Validation Continues, Null Signals Must Be Fixed First (Session 14 update)**

TB/under shadow data (Jun 16-17): 67.0%/51.4% win rate in scored legs, 88.4%/53.7% in selected parlay legs. Strong edge (+8.9pp, 89 legs, clean window). However, `park_factor` and `coverage_vs_opponent` are both NULL for all TB/under legs in shadow — these signals are not being attached to this prop. Production promotion blocked until null signals are investigated and fixed.

---

## Coverage Gating Architecture

### **Decision: Direction-Aware Two-Gate System (June 8, 2026)**

```python
if direction == "over" and coverage_overall < 65.0: continue
if direction == "under" and coverage_overall < 40.0: continue
```

### **Decision: Coverage Ceiling Is Prop-Specific — Universal Ceiling NOT Implemented (June 18, 2026)**

Full coverage bucket analysis run on clean data (Apr 27+, corrected 0-100 scale). Results per prop:

**hits/over:**
| Coverage Bucket | Resolved | Win Rate |
|---|---|---|
| 70–75% | 531 | 66.7% |
| 75–80% | 231 | **71.9%** ← peak |
| 80–84% | 44 | 61.4% ↓ |
| 84–90% | 6 | 50.0% ↓ |

Real ceiling is ~80%, not 84%. Prop-specific ceiling at 80% is pending implementation.

**strikeouts/over:**
| Coverage Bucket | Resolved | Win Rate |
|---|---|---|
| 75–80% | 161 | 70.2% |
| 80–84% | 47 | **78.7%** |
| 84–90% | 30 | **76.7%** |

**No ceiling for SO/over.** Win rate monotonically improves through 84%+. A universal 84% ceiling would cut the highest-quality SO/over legs — exactly wrong.

**totalBases/under:** Peaks at 70-75% (63.8%), gets noisy above 75% with small samples.

**Decision:** A universal coverage ceiling was previously flagged as a "quick win" based on hits/over data. After correcting the query scale and running per-prop analysis, that description was wrong. The effect is entirely prop-specific. Universal implementation would harm SO/over. Pending items:
- hits/over: add ~80% ceiling in `main.py`  
- SO/over: no ceiling — do not add one
- hits/under: raise floor from 40% to 65% (avg coverage 48%, no enriched signal, 1,832 legs below 55% at 39.3%)

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
### **Phase 3.6: Cross-Run 2x Player Cap Shadow (June 16, 2026)**
### **Phase 3.7: CLR Player Cap + TB Exclusion + Fallback Composition Fix (June 18, 2026) — CURRENT**

**Decision: EV-Sort Discarded by Backtest (June 12, 2026)**

---

## Player Diversity — Cross-Run Cap

### **Decision: 2x Daily Appearance Cap Applied to Both Pipelines, 1x Cap in CLR (Session 12–14)**

Three diversity constraints operate simultaneously:

1. **Intra-batch** (`parlay_builder.py`): Each player appears in at most 1 parlay per build. Enforced via `used_players` set inside `build_parlays()`.

2. **Cross-run** (`main.py` and `run_enriched_pipeline.py`): Each player appears in at most 2 total parlays per calendar day across all sources. Before each build, query `mlb_parlay_legs_v2` (production) or `mlb_parlay_legs_enriched` (shadow) to count today's prior appearances. Players at ≥2 removed from pool before `build_parlays()`.

3. **CLR batch** (`lineup_confirmation.py`, Session 14): When CLR rebuilds multiple parlays in one event, each player appears in at most 1 replacement parlay within that CLR run. Enforced via `used_replacement_player_ids: set[str]` initialized before the loop, filtered in `available_pool`, and updated after each successful rebuild. Stricter than cross-run cap because all replacements happen in a single event.

**Motivation for CLR cap:** Without it, the same top-scoring player was independently selected as a replacement in every CLR iteration — Jared Triolo appeared in 10 CLR parlays Jun 17, Jackson Chourio in 9. `build_parlays()` internal diversity only covers a single call.

**Known failure mode (fixed Session 14):** After 5+ runs, if the cross-run cap removes enough overs that only unders remain in the pool, the 4-leg +400–+700 target becomes mathematically impossible. Fixed: fallback now checks `len(over_legs_remaining) < 10` in addition to total leg count.

---

## Odds Cap Decision

**Hard cap: -250 per leg.** Above -250 juice means the book's implied probability is so high that even validated coverage signals can't overcome the vig. A leg at -300 needs 75%+ win rate just to be EV neutral.

---

## Coverage Signal Architecture

Coverage signal is derived from rolling historical outcomes per player per prop type. `coverage_overall` = wins / (wins + losses) over all available history. `coverage_recent_10` = same for last 10 resolved legs. The base signal for all scoring.

**Direction awareness:** Under coverage is structurally lower than over coverage because unders require the player to underperform. Floor gates differ accordingly (40% vs 65%) — though hits/under 40% floor is pending a raise to 65% based on June 18 data analysis.

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
June 15 data: 0/3 win rate for hits/over against pitchers with vulnerability <0.25 (Wheeler ERA 2.22, Burns ERA 2.14). Soft penalty applied, not hard exclusion. Thresholds subject to recalibration after June 22.

**Key decision: hits/under pitcher signal removed (Session 13)**
No consistent predictive signal in data. Jun 16-17 signal differentiation: vulnerability 0.482 won vs 0.476 lost — essentially no difference. Removed entirely.

**Key decision: TB/under park_factor and opp_coverage not populating (Session 14 finding)**
Signal differentiation query (Jun 16-17) showed NULL for both `park_factor` and `coverage_vs_opponent` on all TB/under legs. These signals are not being attached to TB/under in the enrichment path. Must investigate and fix before production promotion.

---

## Shadow Pipeline Strategy

### **Decision: Shadow Pipeline as Signal Validation Layer**

The shadow pipeline runs after every production pipeline. It scores all props (including TB/under) using the enriched scorer with pitcher signals. Parlays are built and tracked but not shown in Discord. Purpose: validate new signals before promoting to production.

**Performance (Jun 16-17):** Shadow win rates 32.0%/25.0% vs production 10.0%/22.2%. Shadow had zero voided parlays; production had 6/10 voids from now-fixed CLR bugs.

**Resolution architecture (Session 13):**
Shadow scored leg resolution runs via `resolve_all_enriched_legs()` in the daily morning pipeline. Previously only ~20 legs/day (parlay legs only) were resolved; now the full ~160 leg/day pool is covered.

**Clean data cutoffs:**
- Shadow pitcher signals: Valid from June 15 only (first day with correct dynamic rank normalization)
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

Event-driven annotation system. After 9AM pipeline, rows are written to `mlb_pending_lineup_checks` for each start-time group at T-45 and T-1. Drain cron polls every minute. On trigger, fetches live lineups via statsapi hydrate. Annotates each parlay leg with `batting_order` and `lineup_check_status` (CONFIRMED/OUT_OF_RANGE/SCRATCHED/MISSING). If SCRATCHED or OUT_OF_RANGE detected, triggers CONFIRMED_LINEUP_RESOLUTION rebuild.

**CLR pool rules (Session 14):**
- TB/under excluded from CLR replacement pool (mirrors `main.py` production exclusion)
- Cross-iteration player cap: max 1 player appearance per CLR batch via `used_replacement_player_ids`
- Any future production exclusions in `main.py` must be explicitly mirrored in CLR pool construction

---

## CLV Tracking Layer

After 9AM pipeline, CLV rows are scheduled at T-1 for each start-time group. On trigger, `clv_tracker.py` re-fetches SGO odds and writes `closing_odds` + `closing_odds_captured_at` to `mlb_scored_legs`. Live since June 16. First meaningful read: ~June 26.

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

### **Production:** `resolve_all_legs(run_date)` — box score path, one API call per game. Runs every 9AM pipeline.

### **Shadow (Session 13):** `resolve_all_enriched_legs(run_date)` — same box score path targeting `mlb_scored_legs_enriched`. Natural key `(run_date, odd_id)` — never `id` (NULL for all rows). Runs every 9AM pipeline immediately after `resolve_all_legs()`.

### **Shadow parlay mirror:** `resolve_enriched_parlays(run_date)` — syncs outcomes from `mlb_parlay_legs_enriched` back to `mlb_scored_legs_enriched`. Direction filter required: `AND direction = %s` in both lookup and UPDATE.

---

## Database Design

### **Natural Keys vs Surrogate Keys**
`mlb_scored_legs_enriched.id` is NULL for all rows. All updates must use natural key `(run_date, odd_id)`. Never reference `id` in UPDATE statements targeting this table.

### **PostgreSQL Conventions**
- Never `ROUND()` — use `::numeric(p,s)`
- `RealDictCursor` everywhere — `row["col"]`, never `row[0]`
- `run_date` is TEXT in `mlb_scored_legs` and `mlb_scored_legs_enriched` — filter as `run_date = '2026-06-18'`
- `run_date` is DATE in `mlb_parlay_recommendations_v2` and `mlb_parlay_recommendations_enriched` — no cast needed
- When joining: `ON p.run_date::text = s.run_date`

### **game_pks Column Format**
`mlb_pending_lineup_checks.game_pks` is a TEXT column storing a PostgreSQL array literal: `{822724,823371}`. Must be serialized as `"{" + ",".join(str(pk) for pk in game_pks) + "}"`.

### **Schema Change Log**
| Date | Table | Change |
|---|---|---|
| 2026-06-12 | `mlb_scored_legs` | Added: `batting_order`, `lineup_check_status`, `lineup_checked_at`, `closing_odds`, `closing_odds_captured_at` |
| 2026-06-12 | `mlb_parlay_legs_v2` | Added: `batting_order`, `lineup_check_status`, `lineup_checked_at` |
| 2026-06-12 | `mlb_parlay_recommendations_v2` | Added: `superseded_by_batch_id`, `superseded_reason` |
| 2026-06-12 | `mlb_pending_lineup_checks` | New table created |
| 2026-06-12 | `mlb_scored_legs_enriched` | Added: `stack_bonus_applied`, `pitcher_vulnerability` |

### **Training Data Schema (Post Session 9)**
`coverage_overall`, `coverage_recent_10`, `pitcher_era_rank`, `pitcher_k9_rank`, `pitcher_whip_rank`, `whip_adj`, `k9_adj`, `era_adj` all now persisted.

### **Clean Training Data Cutoff: April 27, 2026**
Coverage calculation was inverted before April 27. All signal validation must use `run_date >= '2026-04-27'`.

### **Clean Shadow Signal Cutoff: June 15, 2026**
Dynamic rank normalization deployed June 15. Shadow pitcher vulnerability scores are only valid from June 15 onward.

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
- **On SCRATCHED/OUT_OF_RANGE** — CONFIRMED_LINEUP_RESOLUTION rebuild (TB/under excluded, 1x player cap)

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
16. **Rank scale bugs are invisible without spot-checking values.** The 30-pitcher hardcoded scale bug existed in two separate functions. Always verify that rank normalization uses `len(pitcher_ranks)` at runtime.
17. **Backfill scripts should build lookup maps, not make per-leg API calls.**
18. **API abbreviations drift from internal tables.** Always maintain `ABR_ALIASES`.
19. **Training data schema must match scoring schema.**
20. **Corrupted training data must be date-gated before analysis.** April 27 cutoff is confirmed.
21. **Deprecated write paths cause silent pipeline failures.**
22. **RealDictCursor rows require string keys, not integer indexes.**
23. **Stacking pitcher signals across all prop types causes cancellation.**
24. **A coverage ceiling observed in one prop does not generalize to all props.** The 84% ceiling was documented based on hits/over data and incorrectly treated as a universal rule. Full per-prop bucket analysis (Session 14) showed SO/over monotonically improves through 84%+ — a universal ceiling would have cut the best SO/over legs. Always validate ceiling effects per prop before implementing.
25. **A broken feature that never ran is not the same as a working feature.** `lineup_scheduler.py` and `clv_tracker.py` were both wired into `main.py` and referenced correctly, but neither file existed on Railway. Always verify with `git show HEAD:src/path/to/file.py`.
26. **Backtest pool contamination produces confidently wrong conclusions.** Running variants against a pool wider than production makes filtering appear to improve leg quality when it's actually filtering out props the production system never used.
27. **EV-sort requires a signal that discriminates within the validated pool.** coverage_overall-derived EV does not rank legs differently within an already-validated pool.
28. **Same-game correlation finding requires larger sample before acting on it.** Q3 found 20.0% vs 12.6% from a small sample. Session 14 data: only 3 same-game pairs in 316 parlays over 30 days — correlation-based construction changes not warranted yet.
29. **Multi-loss clustering is expected math, not a signal of system failure.** At 65% per-leg, conditional on a 4-leg parlay losing, ~53% of losses have 2+ losing legs.
30. **Database-backed schedulers are worth the extra table.** An in-memory APScheduler job is one Railway restart away from disappearing. Postgres-backed drain with 1-minute poll makes the scheduler restart-proof.
31. **Verify parsers against real API responses before trusting them.** Lineup hydrate parser explicitly verified against real `battingOrder` response (19/19 slot match).
32. **The hypothesis you're testing must match the data you're testing it on.** Slot gate hypothesis contradicted by current data — keep annotation, don't gate.
33. **The same bug can exist in two separate functions.** When fixing a class of bug, search all occurrences of the pattern before closing the fix.
34. **Backfill scripts that go through application logic may fail on already-resolved data.** Direct SQL (`UPDATE ... FROM` JOIN) bypasses the application-level state machine entirely and is the correct approach for data repair.
35. **Shadow scored legs and shadow parlay legs are different sources of truth.** Parlay leg outcomes conflate signal quality with construction quality. Scored leg outcomes isolate signal quality. Both are needed; use the right one for the right question.
36. **Direction filters in resolution queries are not optional.** A join on `(player_name, stat, run_date)` without `direction` will silently return the wrong result for any player with both an over and under leg on the same day. `LIMIT 1` is not a safety net.
37. **Prop-specific pitcher signals must account for which direction improves outcomes.** Facing an elite K/9 pitcher is bad for hits/over but good for SO/over. A single composite applied uniformly cancels itself out.
38. **Player cap fallback logic must check prop type composition, not just leg count.** 29 under legs with -180 juice cannot combine to reach +400 — the builder returns 0 parlays despite the fallback threshold not triggering.
39. **Locally present files are not deployed files.** Always run `git status` after a session and commit everything that should be on Railway.
40. **CLR does not inherit production filters from main.py.** Any prop exclusion, odds cap, or coverage gate applied in `main.py` must be explicitly mirrored in `run_confirmed_lineup_resolution()`'s pool construction. CLR builds its pool independently from `mlb_scored_legs` — it has no awareness of what `main.py` would have filtered. Session 14 found TB/under (shadow-only) leaking into 27 production CLR parlays because the `stat != "totalBases"` filter existed in `main.py` but not in CLR.
41. **build_parlays() player diversity only covers a single call.** The internal `used_players` set resets on every invocation. When CLR calls `build_parlays()` in a loop (one call per affected parlay), each call has no memory of which players were selected in prior iterations. Cross-iteration diversity requires an explicit tracking set in the calling code, not inside `build_parlays()` itself.
42. **SQL query scale assumptions must match the stored data scale.** Coverage bucket analysis initially used decimal thresholds (0.55, 0.65) when `coverage_overall` is stored as a percentage (55.0, 65.0). Every row landed in the `>= 0.90` bucket. Always verify the value scale of a column before writing range queries.

---

## Future Considerations

### **1. Fix TB/under Null Signals (Immediate — Next Session)**
`park_factor` and `coverage_vs_opponent` are NULL for all TB/under legs in shadow. Investigate why these signals aren't attaching to TB/under in `enriched_scorer.py` / `run_enriched_pipeline.py`. Required before production promotion decision.

### **2. Raise hits/under Coverage Gate from 40% to 65% (Next Session)**
Data: 1,832 legs below 55% at 39.3% win rate, avg coverage ~48%, no enriched signal differentiation. One-line change in `main.py`.

### **3. Add prop-specific hits/over Ceiling at ~80% (Next Session)**
Data: win rate peaks at 75-80% (71.9%), drops to 61.4% at 80-84% (44 legs). Simple per-prop filter in `main.py`. Do NOT apply universally — SO/over must remain uncapped.

### **4. Vulnerability Penalty Calibration (~June 22)**
Jun 15-18 now available. Rerun full hits/over vulnerability gradient analysis before finalizing thresholds (<0.15 → -10, <0.25 → -6).

### **5. TB Under Promotion Decision (Late June)**
Shadow edge confirmed (+8.9pp, 89 legs). Blocked pending null signal fix. Recheck after signals are populated and June 20+ shadow data available.

### **6. Stack Bonus Promotion Decision (After June 20)**
Current: 72.7% vs 55.3% (11 legs — small sample). Re-evaluate after June 20.

### **7. CLV Signal Read (~June 26)**
First meaningful read on whether SO/over and hits/over beat the close. Expected: SO/over positive CLV, hits/over near zero.

### **8. Pool Expansion Strategy**
Real improvement requires pool expansion, not filtering. Priority: (1) TB under after null signal fix + shadow validation, (2) pitcher SO market integration, (3) additional validated hitter props.

### **9. Pitcher SO Market Integration (Phase 2)**
Pitcher strikeout total props require new SGO market parameter + pitcher coverage logic.

### **10. Hits/Over Reassessment After CLV**
Currently -1.2pp below breakeven on full clean window. CLV will provide cleaner verdict on whether the book has priced out the edge entirely.

### **11. Learning Loop**
Once 500+ resolved legs exist under current scoring, regression on signals vs outcomes. Recalibrate weights from data.

---

**Architecture Status:** ✅ STABLE
**Last Major Change:** June 18, 2026 (CLR bugs fixed, coverage ceiling confirmed prop-specific)
**Next Architecture Review:** After June 22 vulnerability calibration + TB/under null signal fix
