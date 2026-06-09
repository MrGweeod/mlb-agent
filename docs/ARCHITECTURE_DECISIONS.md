# MLB Parlay Agent — Architecture Decisions
**Last Updated:** June 9, 2026 (Session 9 — Performance Analysis + Data Pipeline Gaps + TB Under + Bug Fixes)

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
12. [Outcome Resolution](#outcome-resolution)
13. [Database Design](#database-design)
14. [Pipeline Architecture](#pipeline-architecture)
15. [Lessons Learned](#lessons-learned)
16. [Future Considerations](#future-considerations)

---

## Core Philosophy

### **Decision: Optimize for Validated Edge, Not Feature Complexity**

The system exists to find props where historical coverage rate predicts actual outcomes, and combine them into parlays with positive expected value. Every design decision should be evaluated against this goal.

**Validated as of June 2026:**
- `hits over 0.5` at 65%+ coverage: genuine +6pp edge above breakeven
- `SO over 0.5` (hitter) at 65%+ coverage: genuine +7pp edge above breakeven (80.6% win rate June 5-7)
- `hits under 0.5` at 40%+ hitless rate: signal being validated — gate unblocked June 8
- Park factor: 30-point win rate spread between pitcher parks (40%) and hitter parks (70%)

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
     + whip_rank_adjustment       # ±5 for hits props (opp_pitcher_whip_rank — new June 8)
     + k9_rank_adjustment         # ±5 for SO props (opp_pitcher_k9_rank, raw fallback)
     + lineup_stability           # -5 if lineup_consistency < 0.50
```

### **Key Scoring Decision: `coverage_overall` Always Base (June 5, 2026)**

`coverage_vs_hand` produces values within 0.5 points of `coverage_overall` on average, with identical win rates (62.0% vs 62.3%). Demoted to delta adjustment at 30% weight, capped ±3.

### **Key Scoring Decision: WHIP Rank for Hits Props (June 8, 2026)**

WHIP directly measures (hits + walks) per inning — the most direct pitcher signal for hits props. `opp_pitcher_whip_rank` was already attached to all hitter legs but not used in scoring. Added ±5 adjustment:
- Rank 1 (elite, low WHIP) → -5 for over, +5 for under
- Rank 15 (average) → 0
- Rank 30 (poor, high WHIP) → +5 for over, -5 for under

---

## Prop Selection — Data-Driven Whitelist

### **Decision: Strict Whitelist Based on 60-Day Outcome Analysis (June 1, 2026)**

Only props showing monotonically increasing coverage-to-win-rate relationship are included.

**Current production whitelist:**
```python
ALLOWED_PROPS = {
    ("hits",       "over",  0.5),
    ("hits",       "under", 0.5),
    ("strikeouts", "over",  0.5),  # hitter only — pitchers skipped by position check
}
```

**Removed props and reasons:**

| Prop | Reason |
|---|---|
| `rbi under 0.5` | Flat signal — book prices edge away (avg -280 to -348) |
| Pitcher SO (all) | Coverage missing for most legs; win rates 30-52% |
| `walks`, `homeRuns`, `stolenBases` | Insufficient sample / negative edge |
| Strikeouts under | Not available on DraftKings |

**Design principle:** Never add a prop type without 200+ resolved appearances showing monotonically increasing coverage-to-win-rate.

### **Decision: Total Bases Under 1.5 — Shadow Validation Only (June 9, 2026)**

TB under was previously removed due to "flat signal" — but that analysis used corrupted pre-April-27 training data. Clean data analysis (April 27+) shows:
- 61.1% win rate in 65-74% coverage bucket on 422 legs
- Breakeven at -163 average odds is 61.9% — marginal edge, insufficient for production
- TB over has no edge at any coverage level — book fully prices it — excluded permanently
- 45-54% coverage bucket shows 76.0% on 25 legs but sample too small to trust

**Decision:** Added TB under 1.5 to production coverage pipeline (not production parlays) so shadow pipeline can accumulate resolved legs with WHIP rank signal. Promote to production only after WHIP signal validates 5pp+ spread between elite and weak WHIP tiers.

**Line restriction:** Only 1.5 line is meaningful — 0.5 lines are over-juiced noise. Hard-coded as line gate in enriched_scorer.py and ALLOWED_PROPS filter.

---

## Coverage Gating Architecture

### **Decision: Direction-Aware Two-Gate System (June 8, 2026)**

**Previous architecture (broken for unders):** Single gate `coverage_overall >= 65%` applied to all directions. Structurally impossible for hits under — a healthy MLB hitter goes hitless in only 27-35% of games. Result: 0-1 hits under legs per day despite being a valid prop.

**New architecture:**
```python
# Gate 1 — direction-aware floor
if direction == "over" and coverage_overall_raw < 65.0:
    continue   # over: validated floor
if direction == "under" and coverage_overall_raw < 40.0:
    continue   # under: ~.240 BA hitter, genuinely weak
```

**Rationale for 40% under floor:** A 40% hitless rate corresponds to roughly a .240 batting average — a legitimately weak hitter.

**Parlay builder mirrors same logic:**
```python
MIN_COV_POOL       = 65.0   # overs
MIN_COV_POOL_UNDER = 40.0   # unders
floor = MIN_COV_POOL_UNDER if direction == "under" else MIN_COV_POOL
```

**Known limitation:** Under legs score 43-61 vs overs scoring 65-81 on the same raw scale. Unders clear the pool but lose the score competition. Score normalization deferred until 50+ resolved under outcomes validate the signal.

### **Decision: 85%+ Coverage Is a Trap, Not a Signal (June 9, 2026)**

Clean training data analysis confirmed that win rates collapse at 85%+ coverage:
- Hits over: drops from 71.8% (75-84% bucket) to 31.5% (85%+ bucket)
- SO over: drops from 72.7% to 46.8%

This is almost certainly a data artifact — players showing 85%+ coverage are doing so on very small samples, or the coverage calculation has a ceiling/overflow issue at extreme values. **A hard ceiling of 84% should be added to the production gate.** This fix is pending implementation.

---

## Parlay Construction Evolution

### **Phase 1: ML-based (April–May 2026) — ABANDONED**
### **Phase 2: Anchor/Swing Two-Pool (May 28, 2026) — REPLACED**
### **Phase 3: Single Flat Pool 4-Leg +400–+700 (June 1, 2026)**
### **Phase 3.1: Score-Sort + MAX_CANDIDATES 50 (June 5, 2026)**
### **Phase 3.2: Direction-Aware Score Floor (June 8, 2026)**
### **Phase 3.3: TB Under Excluded from Production Parlays (June 9, 2026) — CURRENT**

TB under legs flow through coverage and scoring but are filtered out before build_parlays() via `production_legs` filter. This allows shadow pipeline validation without contaminating production parlay quality.

---

## Manual Regen Player Diversity

### **Decision: Exclude Prior-Run Players from Manual Regenerate (June 8, 2026)**

Regen excludes players from the most recent prior batch (auto or manual). Fallback to full pool if fewer than 4 legs remain. Automated runs unaffected.

### **Bug: RealDictCursor Silent Failure (June 9, 2026)**

The exclusion logic used `row[0]` (integer index) to extract player names, but `get_conn()` uses `RealDictCursor` which returns dict-like rows. Every manual regen silently failed with `KeyError: 0`, caught by the except block, logged as `[manual_regen] Could not fetch exclusion list (non-fatal): 0`. The feature never worked from June 8 until June 9. Fixed to `row["player_name"]`.

**Lesson:** Always use named dict keys with RealDictCursor. Never use integer indexes on database rows.

---

## Odds Cap Decision

### **Decision: -250 Hard Cap Per Leg (June 1, 2026)**

At -250, breakeven is 71.4%. Validated hits over win rate at 75-79% coverage is 75.4%. Edge exists. At -300, breakeven is 75.0% — edge disappears for most legs.

---

## Coverage Signal Architecture

### **Decision: `coverage_vs_hand` as Delta, Not Base (June 5, 2026)**

`coverage_overall` = gate and base. `coverage_vs_hand` = delta at 30% weight, ±3 cap.

**Note on under props:** For hits under, `coverage_vs_hand` log-odds adjustment is correctly inverted — a higher batting average vs a given handedness means *worse* coverage for under, so the adjustment flips sign. This is implemented in `coverage.py` `_hitter_coverage()`.

### **Decision: coverage_vs_hand Falls Back to coverage_overall When None (June 9, 2026)**

Previously `coverage_vs_hand` was left NULL when pitcher handedness was unknown, causing 43% of legs to have no handedness signal. Fixed in `coverage.py` — falls back to `coverage_overall` when `coverage_vs_hand` is None. Population rate improved from 57% to ~100%.

---

## Pitcher Signal Pipeline

### **Decision: Per-Start IP Filter (June 5, 2026)**
3+ starts, 3.0+ IP/start. Pool: ~20-25 → 192 qualified starters.

### **Decision: Position-First Pitcher Prop Detection (June 5, 2026)**
`position in ("SP", "RP", "P")` is authoritative. `stat in _PITCHER_STATS` was fragile and misrouted batter SO legs.

### **Decision: Opposing Pitcher Ranks on Hitter Legs (June 5, 2026)**
`opp_pitcher_era_rank`, `opp_pitcher_k9_rank`, `opp_pitcher_whip_rank` attached to all hitter legs.

### **Decision: WHIP Rank Signal for Hits Props (June 8, 2026)**
WHIP is the most direct signal for hits (measures hits+walks/IP). Added ±5 adjustment to production `simple_scorer.py` for hits props. Inverted for under direction. Rank normalization: `(whip_rank - 15.5) / 2.9`, capped ±5.

### **Decision: K9 Rank Signal for Batter Strikeout Props**
`opp_pitcher_k9_rank` normalized 1-30. Continuous formula: `(15.5 - k9_rank) / 2.9`, capped ±5.

### **Decision: ERA Rank Removed from Enriched Scorer (Pending Revalidation)**
ERA rank signal was directionally unreliable in shadow data, confounded by: (1) 50 IP threshold contaminating the pool, and (2) scale bug — ranks were 1-192 not 1-30. Both fixed June 8. Needs 3+ days clean data before re-enabling.

### **Decision: Prop-Specific Pitcher Signal Routing in Shadow Scorer (June 9, 2026)**

Stacking all three pitcher signals (ERA, K9, WHIP) on every prop type risks cancellation — a pitcher can have elite K9 but poor WHIP, and applying both to a hits prop partially cancels. Implemented isolated routing in `enriched_scorer.py`:

| Prop | Signals | Cap | Rationale |
|---|---|---|---|
| `totalBases under 1.5` | WHIP rank only | ±5 | WHIP = hits+walks/IP, most direct TB signal |
| `strikeouts over 0.5` | K/9 rank only | ±5 | K/9 directly measures strikeout rate |
| `hits over/under 0.5` | ERA + K/9 + WHIP | ±2 each (±6 max) | All three pitcher dimensions affect hits |

For hits props, each signal is capped at ±2 (not ±5) so the combined maximum is ±6 — keeping pitcher influence proportional to the coverage base signal and preventing any single signal from dominating.

---

## Shadow Pipeline Strategy

### **Decision: Shadow Before Promoting**
Significant scoring changes run as shadow pipeline for 5-7 days before production promotion.

### **Decision: Resolution Must Be Wired to Shadow Table**
Fixed June 5. All 5 resolution paths write to `mlb_scored_legs_enriched`.

### **Decision: Validate Shadow Signals With Correct Data Before Promoting (June 8, 2026)**

Two bugs found that made shadow signal analysis untrustworthy:

**Bug 1 — ERA rank scale:** `blended_era_rank` was on a 1-N scale where N = pool size (192), not 1-30. Fixed in `enriched_scorer.py`.

**Bug 2 — park_factor not persisted:** `park_factor` was missing from the `mlb_parlay_legs_enriched` INSERT. Fixed in `run_enriched_pipeline.py`. 870 rows backfilled.

**Implication:** Shadow pipeline performance data prior to June 8 is not reliable for ERA rank or park factor analysis.

### **Decision: TB Under Validated in Shadow Before Production (June 9, 2026)**

TB under's edge is marginal at average odds — 61.1% win rate vs 61.9% breakeven in the 65-74% coverage bucket. Adding it to production without further validation would introduce a near-breakeven prop that could dilute parlay quality. The WHIP signal is the hypothesis: elite opposing pitcher WHIP should push TB under win rates above breakeven. Shadow pipeline will validate this over 2-3 weeks before production promotion.

---

## Enriched Scoring Signals

### **Signal 1: Blended ERA Rank (Computed — NOT applied to score)**
Season ERA rank × 0.5 + last-3-start ERA rank × 0.5. Normalized to 1-30. Stored on all hits legs. Pending revalidation after scale fix.

### **Signal 2: Opponent-Specific Coverage (Active — thin data)**
Batter's hit rate vs tonight's specific opponent (min 3 games, 25% delta, ±8 cap). ~20-35% population rate early season.

### **Signal 3: Ballpark Factor (Active — validated, now correctly persisted)**
30-row `ballpark_factors` static table. Validated: 30-point win rate spread. Fixed June 8. `ABR_ALIASES` added: `ATH → OAK`, `AZ → ARI`.

### **Signal 4: Prop-Specific Pitcher Routing (Active — June 9, 2026)**
See Pitcher Signal Pipeline section above.

---

## Outcome Resolution

### **Decision: Fail-Safe EEP with Explicit Presence Check (June 1, 2026)**
EEP fires only when `plateAppearances`/`battersFaced` explicitly present. `game_not_found` defers rather than voids.

### **Decision: Shadow Table Resolution Parity (June 5, 2026)**
All 5 void/won/lost paths write to both `mlb_scored_legs` and `mlb_scored_legs_enriched`.

---

## Database Design

### **Critical Type Rules**
- `mlb_scored_legs.run_date`: TEXT — use string comparisons
- `mlb_scored_legs.odds`: TEXT — cast to numeric for math: `odds::numeric`
- `mlb_parlay_recommendations_v2.run_date`: DATE — no cast needed
- `mlb_training_data.result`: `'hit'/'miss'/'void'` — different from parlay tables' `'won'/'lost'`
- `mlb_scored_legs_enriched.id`: NULL for all rows — use natural key for all writes

### **Training Data Schema (Post Session 9)**
The following columns are now populated going forward (previously NULL):
- `coverage_overall` — direction-aware season coverage (primary signal)
- `coverage_recent_10` — rolling 10-game coverage (consistency base)
- `pitcher_era_rank` — opposing pitcher ERA rank (1-30)
- `pitcher_k9_rank` — opposing pitcher K/9 rank (1-30)
- `pitcher_whip_rank` — opposing pitcher WHIP rank (1-30)
- `whip_adj` — WHIP rank adjustment applied by scorer
- `k9_adj` — K/9 rank adjustment applied by scorer
- `era_adj` — ERA rank adjustment applied by scorer

These columns enable future signal validation queries against historical outcomes.

### **Clean Training Data Cutoff: April 27, 2026**
The coverage calculation for hits direction was incorrect before the week of April 27. Hits over jumped from ~31% to ~58% win rate and hits under dropped from ~68% to ~42% in a single week — a mirror image flip confirming the direction logic was inverted and then fixed. **All training data before April 27, 2026 must be excluded from signal validation analysis.** The flip is confirmed at weekly granularity by this query pattern showing the exact week.

### **Anti-Pattern: ORDER BY before UNION ALL**
```sql
-- WRONG
SELECT ... ORDER BY x
UNION ALL
SELECT ... ORDER BY x;

-- CORRECT
SELECT ...
UNION ALL
SELECT ...
ORDER BY x;
```

### **Backfill Scripts: Use Game-Level Maps, Not Per-Leg API Calls**
Always build a `game_pk → data` map upfront (one API call per unique game) rather than one call per leg. Per-leg calls fail at scale and can't handle abbreviation mismatches centrally. Always maintain an `ABR_ALIASES` map (`ATH → OAK`, `AZ → ARI`) applied at the API boundary.

---

## Pipeline Architecture

### **3× Daily + Shadow After Every Run**
- 9:00 AM ET — Resolution + fresh parlays (shadow runs after)
- 12:00 PM ET — Midday refresh (shadow runs after)
- 5:30 PM ET — Evening refresh (shadow runs after)
- Manual Regenerate — excludes prior-run players, shadow runs after

### **Decision: Remove Deprecated recommendation_logger (June 9, 2026)**
`recommendation_logger.py` was writing to `mlb_recommendations` (renamed to `mlb_recommendations_deprecated_20260512`). Every pipeline run crashed with a foreign key violation after saving v2 parlays, preventing the shadow pipeline from ever running. Removed the import and call from `main.py` entirely. The module is now dead code and can be deleted in a future cleanup.

---

## Lessons Learned

1. **Coverage alone is not edge.** The book also knows historical coverage rates. Edge exists only where predicted win probability exceeds the book's implied probability.
2. **Flat coverage signals mean cut, not raise the floor.** Flat win rate across all coverage buckets with 500+ appearances = signal doesn't exist.
3. **Pool size determines parlay structure.** Design around what the data actually provides daily.
4. **Sort order determines parlay quality, not just efficiency.** Sorting by odds for B&B pruning caused systematic selection of low-quality cheap-odds legs.
5. **Candidate limit determines search depth.** MAX_CANDIDATES=15 caused B&B to stop after finding 15 combinations built from the same top legs.
6. **IP thresholds can silently exclude the best data.** 50-inning season minimum excluded Ohtani, Cole, Harrison from the pitcher ranking pool.
7. **Function names can mislead.** `_attach_pitcher_rank_signals()` only attached to pitcher prop legs, not hitter legs facing pitchers.
8. **Shadow pipeline must have outcome resolution.** Shadow scoring data without resolved outcomes is completely unvalidatable.
9. **Resolution bugs compound quickly.** The `id=NULL` issue caused 1,240 rows to silently not update.
10. **stat-name-based routing is fragile.** Using `stat in _PITCHER_STATS` for pitcher prop detection misrouted all batter strikeout legs.
11. **API defaults can silently corrupt logic.** Use `is not None` guards for boolean conditions.
12. **High-score player saturation kills manual parlays.** Without per-run exclusion, the same players dominate every Regenerate run.
13. **Automated and manual runs need different diversity rules.** Auto runs want the best available players on every run. Manual regens want fresh picks.
14. **A gate that works for overs can be structurally impossible for unders.** The 65% coverage floor is mathematically impossible for hits under — no healthy MLB hitter goes hitless 65%+ of games.
15. **Score scales must be comparable before competing in the same pool.** A 40% hitless rate and a 70% hit rate represent similar edge above their respective breakevens, but raw scores of 40 vs 70 make unders always lose.
16. **Rank scale bugs are invisible without spot-checking values.** `blended_era_rank` was 1-192 for months before a diagnostic query revealed the issue. Always spot-check rank distributions after changing pool size.
17. **Backfill scripts should build lookup maps, not make per-leg API calls.** 870 legs from 10 unique games = 10 API calls, not 870.
18. **API abbreviations drift from internal tables.** Always maintain an `ABR_ALIASES` map applied at the API boundary.
19. **Training data schema must match scoring schema.** Pitcher rank signals were computed and used in scoring but never written to training data — making signal validation impossible for months. Any signal used in scoring must also be persisted at resolution time.
20. **Corrupted training data must be date-gated before analysis.** A coverage calculation bug before April 27, 2026 inverted hits over/under win rates completely. Always verify training data integrity before drawing conclusions. The April 27 cutoff is confirmed by weekly granularity analysis showing a mirror-image flip in a single week.
21. **Deprecated write paths cause silent pipeline failures.** `recommendation_logger.py` was crashing the pipeline after v2 parlays were saved, silently preventing the shadow pipeline from ever running. Any deprecated DB write path must be fully removed, not just commented out.
22. **RealDictCursor rows require string keys, not integer indexes.** `row[0]` silently raises KeyError with RealDictCursor, caught by broad except blocks. Always use `row["column_name"]` with psycopg2 dict cursors. Verify cursor type before writing row access logic.
23. **Stacking pitcher signals across all prop types causes cancellation.** ERA, K9, and WHIP can conflict — a pitcher with elite K9 but poor WHIP would partially cancel adjustments for hits props. Route each signal to the prop type where it's most predictive, not uniformly across all props.
24. **85%+ coverage is a trap.** Win rates collapse above 84% — likely a small-sample artifact or ceiling issue in the coverage calculation. Add a hard ceiling when adding new coverage gates.
25. **A broken feature that never ran is not the same as a working feature.** The manual regen exclusion appeared to be deployed but silently failed every run. Always verify new features produce expected log output before considering them live.

---

## Future Considerations

### **1. Add 85%+ Coverage Ceiling (Quick Win — High Priority)**
Confirmed trap by clean training data. One-line fix in main.py gate. Should be done next session.

### **2. Hits Under Score Normalization (After 50+ Resolved Legs)**
Under legs scoring 43-61 vs overs scoring 65-81. Two options:
- **Option A:** Separate pool slots — 1-2 guaranteed under slots per parlay
- **Option B:** Normalize scores so 40% hitless ≈ 70% hit rate in edge terms
Do not implement before 50+ resolved under outcomes.

### **3. Lineup Confirmation Gate (High Priority)**
Anthony Volpe-style voids still possible. Blueprint Phase 3 item with demonstrated impact.

### **4. TB Under Promotion Decision (Late June)**
After WHIP signal validation via shadow pipeline (~2 weeks). Decision criteria: elite WHIP tier (rank 1-8) winning 5pp+ above weak WHIP tier (rank 23-30).

### **5. Shadow Pipeline Promotion (June 15+)**
ERA rank and park factor bugs fixed. After 3-5 days clean shadow data confirms signals are working.

### **6. ERA Rank Re-Evaluation (June 12+)**
Scale bug fixed — ranks now correctly 1-30. Re-run ERA tier win rate analysis after 7+ days clean data.

### **7. Manual Regen Fallback Threshold**
Monitor `[manual_regen] Pool too thin` in Railway logs. If firing regularly, raise threshold from 4 to 8-10.

### **8. Learning Loop**
Once 500+ resolved legs exist under current scoring system, run regression on signals vs outcomes. Recalibrate weights from data rather than principled priors.

### **9. Gate 3 — Minimum `coverage_recent_10` Floor**
Block legs where `coverage_recent_10 < 50%`. Deferred pending consistency signal validation.

---

**Architecture Status:** ✅ STABLE
**Last Major Change:** June 9, 2026 (Training data gaps + prop-specific pitcher routing + TB under shadow + bug fixes)
**Next Architecture Review:** June 2026 (After TB under WHIP validation + shadow vs production comparison + 85% ceiling)
