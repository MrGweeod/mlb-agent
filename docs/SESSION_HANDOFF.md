# MLB Parlay Agent — Session Handoff
**Last Updated:** June 5, 2026 (Session 5 — Full System Diagnostic + Signal Pipeline Fixes)

## Current Status
✅ **OPERATIONAL — SESSION 5 DEPLOYED**
✅ **Bug 1 fixed: batter strikeout legs now fully enriched (pitcher_era, pitcher_k9, pitcher_hand)**
✅ **Pitcher IP threshold fixed: 192 qualified starters ranked (was ~20-25)**
✅ **Opposing pitcher rank signals now attached to ALL hitter legs (era_rank, k9_rank, whip_rank)**
✅ **simple_scorer K9 rank signal now firing for batter strikeout props**
✅ **Enriched scorer signal corrections deployed (base signal, ERA removal, K9 rank)**
✅ **Parlay builder: score-sort + MAX_CANDIDATES 50 deployed**
✅ **Shadow pipeline resolution backfilled (1,240 rows) and wired up ongoing**
✅ **All changes committed and pushed**

---

## What Happened on June 5, 2026

### Full System Diagnostic
Conducted a complete end-to-end audit of the pipeline, scoring system, and parlay builder. Key findings:

**Whitelist:** Confirmed working correctly in `main.py`. Historical pre-June-1 data (rbi under, totalBases) was causing confusion in performance queries — those props are correctly blocked in the current system.

**Shadow pipeline resolution:** `mlb_scored_legs_enriched.result` was NULL for all 1,240 rows across 10 days. Backfilled via bulk SQL UPDATE joining on `(player_name, stat, direction, run_date, line)`. Morning resolver now writes outcomes to shadow table after every production resolution.

**Bug 1 — `strikeouts` in `_PITCHER_STATS` in `enrich_legs.py`:** Every batter strikeout leg was hitting the pitcher prop branch due to `stat in _PITCHER_STATS`. Fixed to `is_pitcher_prop_leg = position in ("SP", "RP", "P")`. Now `pitcher_era`, `pitcher_k9`, `pitcher_hand` populate correctly for batter SO legs.

**Pitcher IP threshold:** `pitcher_stats.py` was using `ip < 50` season total filter, excluding Ohtani, Cole, Harrison, Arrighetti and other elite starters with <50 IP. Fixed to per-start filter: 3+ starts, 3.0+ IP/start. Ranked pool went from ~20-25 to 192 qualified starters.

**`_attach_pitcher_rank_signals()` skipping hitter legs:** `main.py` was only attaching `era_rank`, `k9_rank`, `whip_rank` to pitcher prop legs. All hitter legs were skipped entirely. Fixed to attach `opp_pitcher_era_rank`, `opp_pitcher_k9_rank`, `opp_pitcher_whip_rank` to hitter legs via `opposing_pitcher_id`.

**`simple_scorer.py` K9 signal:** Was reading raw `pitcher_k9` float with hardcoded thresholds (10.0/7.0). Updated to use `opp_pitcher_k9_rank` (ranked signal) with raw `pitcher_k9` as fallback. Unit test confirmed: elite K pitcher (rank 5) = 75, weak K pitcher (rank 25) = 65, no rank = 70.

**Parlay builder sort order:** Was sorting pool by decimal odds descending for B&B pruning. This caused low-quality, cheap-odds legs (Oneil Cruz score 59) to be explored before high-quality expensive legs (Waldschmidt score 78). Fixed to sort by `composite_score` descending. B&B pruning bounds fixed via `suffix_dec_sorted` precomputation to remain valid under any sort order.

**MAX_CANDIDATES:** Raised from 15 to 50. Builder now finds 50 valid combinations before stopping, giving `avg_composite` selector meaningful differentiation instead of 15 near-identical combinations.

**`coverage_vs_hand` validation:** Confirmed calculating correctly (values vary by pitcher hand per player). However produces values within 0.5 points of `coverage_overall` on average, with identical win rates (62.0% with vs 62.3% without). Retained as delta adjustment (30% weight, ±3 cap) in enriched scorer rather than base replacement.

**ERA rank signal:** Validated on shadow data. ERA rank was directionally unreliable for hits props due to 50 IP threshold contaminating the ranking pool. With IP threshold fixed, ERA signal needs re-evaluation after 1-2 weeks of clean data. Removed from enriched scorer scoring (still computed and stored for analysis).

**Park factor signal:** Validated as strongest enriched signal — 30-point win rate spread between pitcher parks (40%) and hitter parks (70%) for hits over. Retained as-is.

### Commits This Session
- `1ab63c2` — pitcher IP threshold, enrich_legs Bug1, enriched scorer signal corrections, parlay builder score-sort + MAX_CANDIDATES 50
- `e67896e` — attach opp pitcher rank signals to hitter legs, use k9_rank for SO scoring in simple_scorer

---

## Pending Items — Next Session

### 1. Verify Tomorrow Morning's 9 AM Pipeline (Manual — 9 AM)
First full pipeline run with all Session 5 fixes. Check Railway logs for:
- `[pitcher_stats] Ranked 192 qualified starters` — confirms IP threshold active
- Batter strikeout legs now show `pitcher_era` and `pitcher_k9` populated in enrich_legs sample log
- Score distribution shows meaningful spread for strikeout legs (not uniform 68-70)
- Parlay compositions lead with high-scoring legs

Run this after 9 AM to confirm K9 rank is flowing into scores:
```sql
SELECT
    player_name,
    stat,
    pitcher_name,
    pitcher_k9,
    coverage_overall,
    composite_score
FROM mlb_scored_legs
WHERE run_date = (CURRENT_DATE)::text
  AND stat = 'strikeouts'
  AND line = 0.5
  AND position NOT IN ('SP','RP','P')
ORDER BY composite_score DESC
LIMIT 15;
```
Expect meaningful score spread based on opposing pitcher K9 rank.

### 2. ERA Rank Signal Re-Evaluation (June 12+)
With the IP threshold fixed, ERA rank will now correctly identify elite starters. After 7+ days of clean data:
- Re-run ERA tier win rate analysis on `mlb_scored_legs_enriched`
- Determine whether to add ERA rank back as a scoring adjustment in enriched scorer
- Check directional correctness: do hits over legs actually win less often vs true aces (low ERA rank)?

### 3. Shadow vs Production Comparison (June 12+)
After 7 days of clean data under Session 5 changes:
```sql
SELECT
    'production' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2
WHERE run_date >= '2026-06-05'
UNION ALL
SELECT
    'shadow' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_enriched
WHERE run_date >= '2026-06-05';
```

### 4. Hits Under 0 Appearances in Pool
Today's pool showed `0 unders` reaching the builder. This reduces pool diversity and makes hitting the +400-+700 odds window harder. Investigate whether hits under legs are being blocked upstream (coverage gate too strict at 70%) or whether there simply aren't enough qualifying legs on typical slates.

### 5. Negative EV Legs in Parlay Selection
Several legs in recent parlays show negative EV (e.g. Alex Bregman -244 at EV=-20.9%). The scorer selects by coverage/consistency, not EV. After 30+ days of outcome data on the new system, evaluate whether a minimum EV gate improves parlay quality.

### 6. Update `supabase-query-builder` SKILL.md
Add anti-pattern: `ORDER BY` before `UNION ALL` causes syntax error. Use single `ORDER BY` at the end, or combine date ranges with `WHERE ... OR ...` on the same table.

### 7. Health Check Threshold Update (Low Priority)
Health check flags hit rate >58% as anomalous. With 65%+ coverage gate, expected range is 63-75%. Update threshold to avoid misleading log warnings.

### 8. Dead ERA Adjustment Cleanup in `simple_scorer.py` (Low Priority)
The raw `pitcher_era` block for hits props still exists but was validated as directionally unreliable. Remove after ERA rank signal is re-validated with clean data.

### 9. `won_with_void` Outcome Tracking (Low Priority)
Still not implemented.

---

## Key Data Findings From Today

- `coverage_vs_hand` produces values within 0.5 points of `coverage_overall` on average; win rates identical (62.0% vs 62.3%) — retained as ±3 delta adjustment only
- Park factor: strongest validated signal — 40% win rate in pitcher parks vs 70% in hitter parks for hits over
- ERA rank: unreliable until IP threshold fix; needs re-evaluation with clean data
- K9 rank: correct signal for batter strikeout props; unit test confirms 10-point spread elite vs weak
- Parlay builder sort fix: Waldschmidt (78), Rice (76.8), Turner (76.6) now leading parlays vs Cruz (59), Andujar (59) before fix
- Shadow resolution: 1,240 rows backfilled; ongoing resolution now wired up
- Pitcher ranks: 192 qualified (was ~20-25); Ohtani, Cole, Harrison now correctly included

---

## System Health Indicators

### Green Lights
✅ Bug 1 fixed — batter SO legs fully enriched
✅ Pitcher IP threshold fixed — 192 qualified starters
✅ Opposing pitcher ranks attached to hitter legs
✅ K9 rank signal firing in simple_scorer
✅ Parlay builder score-sort + MAX_CANDIDATES 50
✅ Shadow resolution backfilled and ongoing
✅ Park factor signal validated and active
✅ Enriched scorer corrections deployed
✅ All changes committed and pushed

### Yellow Flags
⚠️ ERA rank signal needs re-evaluation with clean data (7+ days post IP-fix)
⚠️ 0 hits under legs in today's pool — investigate coverage gate
⚠️ Negative EV legs still appearing in parlays
⚠️ Health check hit rate threshold stale (flags 63%+ as anomalous)

### Red Flags
None currently

---

**Last Review:** June 5, 2026
**System Status:** ✅ Operational — Full Signal Pipeline Fixed + Parlay Builder Corrected
**Next Review:** June 6, 2026 (Validate 9 AM pipeline + K9 rank in scores)
**Pending Code Changes:** ERA rank re-evaluation, hits under investigation, health check threshold, dead ERA cleanup
