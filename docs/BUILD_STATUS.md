# MLB Parlay Agent — Build Status
**Last Updated:** May 27, 2026 (Session 1 — Coverage Floor Fixes)

## Overall System Status: ✅ OPERATIONAL — SESSION 1 FIXES LIVE
```
┌────────────────────────────────────────────────────────────────┐
│                  SYSTEM HEALTH DASHBOARD                       │
├────────────────────────────────────────────────────────────────┤
│ Scoring System:          ✅ PHASE 1 SIMPLE SCORER LIVE        │
│ Coverage Gate (Gate 1):  ✅ coverage_overall >= 65% ENFORCED  │
│ TB Under Floor (Gate 2): ✅ 80% coverage_overall MINIMUM      │
│ SO Over 5.5 Floor:       ✅ 72% coverage_overall MINIMUM      │
│ Shadow Enriched Pipeline:✅ FULLY OPERATIONAL (filters inherited)│
│ Enriched Data Integrity: ✅ IDs, timestamps, links all valid  │
│ Prop Filtering:          ✅ BLOCKING UNPROFITABLE PROPS       │
│ Coverage Calculation:    ✅ VALIDATED (direction-aware)       │
│ Parlay Odds Range:       ✅ +700 TO +1000                     │
│ Juice Cap:               ✅ ACTIVE (blocks odds < -300)       │
│ Player Diversity:        ✅ ACTIVE (max 1 per batch)          │
│ Database Logging:        ✅ STABLE (all data persisting)      │
│ Training Data:           ✅ PRESERVED (94K+ rows)             │
│ Web UI:                  ✅ FUNCTIONAL (all tabs working)     │
│ Deployment:              ✅ LIVE (Railway auto-deploy)        │
│ 9AM Pipeline:            ✅ PRODUCING PARLAYS                 │
│ Next Review:             📊 May 29 (Friday — Session 2)       │
└────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🔧 **May 27, 2026: Session 1 — Coverage Floor Fixes**

**Commit:** `9f49aa3` (rebased from `c4c6eae`)
**File:** `main.py` — 14 lines added, 3 removed (lines 362–376)

**Problem solved:** The 65% coverage threshold was being applied to `coverage_vs_hand` (best available signal), which allowed `coverage_vs_hand` to rescue players whose `coverage_overall` was below threshold. José Ramírez (62–64% overall), Mookie Betts (67–70%), and Josh Naylor (67–70%) were all passing the gate and then getting further boosted by ERA/pitcher adjustments — despite being 0/8+ in parlays over the last 7 days.

Additionally, `totalBases under 1.5` had a 50.4% in-parlay win rate over the last 7 days (135 appearances), and `strikeouts over 5.5` had a 50.0% win rate with a clean threshold cliff at 72% coverage.

**Three changes in `_find_qualifying_legs()` in `main.py`:**

```python
# Gate 1: coverage_overall must clear 65% before adjustments
coverage_overall_raw = coverage.get("coverage_overall") or 0.0
if coverage_overall_raw < MIN_COVERAGE_PCT:
    continue

# Gate 2: prop-specific floors
if stat == "totalBases" and direction == "under" and line == 1.5:
    if coverage_overall_raw < 80.0:
        continue
if stat == "strikeouts" and direction == "over" and line == 5.5:
    if coverage_overall_raw < 72.0:
        continue

# Best available signal (vs-hand preferred, else overall)
coverage_pct = coverage.get("coverage_vs_hand") or coverage_overall_raw
```

**Verified in Railway logs:**
- Pool: 252 qualifying legs (reduced from ~290)
- 133 eligible after juice cap
- 3 parlays built — chronic bad actors gone from output
- Shadow pipeline confirmed inheriting filters (no changes needed)

**Status:** ✅ Live and validated

---

### 🔬 **May 26, 2026: Shadow Enriched Pipeline — Full Data Integrity Fix**
*(See previous BUILD_STATUS for full details)*

All enriched tables fully wired: IDs, `created_at`, `production_batch_id` all populating correctly.

---

### 🎯 **May 21, 2026: Parlay Strategy Optimization**
- Lowered parlay odds to +700–+1000
- Added juice cap (blocks odds < -300)
- Unblocked RBI props and Total Bases under

---

### 🎉 **May 20, 2026: Phase 1 Simple Scorer**
- Replaced ML model with coverage-based scoring
- Validated 69% accuracy on 7,895 resolved legs

---

## Component Status

### **1. Coverage Gating** ✅ FIXED (May 27)

**Before:** Gate ran on `coverage_vs_hand or coverage_overall`. A player with 55% overall and 70% vs-hand would pass.

**After:** Two-gate system:
- Gate 1: `coverage_overall >= 65%` — hard requirement, checked before any other signal
- Gate 2: Prop-specific floors applied after Gate 1
- `coverage_pct` for scoring still uses best available (vs-hand preferred), but only after both gates pass

### **2. Production Scoring System** ✅ PHASE 1 LIVE

```python
score = base_coverage + adjustments
# base_coverage = coverage_vs_hand (preferred) or coverage_overall
# adjustments = handedness (+3) + form (±4) + pitcher ERA (±5) + K-rate (±5) + stability (-5)
```

**Note:** Score-outcome correlation shows lost legs scoring slightly higher than won legs (75.5 vs 74.2). The ERA/K-rate adjustments may be adding noise. Under review for a future session.

### **3. Shadow Enriched Scorer** ✅ OPERATIONAL

Three signals running in shadow:
1. Blended ERA rank (season × 0.5 + last-3-start × 0.5)
2. Opponent-specific coverage split (min 3 games, 25% delta, ±8 cap)
3. Ballpark factor (30-row table, Coors 115 → Petco 94)

Signal 4 (consistency: `coverage_overall - coverage_recent_10` gap) being added Friday.

### **4. Prop Filtering** ✅ UPDATED

| Prop | Floor | 7-Day Win Rate | Status |
|---|---|---|---|
| `hits over 0.5` | 65% overall | 60.0% | ✅ Keep |
| `hits under 0.5` | 65% overall | 71.1% | ✅ Keep |
| `strikeouts over 0.5` | 65% overall | 57.6% | ✅ Monitor |
| `strikeouts over 3.5` | 65% overall | 76.9% | ✅ Keep |
| `strikeouts over 4.5` | 65% overall | 60.0% | ✅ Keep |
| `strikeouts over 5.5` | **72% overall** | 50.0% → better | ✅ Floor raised |
| `strikeouts over 6.5` | 65% overall | 68.4% | ✅ Keep |
| `strikeouts under 4.5` | 65% overall | 63.0% | ✅ Keep |
| `strikeouts under 5.5` | 65% overall | 85.7% | ✅ Prioritize |
| `totalBases under 1.5` | **80% overall** | 50.4% → better | ✅ Floor raised |
| `rbi under 0.5` | 65% overall | 58.3% | ✅ Monitor |
| `hitter K under 0.5` | — | 36.7% | ❌ Blocked |
| `pitcher K under <5.5` | — | ~45% | ⚠️ Pending block |
| Any prop < -300 | — | — | ❌ Blocked from parlays |

### **5. Parlay Builder** ✅ OPTIMIZED
- 4 legs per parlay
- +700 to +1000 combined odds
- Juice cap: props < -300 excluded
- Max 2 legs per game
- Max 1 leg per player per batch

### **6. Shadow Pipeline Tables** ✅ FULLY WIRED

| Table | Rows Today | ID Sequence | created_at | production_batch_id |
|---|---|---|---|---|
| `mlb_parlay_recommendations_enriched` | 3 | ✅ | ✅ | ✅ |
| `mlb_parlay_legs_enriched` | 12 | ✅ | ✅ | ✅ |
| `mlb_scored_legs_enriched` | ~217 | — | ✅ | — |
| `ballpark_factors` | 30 (static) | — | — | — |

---

## Performance Metrics

### **May 22–25 Results (Pre-Session 1)**

| Metric | Value | Target |
|---|---|---|
| Parlay win rate | ~11% | 18–22% |
| In-parlay leg win rate | 57.6% | 67%+ |
| `totalBases under 1.5` in-parlay win rate | 50.4% | ≥65% |
| `strikeouts over 5.5` in-parlay win rate | 50.0% | ≥65% |

### **Expected Post-Session 1**
- TB under 1.5 pool: only players with 80%+ coverage_overall (e.g. Ha-Seong Kim 100%, Tyler Freeman 80.4%)
- SO over 5.5 pool: only Cam Schlittler (81.8%), Landen Roupp (80%) tier — all 7-day winners
- Chronic bad actors (Mookie Betts, José Ramírez, Josh Naylor, Braxton Ashcraft) eliminated

---

## Pending Code Changes

| Item | File | Priority | Type |
|---|---|---|---|
| Consistency signal (coverage gap) | `src/engine/enriched_scorer.py` | High | Claude Code (Friday) |
| Pitcher K under line ≥5.5 | `main.py` | High | Claude Code (Friday) |
| `won_with_void` outcome tracking | `parlay_outcome_resolver.py` | Medium | Claude Code |
| Promote enriched to production | Multiple | After analysis | Claude Code (June) |

---

**Build Status:** ✅ HEALTHY — Session 1 Live, Session 2 Friday
**Last Deployment:** May 27, 2026 (commit `9f49aa3`)
**Next Review:** May 29, 2026 (Friday Session 2)
