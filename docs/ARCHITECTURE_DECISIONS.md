# MLB Parlay Agent — Architecture Decisions
**Last Updated:** June 12, 2026 (Session 10 — Lineup Confirmation + CLV Tracking + Backtest Harness + Correlation Spec)

---

## Table of Contents
1. [Core Philosophy](#core-philosophy)
2. [Scoring System Evolution](#scoring-system-evolution)
3. [Prop Selection — Data-Driven Whitelist](#prop-selection--data-driven-whitelist)
4. [Coverage Gating Architecture](#coverage-gating-architecture)
5. [Parlay Construction Evolution](#parlay-construction-evolution)
6. [Manual Regen Player Diversity](#manual-regen-player-diversity)
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
- `SO over 0.5` (hitter) at 65%+ coverage: genuine +2.8pp edge above breakeven confirmed on clean June 1-10 data
- Same-game correlation: 20.0% parlay win rate with same-game pair vs 12.6% without — +7.4pp confirmed
- Park factor: 30-point win rate spread between pitcher parks (40%) and hitter parks (70%)

**Revised June 12, 2026:**
- `hits over 0.5` at 65%+ coverage: **at or below breakeven** on clean June data (59.9% win rate vs 66.9% breakeven at -202 odds). Previously believed to have +6pp edge — that finding used pre-April-27 corrupted data. Reassess after CLV data matures.
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
     + slot_gate_penalty          # -8 if batting_order known + outside BATTING_ORDER_FAVORABLE range (June 12)
```

### **Key Scoring Decision: Slot Gate as Soft Penalty (June 12, 2026)**

Batting order data now captured via the lineup confirmation layer. A known unfavorable batting slot applies a −8 scoring penalty rather than a hard exclusion. Rationale: absence of data (unknown slot) must not penalize a leg; only confirmed unfavorable slots are penalized. The backtest showed the slot gate hypothesis is contradicted by current data (slots 6-9 won at 66.7% vs slots 1-5 at 61.2%), but the penalty is kept small and soft pending more resolved outcomes with batting_order populated.

---

## Prop Selection — Data-Driven Whitelist

### **Decision: Strict Whitelist Based on Outcome Analysis**

Only props showing edge above breakeven with a predictive coverage signal are included.

**Current production whitelist:**
```python
ALLOWED_PROPS = {
    ("hits",       "over",  0.5),
    ("hits",       "under", 0.5),
    ("strikeouts", "over",  0.5),  # hitter only — pitchers skipped by position check
    ("totalBases", "under", 1.5),  # shadow validation only — excluded from production parlays
}
```

**Removed/deferred props:**

| Prop | Reason |
|---|---|
| `rbi under 0.5` | Flat signal — book prices edge away |
| Pitcher SO (all) | Zero pitcher legs in DB — only batter SO scored. Pitcher K total market not integrated. |
| `walks`, `homeRuns`, `stolenBases` | Insufficient sample / negative edge |
| Strikeouts under | Not available on DraftKings |
| TB over | No edge at any coverage level — excluded permanently June 9 |

**Decision: TB Under — Shadow Validation Continues (June 12 update)**

TB under on clean June 1-10 data: 55.5% win rate vs 60.7% breakeven. Below breakeven. WHIP signal validation ongoing in shadow pipeline. Non-monotonic coverage signal (55-64% bucket wins at 59.8%, 65-74% drops to 53.4%). Do not promote until WHIP tier spread ≥10pp confirmed.

**Decision: Pitcher SO Market — Not Integrated (June 12)**

Investigation confirmed: zero pitcher legs exist in `mlb_scored_legs`. All strikeout legs are batter props (positions: 1B, SS, RF, 2B, CF, LF, 3B, C, DH). The pitcher strikeout total market (e.g. over 5.5 Ks for the starting pitcher) would require new SGO market integration — it is a Phase 2 item, not a whitelist addition.

---

## Coverage Gating Architecture

### **Decision: Direction-Aware Two-Gate System (June 8, 2026)**

```python
if direction == "over" and coverage_overall < 65.0: continue
if direction == "under" and coverage_overall < 40.0: continue
```

### **Decision: 85%+ Coverage Is a Trap — Ceiling Pending**

Clean training data confirmed win rates collapse above 84%: hits over drops from 71.8% (75-84% bucket) to 31.5% (85%+). Gate fix (`coverage_overall <= 84%`) confirmed needed but not yet implemented.

---

## Parlay Construction Evolution

### **Phase 1: ML-based (April–May 2026) — ABANDONED**
### **Phase 2: Anchor/Swing Two-Pool (May 28, 2026) — REPLACED**
### **Phase 3: Single Flat Pool 4-Leg +400–+700 (June 1, 2026)**
### **Phase 3.1: Score-Sort + MAX_CANDIDATES 50 (June 5, 2026)**
### **Phase 3.2: Direction-Aware Score Floor (June 8, 2026)**
### **Phase 3.3: TB Under Excluded from Production Parlays (June 9, 2026)**
### **Phase 3.4: Slot Gate Soft Penalty Added (June 12, 2026) — CURRENT**

**Decision: EV-Sort Discarded by Backtest (June 12, 2026)**

EV-sort (rank pool by coverage_overall-derived edge rather than composite_score) tested on clean 533-leg production pool: +0.0pp leg improvement, -6.2pp parlay win rate. Root cause: `coverage_overall` does not discriminate within the validated production pool. Pool thinning from EV gate drops parlays from 191 to 49. Revisit only after pool expands (TB under promotion or new prop type) or CLV data provides a better edge signal.

**Decision: Slot Gate Discarded by Backtest (June 12, 2026)**

Slot gate tested on clean pool: +0.0pp leg improvement, -9.7pp parlay win rate. Batting order hypothesis (slots 1-5 = more PAs = more hits) contradicted by current data (slots 6-9 won at 66.7% vs slots 1-5 at 61.2% on current sample). Slot annotation continues as free data; production exclusion gate not implemented.

**Decision: Backtest Must Use Whitelist-Filtered Pool (June 12, 2026)**

First backtest run used 960-leg pool (included TB/under, hits/under) vs the correct 533-leg production pool. EV-sort appeared to show +6.3pp leg improvement — entirely from filtering out bad props (hits/under at 39.2%), not from reranking good ones. All future backtests must apply the production whitelist filter before running variants. Report the pool size explicitly.

---

## Manual Regen Player Diversity

### **Decision: Exclude Prior-Run Players (June 8, 2026)**

### **Bug: RealDictCursor Silent Failure Fixed (June 9, 2026)**

`row[0]` → `row["player_name"]`. Exclusion was silently failing since June 8.

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

### **Decision: K9 Rank Signal for Batter Strikeout Props**

### **Decision: Prop-Specific Pitcher Signal Routing in Shadow Scorer (June 9, 2026)**

| Prop | Signals | Cap |
|---|---|---|
| `totalBases under 1.5` | WHIP rank only | ±5 |
| `strikeouts over 0.5` | K/9 rank only | ±5 |
| `hits over/under 0.5` | ERA + K/9 + WHIP | ±2 each (±6 max) |

### **Decision: Pitcher Vulnerability Composite Score (June 12, 2026 — spec ready, not yet built)**

For offense stack detection in shadow pipeline, a composite `pitcher_vulnerability` score aggregates ERA rank (inverted), K/9 rank (inverted), WHIP rank — normalized 0-1. Threshold `>= 0.60` identifies bottom-third pitchers as qualifying stack targets. Falls back to raw `pitcher_era` when ranks NULL.

---

## Shadow Pipeline Strategy

### **Decision: Shadow Before Promoting**

Significant scoring changes run in shadow for 5-7 days before production promotion.

### **Decision: Offense Stack Bonus — Shadow Only (June 12, 2026)**

Same-game correlation confirmed empirically (20.0% vs 12.6% parlay win rate Q3 diagnostic). Offense stack bonus specced as post-scoring pass in `run_enriched_pipeline.py`. Shadow-only until promotion criteria met (stack legs win ≥5pp more than non-stack, shadow ≥ production parlay win rate, ≥2 stacks/day average). See spec: `CORRELATION_RESTRUCTURE_SPEC.md`.

---

## Enriched Scoring Signals

### **Signal 1: Blended ERA Rank (Computed — NOT applied to score)**
Pending revalidation after scale fix (June 8).

### **Signal 2: Opponent-Specific Coverage (Active — thin data)**
Batter hit rate vs tonight's specific opponent. ~20-35% population rate early season.

### **Signal 3: Ballpark Factor (Active — validated)**
30-row static table. 30-point win rate spread confirmed. Correctly persisted since June 8.

### **Signal 4: Prop-Specific Pitcher Routing (Active — June 9, 2026)**

### **Signal 5: Offense Stack Bonus (Specced — June 12, 2026)**
Post-scoring pass. `STACK_BONUS = 4.0` points for legs in qualifying offense stack. `STACK_VULNERABILITY_THRESHOLD = 0.60`. Shadow only — pending build.

---

## Lineup Confirmation Layer

### **Decision: Event-Driven Scheduler, Database-Backed (June 12, 2026)**

Fixed 3×/day pipeline cannot catch lineups posting after 5:30 PM. Solution: per-game-group checks fired at `game_start_time − 45 minutes`. Scheduler persisted to `mlb_pending_lineup_checks` (restart-safe). Drain: 1-minute async loop in `server.py`, stateless table polling.

### **Decision: Annotation-Only, No Hard Blocking (June 12, 2026)**

Four states: `MISSING_LINEUP_CONFIRMATION`, `LINEUP_CONFIRMED`, `BATTING_ORDER_OUT_OF_RANGE`, `SCRATCHED`. Pipeline never blocked on unconfirmed lineups. `MISSING` never triggers resolution — only `SCRATCHED` and `OUT_OF_RANGE` do.

### **Decision: CONFIRMED_LINEUP_RESOLUTION Run Type (June 12, 2026)**

When a selected player is confirmed SCRATCHED or OUT_OF_RANGE, the affected parlay is voided (`superseded_by_batch_id`, `superseded_reason`) and rebuilt from **upcoming-games-only** replacement pool. A scratched 7 PM player can never be replaced by a 1 PM leg whose game is over. Fallback: leave parlay void if replacement pool too thin rather than ship a short parlay.

### **Decision: T-45 Offset, Configurable (June 12, 2026)**

`LINEUP_CHECK_OFFSET_MINUTES = 45`. Made configurable because actual lineup posting times at T-45 are unvalidated — if lineups are consistently not posted at T-45 on live slates, flip `LINEUP_CHECK_SECOND_PASS = True` for a T-15 confirmation pass.

### **Decision: Batting Order Slot — Soft Penalty Only (June 12, 2026)**

`BATTING_ORDER_FAVORABLE` defines preferred slots per bet type. Known unfavorable slot → −8 scoring penalty. Unknown slot → no penalty. Hard exclusion gate tested and discarded by backtest (contradicts hypothesis on current sample).

---

## CLV Tracking Layer

### **Decision: Scheduled at T-1, Reusing Lineup Scheduler (June 12, 2026)**

CLV snapshot fires at `game_start_time − CLV_OFFSET_MINUTES` (default 1). Reuses `mlb_pending_lineup_checks` with `check_type = 'clv'`. Same drain, same atomic-claim pattern, same restart-safety. `CLV_OFFSET_MINUTES` is configurable — if SGO markets are routinely gone at T-1, bump to 3 or 5.

### **Decision: All Scored Legs, Not Just Parlay Legs (June 12, 2026)**

Full pool captured for recalibration and signal validation. CLV is forward-only — clock started June 12. First meaningful read ~June 26.

### **Decision: Option B — Odds + Closing Odds Only (June 12, 2026)**

`odds` = selection-time (existing column, unchanged). `closing_odds` + `closing_odds_captured_at` added. No opening odds column — the odds at selection time are the odds that matter for edge validation. CLV = implied_prob(closing_odds) − implied_prob(odds). Positive = beat the close = real edge.

### **Decision: SGO Reuse for Natural-Key Match (June 12, 2026)**

`run_clv_snapshot()` imports `get_todays_games()` and `get_player_props()` from `sportsgameodds.py` verbatim. Natural key: `(player_id, stat, line, direction)`. Guarantees consistent market representation between selection-time and closing-time odds.

---

## Backtest Harness

### **Decision: Read-Only Replay Against Real History (June 12, 2026)**

`scripts/run_backtest.py` replays June 1-10 against variants using real recorded `result` values — no future-looking. Baseline = real recorded parlay outcomes from `mlb_parlay_recommendations_v2`. Variants re-simulate construction from the same daily scored-leg pools.

### **Decision: Always Whitelist-Filter Before Running Variants (June 12, 2026)**

Backtest must filter scored-leg pool to production whitelist (`hits/over`, `hits/under`, `strikeouts/over`) before computing variants. Running against the full 960-leg pool (includes shadow TB/under and hits/under) produces misleading results — apparent EV-sort improvements were entirely from filtering bad props, not from reranking good ones.

### **Decision: Report Confidence Intervals Explicitly (June 12, 2026)**

All parlay-level claims include ±CI. With ~191 parlays, CI ≈ ±6.6pp. A change must exceed the CI to be considered signal. Leg-level claims (533 legs) carry ±4pp CI — more trustworthy.

---

## Outcome Resolution

### **Decision: Fail-Safe EEP with Explicit Presence Check (June 1, 2026)**

### **Decision: Shadow Table Resolution Parity (June 5, 2026)**

---

## Database Design

### **Critical Type Rules**
- `mlb_scored_legs.run_date`: TEXT — string comparisons only
- `mlb_scored_legs.odds`: TEXT — cast `::numeric` for math
- `mlb_scored_legs.closing_odds`: TEXT — same as odds, cast `::numeric` for CLV math
- `mlb_scored_legs.player_id`: TEXT — cast `int()` at API boundary
- `mlb_parlay_legs_v2.player_id`: INTEGER — consistent with TEXT cast pattern
- `mlb_parlay_recommendations_v2.run_date`: DATE — no cast needed
- `mlb_training_data.result`: `'hit'/'miss'/'void'` — different from parlay tables' `'won'/'lost'`
- `mlb_scored_legs_enriched.id`: NULL for all rows — use natural key for all writes
- Never `ROUND()` — use `::numeric(p,s)`
- `RealDictCursor` everywhere — `row["col"]`, never `row[0]`

### **New Columns Added Session 10**

`mlb_scored_legs`: `batting_order` (integer), `lineup_check_status` (text), `lineup_checked_at` (timestamp), `closing_odds` (text), `closing_odds_captured_at` (timestamp)

`mlb_parlay_legs_v2`: `batting_order` (integer), `lineup_check_status` (varchar), `lineup_checked_at` (timestamp with time zone)

`mlb_parlay_recommendations_v2`: `superseded_by_batch_id` (varchar), `superseded_reason` (text)

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

### **Backfill Scripts: Use Game-Level Maps**
One API call per unique `game_pk`, never one per leg. Always maintain `ABR_ALIASES` (`ATH → OAK`, `AZ → ARI`).

---

## Pipeline Architecture

### **3× Daily + Shadow After Every Run + Event-Driven Lineup/CLV Checks**
- 9:00 AM ET — Resolution + fresh parlays + schedule lineup/CLV checks (shadow runs after)
- 12:00 PM ET — Midday refresh (shadow runs after)
- 5:30 PM ET — Evening refresh (shadow runs after)
- Manual Regenerate — excludes prior-run players, shadow runs after
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
8. **Shadow pipeline must have outcome resolution.**
9. **Resolution bugs compound quickly.**
10. **stat-name-based routing is fragile.**
11. **API defaults can silently corrupt logic.**
12. **High-score player saturation kills manual parlays.**
13. **Automated and manual runs need different diversity rules.**
14. **A gate that works for overs can be structurally impossible for unders.**
15. **Score scales must be comparable before competing in the same pool.**
16. **Rank scale bugs are invisible without spot-checking values.**
17. **Backfill scripts should build lookup maps, not make per-leg API calls.**
18. **API abbreviations drift from internal tables.** Always maintain `ABR_ALIASES`.
19. **Training data schema must match scoring schema.**
20. **Corrupted training data must be date-gated before analysis.** April 27 cutoff is confirmed.
21. **Deprecated write paths cause silent pipeline failures.**
22. **RealDictCursor rows require string keys, not integer indexes.**
23. **Stacking pitcher signals across all prop types causes cancellation.**
24. **85%+ coverage is a trap.**
25. **A broken feature that never ran is not the same as a working feature.**
26. **Backtest pool contamination produces confidently wrong conclusions.** Running variants against a pool wider than production (e.g. 960 legs vs 533 production legs) makes filtering appear to improve leg quality — when it's actually filtering out props the production system never used. Always whitelist-filter the backtest pool to match production exactly before computing variants.
27. **EV-sort requires a signal that discriminates within the validated pool.** coverage_overall-derived EV does not rank legs differently within an already-validated pool (all legs pass the same coverage gate). A better edge signal — CLV, or a calibrated model — is needed before EV-sort provides value.
28. **Same-game correlation is empirically net positive for all-or-nothing bets.** Q3 diagnostic confirmed: same-game parlays win 20.0% vs 12.6% for distinct-game. Positive correlation fattens both tails — the clustering of losses that feels like a problem is the same mechanism producing higher win rates. This is a feature, not a bug.
29. **Multi-loss clustering is expected math, not a signal of system failure.** At 65% per-leg, conditional on a 4-leg parlay losing, ~53% of losses have 2+ losing legs. The daily experience of seeing multiple losing legs is statistically expected even when the system is working correctly.
30. **Database-backed schedulers are worth the extra table.** An in-memory APScheduler job registered at 9 AM for a 10 PM trigger is one Railway restart away from silently disappearing for the rest of the day. A Postgres-backed drain with a 1-minute poll costs one table and makes the scheduler restart-proof for free.
31. **Verify parsers against real API responses before trusting them.** The lineup hydrate parser was explicitly verified against a real `battingOrder` response (19/19 slot match) rather than assumed correct. This is the correct pattern for all API integrations.
32. **The hypothesis you're testing must match the data you're testing it on.** Slot gate hypothesis (slots 1-5 > slots 6-9 for hit frequency) was contradicted by current data. Keep annotation accumulating; don't implement a production gate from a hypothesis the data doesn't support.

---

## Future Considerations

### **1. Build Offense Stack Bonus (Highest Priority)**
Spec ready (`CORRELATION_RESTRUCTURE_SPEC.md`). Shadow pipeline only. Promotion requires ≥5pp stack vs non-stack leg improvement + shadow ≥ production win rate + ≥2 stacks/day.

### **2. Add 84% Coverage Ceiling (Quick Win)**
One-line fix in `main.py`. Trap confirmed by training data. Still not implemented.

### **3. CLV Signal Read (~June 26)**
First meaningful read on whether SO/over and hits/over beat the close. Expected: SO/over positive CLV, hits/over near zero. Will either confirm hits/over removal from whitelist or provide evidence to keep it.

### **4. TB Under Promotion Decision (Late June)**
After WHIP tier spread validation. Current data (55.5% win rate vs 60.7% breakeven) does not support promotion. Needs elite WHIP tier (rank 1-8) winning ≥5pp above weak tier (rank 23-30).

### **5. Pitcher SO Market Integration (Phase 2)**
Pitcher strikeout total props (e.g. over 5.5 Ks for starting pitcher) are not in the pipeline. This is a genuinely different and predictable market — pitcher K% is the fastest-stabilizing skill in baseball. Requires new SGO market parameter + pitcher coverage logic. Not a whitelist addition; a new data integration.

### **6. Hits/Over Reassessment After CLV**
Current data shows hits/over at or below breakeven (-7.0pp edge on June window). CLV will provide a cleaner verdict. If hits/over CLV is consistently negative (market moves against us after selection), consider removing from production whitelist and running SO/over-only.

### **7. Pool Expansion Strategy**
Backtest confirmed: filtering a 533-leg pool causes construction collapse. Real improvement requires pool expansion. Priority order: (1) TB under after WHIP validation, (2) pitcher SO market integration, (3) additional validated hitter props.

### **8. verify_common.py Refactor**
Extract shared boilerplate from `verify_lineup_layer.py` and `verify_clv.py` into a common module. Establishes pattern for future verification scripts.

### **9. Statcast xBA Integration**
`pybaseball` confirmed installable. `statcast_batter_expected_stats()` available. Forward-only — requires daily snapshots. Cannot be backtested honestly (look-ahead bias). Implement after CLV data matures and pool expansion decisions are made.

### **10. Learning Loop**
Once 500+ resolved legs exist under current scoring, regression on signals vs outcomes. Recalibrate weights from data.

---

**Architecture Status:** ✅ STABLE
**Last Major Change:** June 12, 2026 (Lineup confirmation layer + CLV tracking + backtest findings + correlation spec)
**Next Architecture Review:** After offense stack shadow validation (June 19+) and CLV first read (~June 26)
