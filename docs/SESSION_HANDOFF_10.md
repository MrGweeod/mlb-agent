# MLB Parlay Agent — Session Handoff
**Last Updated:** May 26, 2026 (Performance Analysis + Shadow Enriched Pipeline)

## Current Status
✅ **OPERATIONAL - PHASE 1 SIMPLE SCORER LIVE**
✅ **Parlay Odds Range: +700 to +1000**
✅ **Shadow Enriched Pipeline: FULLY OPERATIONAL**
✅ **Enriched Tables: Legs, recommendations, and timestamps all linking correctly**
✅ **Coverage Calculation Validated**

---

## What Happened on May 26, 2026

### **🔍 Performance Analysis — May 22–25 Results**

Ran full SQL diagnostic on post-strategy-change performance (May 22–25).

**Key findings:**

**Parlay win rate:** ~11% across ~74 resolved parlays (target: 18–22%)

**Leg-level accuracy (post-May-15 clean data):**
| Prop | Direction | Win Rate | Legs |
|---|---|---|---|
| Total Bases under | 75.0% | 68 |
| Hits over | 71.4% | 35 |
| Hits under | 69.0% | 42 |
| RBI under | 63.6% | 11 |
| Strikeouts over | 56.9% | 116 |
| Strikeouts under | 53.7% | 67 |

**Prop pool composition (May 22–25):**
| Prop | Share |
|---|---|
| Strikeouts over | 22.9% |
| Total Bases under | 22.3% |
| Strikeouts under | 21.8% |
| Hits under | 12.8% |
| Hits over | 10.6% |
| RBI under | 6.9% |
| Walks over | 2.7% |

**Weighted avg leg win rate: ~63.6% → expected parlay win rate: ~16.3%**
Actual 11% suggests same-game correlation dragging results below theoretical ceiling.

**5/24 deep dive:** 4/9 parlays won, but 2 of 4 wins required a voided leg to survive — not a repeatable edge. Identified that good days correlate with pitcher K unders at high lines (5.5+, 6.5) with strong coverage (75–80%).

**Pitcher strikeout under finding:** Losses concentrated at lines 4.5 and below. Winners (McClanahan 5.5, King 6.5, Gray 5.5, Sasaki 5.5) all at 5.5+. Recommendation: add line ≥ 5.5 minimum threshold for pitcher K unders — to be implemented in next Claude Code session.

**9AM pipeline confirmed working** — producing 4–5 parlays per morning run since May 22 (was broken per May 12 diagnostic).

---

### **🏟️ Three New Scoring Signals Designed**

Designed and scoped three enrichment signals to improve leg scoring:

1. **Pitcher last-3-start form** — blend season ERA rank (50%) with recent 3-start ERA rank (50%) for `blended_era_rank`
2. **Opponent-specific coverage splits** — batter's direction-aware hit rate vs tonight's specific opponent (min 3 games, 25% delta weight, ±8 cap)
3. **Ballpark factor adjustment** — park run/HR factor from `ballpark_factors` table (30 rows, Coors 115 → Petco 94)

---

### **🗄️ Supabase Changes Made**

Created the following tables/columns manually:

```sql
-- Ballpark factors (30 rows inserted)
CREATE TABLE ballpark_factors (team_abbrev, team_name, park_name, run_factor, hr_factor, last_updated)

-- Shadow tables
CREATE TABLE mlb_scored_legs_enriched  -- mirrors mlb_scored_legs + 6 enriched columns
CREATE TABLE mlb_parlay_recommendations_enriched  -- mirrors mlb_parlay_recommendations_v2 + production_batch_id
CREATE TABLE mlb_parlay_legs_enriched  -- mirrors mlb_parlay_legs_v2 + 6 enriched columns

-- Sequences for IDs
CREATE SEQUENCE mlb_parlay_recommendations_enriched_id_seq
CREATE SEQUENCE mlb_parlay_legs_enriched_id_seq

-- Defaults
ALTER TABLE mlb_parlay_recommendations_enriched ALTER COLUMN created_at SET DEFAULT NOW()
ALTER TABLE mlb_parlay_legs_enriched ALTER COLUMN created_at SET DEFAULT NOW()
ALTER TABLE mlb_parlay_recommendations_enriched ADD COLUMN production_batch_id TEXT
```

---

### **🔬 Shadow Enriched Pipeline: FULLY OPERATIONAL**

Built and deployed shadow pipeline that runs after every production pipeline run (scheduled + manual Regenerate Now).

**Architecture:**
- `src/engine/enriched_scorer.py` — three new signals on top of simple_scorer.py
- `src/pipelines/run_enriched_pipeline.py` — shadow pipeline, writes to enriched tables only
- `main.py` — try/except wrapper after production completes; production never blocked by enriched failures

**Data integrity confirmed:**
- ✅ `id` sequences working (dedicated sequences per enriched table)
- ✅ `parlay_id` linking legs to parent parlays correctly
- ✅ `created_at` auto-populated via `NOW()` default
- ✅ `production_batch_id` populated — links enriched run to exact production batch it shadowed

**Verification query (run anytime to check enriched data):**
```sql
SELECT 
    p.id, p.batch_id, p.created_at, p.production_batch_id,
    l.parlay_id, l.player_name, l.stat, l.direction
FROM mlb_parlay_recommendations_enriched p
JOIN mlb_parlay_legs_enriched l ON l.parlay_id = p.id
WHERE p.run_date = CURRENT_DATE
ORDER BY p.rank, l.player_name;
```

---

## Pending Items — Next Session

### **1. Pitcher Strikeout Under Line Threshold (Claude Code)**
Block pitcher K unders below line 5.5 in `main.py`. Losses concentrated at 4.5 and below, winners at 5.5+.

```python
# Add to existing filter block in main.py
if stat == "strikeouts" and direction == "under" and float(line) < 5.5:
    continue
```

Confirm whether `line` is string or numeric at that point in the pipeline before Claude Code touches it.

### **2. Won-With-Void Parlay Tracking (Claude Code)**
Add `"won_with_void"` outcome value for parlays that won only because a leg voided. Requires change to `src/tracker/parlay_outcome_resolver.py` in the `recalculate_parlay_outcome()` function.

### **3. Shadow Pipeline Comparison Analysis (5–7 Days)**
Let enriched pipeline collect data through May 27–June 2. Then run comparison queries:
- Same `production_batch_id` joins production and enriched parlays
- Compare leg selection differences
- Compare win rates by pipeline
- Decide whether to promote enriched scoring to production

---

## Side-by-Side Comparison Query (Use After 5–7 Days)

```sql
SELECT
    'production' as pipeline,
    p.rank, p.total_odds, p.outcome,
    l.player_name, l.stat, l.direction, l.line,
    l.odds::numeric as odds, l.coverage::numeric(5,1) as coverage,
    l.outcome as leg_outcome
FROM mlb_parlay_recommendations_v2 p
JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
WHERE p.batch_id IN (
    SELECT DISTINCT production_batch_id 
    FROM mlb_parlay_recommendations_enriched
    WHERE run_date >= CURRENT_DATE - INTERVAL '7 days'
)

UNION ALL

SELECT
    'enriched' as pipeline,
    p.rank, p.total_odds, p.outcome,
    l.player_name, l.stat, l.direction, l.line,
    l.odds::numeric as odds, l.coverage::numeric(5,1) as coverage,
    l.outcome as leg_outcome
FROM mlb_parlay_recommendations_enriched p
JOIN mlb_parlay_legs_enriched l ON l.parlay_id = p.id
WHERE p.run_date >= CURRENT_DATE - INTERVAL '7 days'

ORDER BY pipeline DESC, rank, player_name;
```

---

## System Health Indicators

### **Green Lights**
- ✅ 3–5 parlays per run
- ✅ All parlays within +700–+1000
- ✅ Enriched pipeline completing after every production run
- ✅ No props < -300 in parlays (juice cap working)
- ✅ Player diversity enforced
- ✅ Pipeline scheduler reliable (3x daily)
- ✅ 9AM morning pipeline producing parlays

### **Yellow Flags**
- ⚠️ Parlay win rate at ~11% (target 18–22%) — monitor closely
- ⚠️ Pitcher K unders at 53.7% — line threshold fix pending

### **Red Flags**
- 🔴 Enriched pipeline errors blocking — check try/except in main.py
- 🔴 `production_batch_id` NULL on enriched rows — means batch capture broke

---

## Quick Commands

```bash
# Check Railway logs
railway logs --follow

# Manual pipeline trigger
curl -X POST https://mlb-agent.up.railway.app/api/refresh \
  -H "Authorization: Bearer MLBparlays"
```

---

**Last Review:** May 26, 2026  
**System Status:** ✅ Operational — Shadow Pipeline Active  
**Next Review:** June 1–2, 2026 (Shadow Pipeline Comparison Analysis)  
**Pending Code Changes:** Pitcher K under line threshold (≥5.5), won_with_void tracking
