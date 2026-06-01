# MLB Parlay Agent — Session Handoff
**Last Updated:** June 1, 2026 (Session 4 — Performance Diagnosis + Full System Refactor)

## Current Status
✅ **OPERATIONAL — SESSION 4 DEPLOYED**
✅ **EEP false-void bug fixed and backfilled (May 29–June 1)**
✅ **Prop whitelist narrowed to hits o/u 0.5 + SO over 0.5 (hitter only)**
✅ **Anchor/swing system eliminated — single flat pool**
✅ **4-leg parlays, +400 to +700 target**
✅ **-250 odds cap**
✅ **3 production parlays built on June 1 (+613, +447, +419)**
✅ **Shadow pipeline producing 4 parlays independently**
✅ **Training data preserved and logging**

---

## What Happened on June 1, 2026

### EEP Bug Fix (Morning)
- Diagnosed Early Exit Protection false-void bug: `plateAppearances` and `battersFaced` defaulting to `0` when `boxscore_data()` returned empty stats dict, voiding every batter leg
- Fixed in `src/tracker/parlay_outcome_resolver.py`: both EEP checks now use `is not None` guard
- Also fixed `all_resolved` dead code: `game_not_found` path now defers parlay instead of voiding leg
- Backfilled May 29–June 1: 43 void parlays re-resolved → 3 won (May 30: 2, May 31: 1), rest correctly marked lost
- Commit: `928b6c6`

### Performance Diagnosis
Ran full 60-day data analysis across all prop types. Key findings:
- **Coverage IS predictive** for `hits over 0.5` (50% → 75% win rate across coverage buckets) and `SO over 0.5` (41% → 91%)
- **Coverage is NOT predictive** for `totalBases under 1.5` (flat 57-63% at all coverage levels) and `rbi under 0.5` (flat 67-77% — book prices away the edge, avg odds -280 to -348)
- **Pitcher SO** — coverage_overall missing for 55%+ of legs, win rates 30-52% across all lines. Cut entirely.
- **Parlay-level finding:** Higher coverage parlays NOT winning more (75-79% coverage bucket wins 5.0% vs 65-69% at 8.1%). Coverage alone is insufficient for parlay selection.
- **Hits under 0.5:** Only 24 appearances above 65% coverage — too thin to rely on
- **RBI under:** Flat signal, book prices it at -270 to -348. No edge at any coverage level.

### Full System Refactor (Afternoon)
Three commits deployed:

**Commit `885a4a7` — Prop whitelist + 3-leg parlays:**
- `ALLOWED_PROPS` whitelist: only `hits over 0.5`, `hits under 0.5`, `strikeouts over 0.5` (hitter)
- 3-leg parlays, +300 to +550 target
- Hard -200 odds cap
- Removed: totalBases, rbi, walks, pitcher SO, homeRuns, stolenBases
- Removed dead signals: pitcher ERA block, pitcher K9 branch, `calculate_pitcher_k_coverage()`, team SO signal (Signal 4)
- Shadow pipeline aligned: Signal 4 removed, Signals 1-3 retained

**Commit `351ec61` — Anchor floor fix:**
- Lowered anchor floor from 75% to 65% — upstream gate already enforces 65%
- ANCHOR_MAX_ODDS: -150 → -130
- SWING_MIN_ODDS: -150 → -129 (closed dead zone between pools)

**Commit `1ebbb24` — Single flat pool + 4-leg parlays:**
- Eliminated anchor/swing two-pool system entirely
- Single pool: 65% coverage, odds -250 to +150
- 4-leg parlays, +400 to +700 target
- `build_parlays()` replaces `build_hybrid_parlays()` (kept as backward-compat wrapper)
- `_find_qualifying_legs()` returns single `list[dict]` instead of tuple
- 238 lines removed from parlay_builder.py
- Shadow pipeline updated: `build_hybrid_parlays(enriched_legs, [], ...)`

---

## Pending Items — Next Session

### 1. Monitor June 2 Morning Resolution (Manual — 9 AM)
First morning resolution after EEP fix goes live on a full day's worth of new parlays. Verify:
```sql
SELECT void_reason, COUNT(*)
FROM mlb_parlay_legs_v2
WHERE outcome = 'void'
  AND created_at >= NOW() - INTERVAL '24 hours'
GROUP BY void_reason;
```
Should see 0 or very few `early_exit_protection` voids. Any that appear should be genuine (player removed before facing 5 batters / recording 2 PAs).

### 2. Monitor Parlay Win Rates on New Prop Set (Ongoing)
First clean data under the new system starts June 1. Check after 7 days:
```sql
SELECT
    run_date,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2
WHERE run_date >= '2026-06-01'
GROUP BY run_date
ORDER BY run_date;
```

### 3. Negative EV Legs in Parlay Selection (Discuss)
Several legs in today's parlays show negative EV (e.g. Spencer Steer hits over -205 at EV=-17.2%). The composite score selects by coverage/consistency, not EV. Consider whether a minimum EV threshold should gate parlay selection — but don't implement until 7+ days of outcome data on the new system.

### 4. Shadow vs Production Comparison (June 8+)
Shadow pipeline now fully aligned with new prop set and single pool. After 7 days:
```sql
SELECT
    'production' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2
WHERE run_date >= '2026-06-01'
UNION ALL
SELECT
    'shadow' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_enriched
WHERE run_date >= '2026-06-01';
```

### 5. Health Check Alerts (Low Priority)
Two persistent health warnings in logs:
- `RESOLVER FAILURE: 254 props unresolved (>40%) for 2026-04-02` — stale April data, not affecting current operation
- `HIT RATE HIGH: 64.9% over last 7 days` — this is expected and correct given the 65%+ coverage gate. The health check threshold (40-58%) was calibrated for the old system. Update the expected range to 63-72% to match the new prop set.

### 6. `won_with_void` Outcome Tracking (Low Priority)
Still not implemented. Parlays that win after a void leg are marked `won` same as clean wins. Deferred.

### 7. Dead ERA Adjustment Cleanup in simple_scorer.py (Low Priority)
`opponent_adjustment` returns 0 for 100% of legs — the ERA/pitcher adjustment block still exists but never fires. Remove in a future cleanup session.

---

## Key Data Points from Today

- 60-day analysis: `hits over 0.5` at 75-79% coverage wins 75.4% (1,199 appearances). `SO over 0.5` at 75-79% wins 73.7% (133 appearances).
- Parlay-level win rate across all coverage buckets: 5-8% regardless of avg_coverage — coverage alone insufficient
- RBI under avg odds at 85%+ coverage: -348 (breakeven 77.7%, actual win rate 77.0% — underwater)
- TB under 1.5: flat 57-63% win rate across ALL coverage buckets with 1,000+ appearances
- June 1 production parlays: +613, +447, +419 (4-leg each, 12 unique players)
- June 1 shadow parlays: +631, +529, +426, +402 (4-leg each, 16 unique players)
- Pool size at -250 cap: ~18-22 eligible legs on typical weekday, 30-45 on full weekend slates

---

## Commits Today
- `928b6c6` — EEP false-void fix + backfill script
- `885a4a7` — Prop whitelist, 3-leg +300-+550, remove dead signals
- `351ec61` — Anchor floor 65%, odds boundary fix
- `1ebbb24` — Single flat pool, 4-leg +400-+700, -250 cap, remove anchor/swing

---

## System Health Indicators

### Green Lights
✅ EEP void bug fixed and backfilled
✅ 3 production parlays built on first run with new system
✅ Shadow pipeline producing 4 parlays independently
✅ Single flat pool working — no anchor/swing starvation
✅ Training data logging (34 legs logged June 1)
✅ Coverage gate working: only hits o/u 0.5 and SO over 0.5 reaching builder
✅ Player diversity constraint working (12 unique players across 3 parlays)
✅ -250 odds cap recovering previously excluded legs

### Yellow Flags
⚠️ Negative EV legs appearing in parlays (selection by score, not EV)
⚠️ Health check hit rate threshold stale — needs updating to 63-72%
⚠️ Only 3 parlays on thin 9-game slate — normal, expect 4-5 on full slates
⚠️ `hits under 0.5` barely qualifying (70%+ gate, very few legs per day)

### Red Flags
None currently

---

**Last Review:** June 1, 2026
**System Status:** ✅ Operational — Single Pool + Validated Prop Set Live
**Next Review:** June 2, 2026 (Validate morning resolution + first full-day parlay quality)
**Pending Code Changes:** won_with_void tracking, health check threshold update, dead ERA cleanup
