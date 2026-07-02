# MLB Parlay Agent — Architecture Decisions
**Last Updated:** July 2, 2026 (Session 16 — Batting Order Slot Gate Removed, TB/under Combinatorial Drag Identified)

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
20. [Lessons Learned](#lessons-learned)
21. [Future Considerations](#future-considerations)

---

## Core Philosophy

### **Decision: Optimize for Validated Edge, Not Feature Complexity**

The system exists to find props where historical coverage rate predicts actual outcomes, and combine them into parlays with positive expected value. Every design decision should be evaluated against this goal.

*(Unchanged from prior version — see Session 15 entries below for validated-edge figures per prop as of June 18.)*

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

### **Key Scoring Decision: Slot Gate as Soft Penalty (June 12, 2026) — SUPERSEDED**
See [Batting Order Slot Gate — Removal (Session 16)](#batting-order-slot-gate--removal-session-16) below. The soft-penalty approach adopted June 12 was removed entirely on July 2 after three additional weeks of data confirmed, rather than resolved, the original contradiction.

---

## Prop Selection — Data-Driven Whitelist

*(Unchanged from Session 15 — see that section for current whitelist and breakeven figures.)*

**Session 16 addition:** TB/under's own leg-level win rate confirmed still solidly above breakeven post null-signal-fix (57.9-59.4%, vs. ~39.1% breakeven). The promotion question is no longer about signal quality — see [TB/under Parlay-Level Combinatorial Drag](#tbunder-parlay-level-combinatorial-drag-session-16).

---

## Coverage Gating Architecture

*(Unchanged from Session 15.)*

---

## Parlay Construction Evolution

### **Phase 3.7: CLR Player Cap + TB Exclusion + Fallback Composition Fix (June 18, 2026)**
### **Phase 3.8: Batting Order Slot Gate Removed From Both Scoring and CLR Trigger (July 2, 2026) — CURRENT**

See [Batting Order Slot Gate — Removal](#batting-order-slot-gate--removal-session-16) for full detail.

---

## Player Diversity — Cross-Run Cap

*(Unchanged from Session 15.)*

---

## Odds Cap Decision

*(Unchanged.)*

---

## Coverage Signal Architecture

*(Unchanged.)*

---

## Pitcher Signal Pipeline

*(Unchanged from Session 15 — see that section for the K/9-direction correction and hits/over vulnerability penalty detail. Re-evaluation of K/9 and WHIP against starter-only rank data remains scheduled for ~July 9.)*

---

## Shadow Pipeline Strategy

### **Decision: Shadow Pipeline as Signal Validation Layer**

*(Unchanged framing from Session 15.)*

**Session 16 finding — shadow's per-leg scoring advantage is now quantified and confirmed real, not noise:**

Comparing shadow vs. production on identical props over the same 7-day window (June 24 – July 1):

| Prop | Shadow Leg WR | Production Leg WR | Delta |
|---|---|---|---|
| hits/over | 66.7% (n=78) | 61.8% (n=152) | +4.9pp |
| strikeouts/over | 77.0% (n=100) | 72.1% (n=61) | +4.9pp |

Identical +4.9pp delta on both props, in the same direction, is a meaningful signal rather than sampling noise. Shadow's enriched scoring (pitcher vulnerability, park factor, opponent-specific coverage) is producing better leg selection than production's simpler scorer on the props both pipelines share. This makes the blended shadow parlay win rate (16.5% vs. production's 30.0%) a misleading comparison on its own — see next section.

---

## Enriched Scoring Signals

*(Unchanged from Session 15.)*

**Session 16 confirmation:** the Session 15 TB/under null-signal fix (adding `totalBases` to `_PROP_STAT_MAP`, adding the park-adjustment branch, fixing direction inversion) is confirmed live in production data — `park_factor` populated on 588/707 TB/under legs (83.2%, was 0% pre-fix) and `coverage_vs_opponent` on 420/707 (59.4%, was 0% pre-fix). Not 100% population — likely reflects legitimate cases where underlying park/opponent data isn't available for a given matchup, not a residual bug, but not independently re-verified this session.

---

## Lineup Confirmation Layer

Event-driven annotation system. After 9AM pipeline, rows are written to `mlb_pending_lineup_checks` for each start-time group at T-45 and T-1. Drain cron polls every minute. On trigger, fetches live lineups via statsapi hydrate. Annotates each parlay leg with `batting_order` and `lineup_check_status` (CONFIRMED/OUT_OF_RANGE/SCRATCHED/MISSING).

**Session 16 change:** Previously, both `SCRATCHED` and `BATTING_ORDER_OUT_OF_RANGE` triggered `CONFIRMED_LINEUP_RESOLUTION` (rebuild/void). As of July 2, 2026, **only `SCRATCHED` triggers a rebuild.** `BATTING_ORDER_OUT_OF_RANGE` remains fully annotated on every leg but no longer causes a void. See [Batting Order Slot Gate — Removal](#batting-order-slot-gate--removal-session-16) for the data behind this change.

**CLR pool rules (Session 14, unchanged):**
- TB/under excluded from CLR replacement pool (mirrors `main.py` production exclusion)
- Cross-iteration player cap: max 1 player appearance per CLR batch via `used_replacement_player_ids`
- Any future production exclusions in `main.py` must be explicitly mirrored in CLR pool construction

**Annotation health confirmed (Session 16, 7-day window):** 80.0% `LINEUP_CONFIRMED`, 7.0% `SCRATCHED`, 4.0% `BATTING_ORDER_OUT_OF_RANGE`, 8.9% never checked. 91.1% of legs receive some annotation — the check-firing mechanism itself is healthy; the issue was purely in which annotations caused a rebuild.

---

## CLV Tracking Layer

*(Unchanged.)*

---

## Backtest Harness

*(Unchanged from Session 15 — note the original June 12 "slot gate" backtest variant tested only the scoring-penalty direction, not the CLR-trigger question. Session 16's void investigation is the first analysis to isolate the CLR-trigger cost specifically.)*

---

## Outcome Resolution

*(Unchanged.)*

**Session 16 finding — `void_reason` on `mlb_scored_legs` is not a usable diagnostic field.** Of 68 voided legs in the 7-day review window, 66 (97%) had `void_reason = NULL`; only 2 had a populated reason (`stat_extraction_failed`). The void investigation this session instead joined `mlb_parlay_recommendations_v2.superseded_reason` to `mlb_parlay_legs_v2.lineup_check_status`, which worked cleanly and fully explained 100% of the 78 voided parlays in the window. `void_reason`'s logging gap is not yet fixed — flagged in `SESSION_HANDOFF.md` pending items.

---

## Database Design

*(Unchanged — see prior version for natural key rules, PostgreSQL conventions, schema change log, and clean-data cutoffs.)*

---

## Pipeline Architecture

*(Unchanged structurally. The CLR rebuild trigger condition described in this section's prior versions — "on SCRATCHED/OUT_OF_RANGE" — is superseded; see below.)*

- **On SCRATCHED only** — CONFIRMED_LINEUP_RESOLUTION rebuild (TB/under excluded, 1x player cap). *(Updated Session 16 — was "on SCRATCHED/OUT_OF_RANGE.")*

---

## Batting Order Slot Gate — Removal (Session 16)

### **Decision: Remove Both the -8 Scoring Penalty and the OUT_OF_RANGE CLR Trigger**

**Background:** The June 12, 2026 slot-gate backtest (see Backtest Harness) found `BATTING_ORDER_FAVORABLE` ranges (slots 1-5 for hits/over, 1-6 for strikeouts/over) contradicted by the data available at the time — "unfavorable" slots 6-9 and 7-9 won at 66.7% vs. 61.2% for the "favorable" slots. The team's decision then (Lesson 32) was "keep annotation, don't gate" — i.e., don't build a *new* hard exclusion off a contradicted hypothesis. However, the pre-existing -8 soft penalty in `simple_scorer.py`, and the OUT_OF_RANGE→CLR-rebuild wiring already in `lineup_confirmation.py`, were both left running.

**Session 16 re-test (7 days, June 24 – July 1):**

| Prop | Protected slots | Penalized slots |
|---|---|---|
| hits/over | 1-5: 60.0% WR (n=205) | 6-9: **63.3% WR** (n=30) |
| strikeouts/over | 1-6: 67.8% WR (n=87) | 7-9: **73.7% WR** (n=19) |

Same direction as June 12, on both props independently, three weeks later. The hypothesis is not a one-time fluke — it has now failed to hold up twice, three weeks apart. Continuing to "monitor" a contradiction that repeats is not different from acting on a wrong assumption; the decision was made to remove it.

**Void cost, quantified for the first time this session:** joining `superseded_reason` to `lineup_check_status` for all 78 voided production parlays in the 7-day window showed `BATTING_ORDER_OUT_OF_RANGE` present in 60/78 (76.9%), and **35/78 (44.9%) voided from OUT_OF_RANGE alone with no scratched player involved** — i.e., the selected player genuinely was in the starting lineup, and CLR rebuilt the parlay solely because of the contradicted slot assumption.

**Decision:**
1. Remove the -8 scoring penalty entirely — go neutral, do not flip the direction to reward slots 6-9/7-9 instead (the "penalized" sample sizes, 19-30 legs, are large enough to say "contradicted" but not large enough to establish a new correct direction).
2. Downgrade `BATTING_ORDER_OUT_OF_RANGE` from a CLR rebuild trigger to annotation-only. `SCRATCHED` remains the sole rebuild trigger — it's a factual roster state (player absent from the lineup entirely), not a statistical judgment call, and was not implicated in this contradiction.
3. Keep collecting `batting_order` / `lineup_check_status` annotation data on every leg regardless — cheap, already working (80% confirmation rate), and it's exactly what surfaced this issue in the first place. A future session with a larger, now-unbiased sample (no longer skewed by the scoring penalty influencing which legs get selected) may reveal a real pattern, a different one, or none at all.

**Implementation:** `src/engine/simple_scorer.py` (removed penalty block), `src/apis/lineup_confirmation.py` (`_find_affected_parlays()` and `run_confirmed_lineup_resolution()` both changed to filter on `SCRATCHED` only). Deployed as commit `4cd3c37`, July 2, 2026. See `SESSION_HANDOFF.md` for post-deploy test results and the July 5-6 recheck plan.

---

## TB/under Parlay-Level Combinatorial Drag (Session 16)

### **Finding: TB/under's Leg-Level Edge Is Real; Its Parlay-Level Drag Is Structural, Not a Signal Bug**

Session 16's 7-day review found shadow's blended parlay win rate (16.5%) looked worse than production's (30.0%), which appeared to contradict shadow's per-leg scoring being measurably better than production's on shared props (+4.9pp on both hits/over and strikeouts/over — see Shadow Pipeline Strategy above).

Isolating TB/under (50.6% of shadow's leg volume) resolved the apparent contradiction:

| Segment | Resolved | Won | Win Rate |
|---|---|---|---|
| Shadow — with TB/under leg | 87 | 12 | 13.8% |
| Shadow — without TB/under leg | 10 | 4 | 40.0% |
| Production | 60 | 18 | 30.0% |

TB/under's own leg win rate (57.9-59.4%) remains solidly above its ~39.1% breakeven — it is not a broken or negative-edge signal. But a 4-leg parlay's win probability is closer to the *product* of its legs' win rates than their average, since every leg must hit. Mixing a 58-59%-win-rate prop into the same flat pool as 67-77%-win-rate props mathematically caps the blended parlay win rate below what the stronger props alone would produce — independent of any signal-quality issue.

**Decision: not yet made.** This is a parlay-construction-strategy question, not a scoring fix, and is deliberately not bundled into the Session 16 slot-gate fix. Candidate approaches for a future session: segregated TB-only vs. non-TB parlay pools; leg-quality-weighted selection within the flat pool; or accepting the drag as a known tradeoff of TB/under promotion. See Future Considerations.

---

## Lessons Learned

*(Items 1-42 unchanged from prior version — see full list in git history / prior document version.)*

43. **A contradicted hypothesis that repeats on a second, independent sample is confirmed, not re-flagged for later.** The June 12 slot-gate finding (66.7% vs 61.2%) was treated as "monitor, don't act" at the time — reasonable with one data point. The July 2 re-test (63.3% vs 60.0% hits/over; 73.7% vs 67.8% SO/over) showed the same direction on both props independently, three weeks apart. Two independent confirmations of the same contradiction is sufficient grounds to act, not to keep monitoring indefinitely.

44. **A soft scoring penalty and a hard CLR rebuild trigger can share the same flawed assumption without either being individually flagged as "the big one."** The -8 penalty looked like a minor, bounded scoring adjustment. Separately, the OUT_OF_RANGE→CLR wiring looked like reasonable lineup-safety logic. Neither was obviously the primary problem in isolation — it took joining `superseded_reason` to `lineup_check_status` across all voided parlays to see that 76.9% of voids involved the same contradicted assumption driving both. When two independent-seeming mechanisms trace back to one shared premise, evaluate them together.

45. **A leg-level scoring comparison and a parlay-level win-rate comparison can point in opposite directions without either being wrong.** Shadow scored legs better than production on identical props (+4.9pp, both props) while producing a lower blended parlay win rate (16.5% vs 30.0%). Both facts were true simultaneously because parlay win probability is closer to a product than an average of constituent leg win rates — a weaker-but-still-profitable prop at high volume in the pool will drag down the blend even when every individual signal in the system is working correctly. Diagnose at the level the question is actually about: leg quality and parlay-construction strategy are different questions with different answers.

46. **A diagnostic column that exists in the schema is not the same as a diagnostic column that's populated.** `void_reason` was assumed to be the fastest path to root-causing the void spike, but was NULL for 97% of voided legs. The `superseded_reason` + `lineup_check_status` join was a reliable substitute this time, but the gap itself is worth fixing so the next investigation doesn't need a workaround.

---

## Future Considerations

*(Items 1-11 carried over from Session 15 — see prior version. New items below.)*

### **12. TB/under Parlay Construction Strategy (Session 16, ties to item 5 above)**
Before promoting TB/under to production parlays (previously targeted ~July 9), decide on a construction approach that avoids the combinatorial drag documented in this session — segregated pools vs. quality-weighted selection vs. accepting the tradeoff. Can be simulated against existing shadow leg data without new signal work.

### **13. Fix void_reason Logging Gap (Session 16)**
`void_reason` on `mlb_scored_legs` is NULL for 97% of voided legs. Investigate why the resolver isn't writing to this column and fix, so future void investigations don't require the `superseded_reason`/`lineup_check_status` workaround.

### **14. Re-evaluate Batting Order Slot Data With an Unbiased Sample (Post-Removal)**
Now that the -8 penalty no longer influences which legs get selected into parlays, a future session should re-pull the slot-level win rate breakdown with a larger, unbiased sample to see whether a real pattern exists (in either direction) or whether the June 12 / July 2 findings were themselves noise from a still-limited sample.

### **15. Confirm Origin of Commit 85b5bd5**
Landed on `origin/master` between Session 15 (`9eed486`) and Session 16 without a corresponding session doc entry. Rebase was clean; contents not yet traced.

---

**Architecture Status:** ✅ STABLE
**Last Major Change:** July 2, 2026 (batting order slot gate removed — both scoring penalty and CLR trigger)
**Next Architecture Review:** July 5-6, 2026 (slot-gate fix volume recheck) / ~July 9 (TB/under promotion + construction strategy, K/9/WHIP re-evaluation)
