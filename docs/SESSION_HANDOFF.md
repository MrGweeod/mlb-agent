# MLB Parlay Agent — Session Handoff
**Last Updated:** May 27, 2026 (Session 1 — Coverage Floor Fixes Deployed)

## Current Status
✅ **OPERATIONAL — SESSION 1 FIXES LIVE**
✅ **Coverage floor gating on `coverage_overall` before adjustments**
✅ **`totalBases under 1.5` minimum 80% `coverage_overall`**
✅ **`strikeouts over 5.5` minimum 72% `coverage_overall`**
✅ **Shadow Enriched Pipeline: Fully Operational (inherits new filters)**
✅ **Parlay Odds Range: +700 to +1000**

---

## What Happened on May 27, 2026

### **🔍 Performance Analysis — Identified Root Cause of Poor Parlay Win Rate**

Ran deep diagnostic analysis on parlay leg win rates comparing all-time vs last 7 days.

**Key findings:**

**In-parlay leg win rate is only 57.6%** — not the 66.7% headline from training data. The training data hit rate is carried by high-juice props (-300 to -460) that the parlay builder can't use to reach +700 odds. The legs that actually appear in parlays were hitting at ~50% on the most common categories.

**7-day in-parlay win rates by category:**

| Leg | Appearances | Win Rate | Action |
|---|---|---|---|
| `totalBases under 1.5` | 135 | 50.4% | 🚫 80% floor added |
| `strikeouts over 5.5` | 31 | 50.0% | 🚫 72% floor added |
| `strikeouts over 0.5` | 37 | 57.6% | ✅ Monitor |
| `hits over 0.5` | 31 | 60.0% | ✅ Keep |
| `strikeouts under 4.5` | 27 | 63.0% | ✅ Keep |
| `strikeouts over 6.5` | 19 | 68.4% | ✅ Keep |
| `hits under 0.5` | 53 | 71.1% | ✅ Keep |
| `strikeouts under 5.5` | 16 | 85.7% | ✅ Prioritize |

**Root cause of floor abuse:** `coverage_vs_hand` adjustments were inflating marginal players (62–65% `coverage_overall`) over the 65% threshold. José Ramírez was passing at 62–64% overall, Mookie Betts and Josh Naylor at borderline 67–70% but then getting boosted by ERA/pitcher adjustments into parlay-eligible territory. All three were 0/8+ over the last 7 days.

**Score-outcome correlation is inverted:** Lost parlay legs averaged score 75.5, won parlay legs averaged 74.2. Contextual adjustments (ERA ±5, K/9 ±5) are adding noise, not signal.

---

### **🔧 Session 1 — Three Fixes Deployed to Production**

**Commit:** `c4c6eae` → rebased → `9f49aa3`
**File modified:** `main.py` (lines 362–376)

**Change 1 — Gate on `coverage_overall` before adjustments (Gate 1):**
```python
coverage_overall_raw = coverage.get("coverage_overall") or 0.0
if coverage_overall_raw < MIN_COVERAGE_PCT:  # 65%
    continue
```
A player with `coverage_overall=55%` and `coverage_vs_hand=70%` is now correctly rejected. Previously, `coverage_vs_hand` could rescue a subthreshold player.

**Change 2 — 80% floor for `totalBases under 1.5` (Gate 2):**
```python
if stat == "totalBases" and direction == "under" and line == 1.5:
    if coverage_overall_raw < 80.0:
        continue
```

**Change 3 — 72% floor for `strikeouts over 5.5` (Gate 2):**
```python
if stat == "strikeouts" and direction == "over" and line == 5.5:
    if coverage_overall_raw < 72.0:
        continue
```

**Railway deployment confirmed working.** From today's pipeline logs:
- Pool: 252 qualifying legs (down from ~290)
- 133 eligible after juice cap
- 3 parlays built — no Mookie Betts, José Ramírez, Josh Naylor, or Braxton Ashcraft
- Shadow pipeline confirmed inheriting filters (receives `qualifying_legs` directly from `main.py`)

---

### **💡 Consistency Signal — Designed for Friday Session 2**

Identified that `coverage_recent_10` is populated at 95–97% across all 7 days (confirmed via query). Both `coverage_overall` and `coverage_recent_10` are computed correctly as precise percentages in `_hitter_coverage()` in `src/engine/coverage.py`.

**Consistency signal to be added to `enriched_scorer.py` on Friday:**
```python
gap = coverage_overall - coverage_recent_10

if gap >= 20:       consistency_adj = -6   # severe cold streak
elif gap >= 12:     consistency_adj = -4   # moderate cold streak
elif gap >= 6:      consistency_adj = -2   # mild cooling off
elif gap <= -10:    consistency_adj = +4   # meaningfully hot
elif gap <= -5:     consistency_adj = +2   # slightly hot
else:               consistency_adj = 0    # neutral
```

---

## Pending Items — Next Session (Friday May 29)

### **1. Consistency Signal in Shadow Enriched Scorer (Claude Code)**
Add as Signal 4 in `src/engine/enriched_scorer.py`. Before writing code, confirm:
- Where signals 1–3 are applied in the file (slot in same pattern)
- That `coverage_recent_10` is being passed into the enriched scorer from the pipeline

### **2. Pitcher K Under Line Threshold (Claude Code)**
Block pitcher K unders below line 5.5 in `main.py`. Still pending from last week.
```python
if stat == "strikeouts" and direction == "under" and float(line) < 5.5:
    continue
```

### **3. `won_with_void` Outcome Tracking (Claude Code)**
Add `"won_with_void"` outcome value in `src/tracker/parlay_outcome_resolver.py`. Medium priority.

---

## Longer-Term Considerations

**Scoring adjustments may be doing more harm than good.** The inverted score-outcome correlation (lost legs score higher than won legs) suggests the ±5 ERA and ±5 K/9 adjustments in `simple_scorer.py` are adding noise. After the consistency signal is evaluated in the shadow pipeline, consider reducing or removing these adjustments in a future session.

**Shadow pipeline comparison analysis** — June 1–2 as planned. Now has cleaner data starting May 27 with the new filters in place.

---

## System Health Indicators

### **Green Lights**
- ✅ 3 parlays per run (down from 36 but higher quality)
- ✅ All parlays within +700–+1000
- ✅ No Mookie Betts / José Ramírez / Josh Naylor TB under in pool
- ✅ Coverage gate correctly blocking floor-abuse cases
- ✅ Shadow pipeline inheriting production filters
- ✅ Pipeline scheduler reliable (3x daily)
- ✅ 9AM morning pipeline producing parlays

### **Yellow Flags**
- ⚠️ Parlay win rate at ~11% — Session 1 fixes should improve this, monitor over next 5–7 days
- ⚠️ Pitcher K under line threshold still not implemented
- ⚠️ Score-outcome correlation still inverted — scoring adjustments under review

### **Red Flags**
- 🔴 Health check flagging `HIT RATE HIGH: 67.5%` — likely selection bias from new filters, monitor

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

**Last Review:** May 27, 2026
**System Status:** ✅ Operational — Session 1 Fixes Live
**Next Review:** May 29, 2026 (Consistency Signal + Pitcher K Under Threshold)
**Pending Code Changes:** Consistency signal (enriched scorer), pitcher K under ≥5.5 threshold, won_with_void tracking
