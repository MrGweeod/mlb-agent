# MLB Parlay Agent — Architecture Decisions
**Last Updated:** May 20, 2026 (Phase 1 Simple Scorer Deployed)

This document captures the key architectural and design decisions made during the development of the MLB Parlay Agent, along with the reasoning behind each choice and lessons learned.

---

## Table of Contents
1. [Core Philosophy](#core-philosophy)
2. [Scoring System Evolution](#scoring-system-evolution) ← **NEW**
3. [Coverage Calculation](#coverage-calculation)
4. [Prop Type Filtering](#prop-type-filtering)
5. [Player Diversity Constraint](#player-diversity-constraint)
6. [Parlay Construction](#parlay-construction)
7. [Database Design](#database-design)
8. [Pipeline Architecture](#pipeline-architecture)
9. [Lessons Learned](#lessons-learned)
10. [Future Considerations](#future-considerations)

---

## Core Philosophy

### **Decision: Optimize for Hit Probability, Not Expected Value**

**Rationale:**
- Parlays multiply probabilities, so each leg's hit rate is paramount
- A 75% coverage leg at -150 is better than a 65% leg at +120 for parlay construction
- Expected value (EV) matters less when building 4-leg parlays (+900-1500 range)
- Psychological factor: Users prefer consistent small wins over rare big wins

**Implementation:**
- Primary scorer: Coverage percentage (0-100%)
- Secondary signals: Opponent pitcher adjustment, trend consistency
- EV calculated but not weighted in leg selection

**Trade-offs:**
- ✅ Higher parlay win rates (target 15-25% for 4-leg)
- ✅ More predictable outcomes
- ❌ May pass on high-EV value plays
- ❌ Negative EV on individual legs acceptable

**Validation:** ✅ **Confirmed May 20, 2026** - Profit analysis showed 69% accuracy on coverage-based leg selection

---

## Scoring System Evolution

### **THE JOURNEY: From ML to Simple Coverage-Based Scoring**

This section documents one of the most important architectural decisions: abandoning a complex ML model in favor of transparent coverage-based scoring.

---

### **Phase 0: Initial ML Model (April-May 2026)**

**Architecture:**
- GradientBoostingClassifier with 19 features
- Isotonic calibration (stat-specific)
- Temporary adjustments for direction bias

**Features:**
```
coverage_overall, coverage_vs_hand, coverage_recent_10,
coverage_recent_5, pitcher_quality, opponent_offense,
line, direction (77% feature importance!),
+ 11 stat one-hot features (hits, rbi, strikeouts, etc.)
```

**What It Produced:**
```python
base_prediction = gbm.predict_proba(features)[1]  # 0-1 probability
calibrated = isotonic_calibrator.transform(base_prediction)
score = calibrated + direction_adjustment + odds_penalty + same_game_penalty
score = max(5, min(95, score))  # Floor and ceiling
```

**The Problem:**
- Direction feature absorbed **77% of feature importance**
- Model learned "unders usually cover" from training data
- But in reality: **overs win 60%, unders win 30%**
- Result: High scores (70-100) had **43.7% win rate**, low scores (<55) had **55.1% win rate**
- **Score-outcome correlation was INVERTED**

**Why It Failed:**
The model was trained on "coverage %" as the target (how often the bet covered), not actual betting outcomes. Low lines (0.5 hits) made unders mathematically cover more often in historical data, so the model learned "under = good." But in actual DraftKings pricing, unders are overbet and lose money.

**Temporary Fixes Tried:**
- Direction penalty: -26 for unders, +18 for overs
- Odds penalties: -15 for long-odds unders
- Same-game penalty: -20
- **Result:** Scores collapsed to 5.0 (floor) or 47.98 (near-constant). Discrimination lost.

**Parlay Win Rate:** **7.6%** (barely breakeven, losing money)

---

### **Phase 1: Simple Coverage-Based Scoring (May 20, 2026)**

**The Turning Point:**

On May 20, 2026, ran profit analysis on 7,895 resolved legs with coverage_pct >= 65%:

| Prop Type | Direction | Win Rate | Profit per $1 | Verdict |
|-----------|-----------|----------|---------------|---------|
| Strikeouts | Over (pitcher) | 69.3% | +$0.54 | ✅ KEEP |
| Hits | Over | 69.4% | +$0.32 | ✅ KEEP |
| Hits | Under | 73.1% | +$0.14 | ✅ KEEP |
| Strikeouts | Under (hitter) | 36.7% | -$0.32 | ❌ BLOCK |
| Total Bases | Under | 59.7% | -$0.10 | ❌ BLOCK |

**Key Insight:** Raw coverage calculation already worked (69% accuracy). The ML model was corrupting a good signal.

**Decision:** Remove ML model entirely. Use coverage + simple contextual adjustments.

---

### **Phase 1 Implementation**

**New Scoring Formula:**
```python
score = base_coverage + contextual_adjustments

Where:
base_coverage = coverage_vs_hand (if available) or coverage_overall

adjustments:
  + 3  if has handedness split data (more reliable)
  ± 4  if recent form diverges >15 points (hot/cold)
  ± 5  for pitcher ERA quality (weak >5.0, ace <3.0)
  ± 5  for pitcher K/9 on strikeout props
  - 5  if lineup consistency < 50% (platoon risk)

Final: max(5, min(95, score))
```

**What It Uses (Already in Database):**
- `coverage_vs_hand` - handedness-specific hit rate
- `coverage_overall` - overall hit rate
- `coverage_recent_10` - hot/cold streaks
- `pitcher_era` - opponent quality
- `pitcher_k9` - strikeout rate
- `lineup_consistency` - playing time stability

**What It Doesn't Use:**
- ❌ ML model predictions
- ❌ Direction as a feature (only for adjustments)
- ❌ Calibration
- ❌ Temporary penalties that override base signal

**Code Location:** `src/engine/simple_scorer.py`

---

### **Phase 1 Results (May 20, 2026)**

**First Production Run:**
```
[simple_scorer] Scored 91 legs | avg=72.4 | min=58.0 | max=89.0
```

**Comparison to ML Model:**

| Metric | ML Model | Simple Scorer |
|--------|----------|---------------|
| Score distribution | Bimodal (5.0 or 47.98) | Normal (58-89) |
| Transparency | Opaque (19 features) | Clear (5 adjustments) |
| Training required | Yes (77K samples) | No |
| Debugging | Hard (black box) | Easy (can trace each adjustment) |
| **Parlay win rate** | **7.6%** | **TBD (monitoring 3-5 days)** |

**Expected Improvement:**
- Individual leg accuracy: 65-70% (validated)
- 4-leg parlay win rate: **18-22%** (vs 7.6% baseline)
- Profit per $1 at +1200 odds: **+$1.50-$2.50** (vs -$0.02 baseline)

---

### **Why Simple Beats Complex (In This Case)**

**Lessons from this journey:**

1. **ML is not always the answer** - We had 77K training samples, proper validation, isotonic calibration. The model still failed because the training objective was wrong.

2. **Feature engineering matters more than model complexity** - Coverage calculation with handedness splits was the signal. The ML model added 18 features on top of it and made it worse.

3. **Transparency enables debugging** - When the ML model failed, we added temporary adjustments. With simple scoring, we can see exactly why each leg got its score.

4. **Validate assumptions with real money** - The profit analysis (win rate × odds) revealed what accuracy metrics missed: the ML model was selecting unprofitable props.

5. **Occam's Razor** - The simplest explanation that fits the data is usually correct. Coverage + 5 contextual adjustments explained 69% of outcomes. Adding 19 features didn't improve it.

---

### **When to Use ML (Future)**

**ML model would be valuable IF:**
- Non-linear interactions exist (pitcher fatigue × opponent quality × park factor)
- Feature combinations outperform simple rules
- The training objective aligns with betting profit
- Model can be explained (SHAP values, feature importance)

**NOT valuable when:**
- Simple rules already work (69% accuracy)
- Training data has structural biases (unders cover more at low lines)
- Black box makes debugging harder
- Temporary adjustments needed to fix predictions

**Future consideration:** Train separate models for overs and unders, removing direction as a feature. Or add ML as a secondary signal (0.7 × coverage + 0.3 × ML) rather than replacement.

---

## Prop Type Filtering

### **Decision: Block Unprofitable Categories Based on Empirical Data**
**Implemented:** May 20, 2026

**Problem:**
Before filtering, the system included ALL prop types that met coverage thresholds. This included:
- Hitter strikeouts under: 36.7% win rate, -$0.32 per $1
- Total bases under: 59.7% win rate, -$0.10 per $1
- RBI unders: 68.7% win rate, -$0.42 per $1

These props had reasonable coverage but **lost money** due to DraftKings pricing.

**Solution:**
Direction-based prop filtering added to `main.py`:

```python
# Block hitter strikeouts under 0.5 (36.7% win rate)
if stat == "strikeouts" and line == 0.5 and direction == "under":
    continue

# Block total bases under 1.5 (59.7% win rate)
if stat == "totalBases" and line == 1.5 and direction == "under":
    continue
```

**Allowed Props (Validated Profitable):**
- ✅ Hits over 0.5 (69.4% win rate, +$0.32/dollar)
- ✅ Hits under 0.5 (73.1% win rate, +$0.14/dollar)
- ✅ Pitcher strikeouts over 3.5+ (69.3% win rate, +$0.54/dollar)
- ✅ Total bases over 1.5 (50%+ win rate, positive edge)
- ✅ Walks (marginal, kept for diversity)

**Impact:**
```
Before: 105 scored legs (mix of profitable and unprofitable)
After:  91 scored legs, 77 eligible
        68 overs (88%) + 9 unders (12%)
        0 hitter K under, 0 TB under
```

**Trade-offs:**
- ✅ Eliminates toxic props that drag down parlay win rate
- ✅ Pool becomes 88% overs (which win 60-70%)
- ❌ Smaller leg pool (but higher quality)
- ❌ Less diversity in prop types

**Validation:** Production logs show 0 blocked props appearing ✅

**Decision:** This filtering is **permanent** unless data shows otherwise. The 69% win rate on profitable props vs 36% on blocked props is decisive.

---

## Player Diversity Constraint

### **Decision: Max 1 Appearance Per Player Per Generation Run**
**Implemented:** May 19, 2026

**Problem Identified:**
Analysis of 80 instances over 14 days showed **65% wipeout rate** when players appeared in multiple parlays within the same generation batch:

| Impact Type | Count | Percentage |
|------------|-------|------------|
| 🔴 **All parlays lost** | **52** | **65%** |
| Player won but parlays lost anyway | 25 | 31% |
| Some parlays survived | 3 | 4% |

**Example (May 18, 2026):**
- Shane McClanahan appeared in all 25 parlays generated that day
- When he lost his strikeout under prop → ALL 25 parlays lost
- Result: 0% win rate for the entire day

**Implementation:**
```python
# 5 sequential B&B passes with player exclusion
used_players = set()
parlays = []

for rank in range(1, 6):
    available = [leg for leg in all_legs if leg['player_name'] not in used_players]
    parlay = branch_and_bound(available)
    
    for leg in parlay['legs']:
        used_players.add(leg['player_name'])
    
    parlays.append(parlay)
```

**Key Design Points:**

1. **Per-batch constraint only** - Diversity resets between runs (9 AM, 12 PM, 5:30 PM)
2. **Dynamic leg pool** - Uses ALL eligible legs (not capped at 50)
3. **Player diversity validation** - Can query `mlb_parlay_legs_v2` to verify

**Results (May 20):**
```
Parlay 1: Tyler Mahle, Tyler O'Neill, Marcus Semien, Harrison Bader
Parlay 2: Aaron Civale, Chris Sale, Jake Rogers, Freddy Fermin
Parlay 3: Michael Wacha, Jake Bauers, Joe Ryan, Sal Frelick

Validation query: 0 rows (no player appears 2+ times)
```

**Trade-offs:**
- ✅ Eliminates single-player wipeout risk (65% → 0%)
- ✅ Forces exploration of deeper leg pool
- ✅ Reduces correlation risk dramatically
- ⚠️ May use slightly lower-scoring legs for parlays 3-5
- ⚠️ Requires wider odds range (+900-1500 vs +1000-1400)

**Decision:** This constraint is **permanent** - the 65% wipeout rate data is decisive.

---

## Coverage Calculation

### **Decision: Direction-Aware Coverage with Handedness Splits**

**Rationale:**
Coverage must answer "How often does this player go OVER/UNDER this specific line?" not "How often does the player get hits?"

**Implementation:**
```python
# For hits over 0.5:
coverage_over = games_with_1_or_more_hits / total_games

# For hits under 0.5:
coverage_under = games_with_0_hits / total_games

# Validation: coverage_over + coverage_under ≈ 100%
```

**Handedness Splits:**
```python
# Prefer split when available
if pitcher_hand == 'R' and batter has 10+ games vs RHP:
    coverage = hits_vs_rhp_coverage
elif pitcher_hand == 'L' and batter has 10+ games vs LHP:
    coverage = hits_vs_lhp_coverage
else:
    coverage = overall_coverage (with confidence penalty)
```

**Database Fields:**
- `coverage_vs_hand` - handedness-specific (populated for 72% of legs)
- `coverage_overall` - fallback
- `coverage_recent_10` - hot/cold detection
- `coverage_recent_5` - very recent form

**Validation (May 20):**
```sql
SELECT 
    AVG(coverage_vs_hand)::numeric(5,1) as avg_vs_hand,
    AVG(coverage_overall)::numeric(5,1) as avg_overall
FROM mlb_scored_legs
WHERE run_date >= (CURRENT_DATE - INTERVAL '7 days')::text;

-- Result: 66.8% vs_hand, 66.2% overall (split slightly better)
```

**Status:** ✅ Working as designed, empirically validated

---

## Parlay Construction

### **Decision: Branch-and-Bound with Dynamic Leg Pool**

**Problem:** Build 5 four-leg parlays from 100+ legs with player diversity. Brute force: C(100,4)^5 = too many combinations.

**Solution:** Modified Branch-and-Bound with progressive player exclusion:

```python
# For each parlay rank 1-5:
1. Filter pool: exclude players already used
2. Sort remaining legs by decimal odds DESC for B&B bounds
3. Run B&B search on filtered pool
4. Pick best parlay from candidates found
5. Add that parlay's players to exclusion set
6. Repeat for next parlay
```

**Correlation Limits:**
- Max 2 legs per game (prevents over-concentration)
- DraftKings walks + strikeouts rule (can't combine from same player)
- **Max 1 leg per player per batch** (diversity constraint)

**Performance (May 20):**
```
Parlay 1 B&B: 33 iters (0.0s)
Parlay 2 B&B: 19 iters (0.0s)
Parlay 3 B&B: 258 iters (0.0s)
Total: 311 iterations, <1 second
```

**Result:**
- Built 3 parlays (not 5, but high quality)
- Average coverage: 70-78%
- All within +900-1500 odds range
- 12 unique players, no repeats

**Trade-offs:**
- ✅ Fast (<1 second total)
- ✅ Respects all platform rules
- ✅ Player diversity enforced
- ⚠️ May not always build 5 parlays (acceptable)

---

## Lessons Learned

### **1. Data-Driven Decisions Beat Intuition**

**May 11:** Removed diversity constraint based on leg-level win rates
**May 19:** Re-added it based on parlay-level wipeout rate (65%)
**May 20:** Removed ML model based on profit analysis showing it was making things worse

**Lesson:** Always validate architectural decisions with outcome data, not aggregate statistics.

---

### **2. Optimize for the Metric That Matters**

**Mistake:** Optimized for individual leg accuracy (ML model: 55%)
**Reality:** Parlay win rate is what matters (7.6%)

**Lesson:** The ML model optimized coverage % (how often bets covered), not profit. These are different objectives when DraftKings prices unders aggressively.

---

### **3. Simplicity Enables Iteration**

**With ML model:**
- Change requires retraining (hours/days)
- Debugging requires SHAP analysis
- Adjustments add new code paths

**With simple scorer:**
- Change adjustment: 5 minutes
- Debug: print the adjustments list
- Test: instant feedback

**Lesson:** Start simple, add complexity only when simple fails. We skipped step 1.

---

### **4. Correlation Risk is Real**

**Evidence:** 65% wipeout rate when players appear in multiple parlays
**Fix:** Player diversity constraint

**Lesson:** Parlay correlation isn't theoretical - it's the dominant factor in batch performance.

---

### **5. Training Objective Must Match Business Goal**

**ML Model:** Trained to predict coverage % (how often bet covers)
**Business Goal:** Profit (win rate × odds - losses)

**Result:** Model learned "unders cover more" but unders lose money at DraftKings odds.

**Lesson:** Train on profit, not proxy metrics.

---

## Future Considerations

### **Phase 2: Opponent Team Offense Stats (Optional)**

**Add only if Phase 1 achieves 18%+ parlay win rate:**
- Opponent team K-rate (for pitcher strikeout props)
- Opponent team runs per game
- Opponent team OBP

**Expected impact:** +1-2% parlay win rate improvement

**Implementation:** 1 day (API calls, caching, adjustment logic)

---

### **Phase 3: Advanced Context (Optional)**

**Add only if Phase 2 is insufficient:**
- Park factors (Coors Field boosts offense 20%)
- Weather (wind >15mph affects run totals)
- Umpire tendencies (high/low strike zone)

**Expected impact:** +1-3% parlay win rate improvement

**Implementation:** 2-3 days

---

### **ML Model Revival (Low Priority)**

**Only consider if:**
- Phase 1 + Phase 2 + Phase 3 implemented
- Still not achieving 22%+ parlay win rate
- Have 150K+ training samples

**Approach if attempted:**
- Train separate models for overs and unders
- Remove direction as feature entirely
- Train on profit, not coverage %
- Use as secondary signal (0.7 × coverage + 0.3 × ML)

---

## Open Questions

### **1. Is +900-1500 the optimal odds range?**
- Current: +900-1500 (widened May 19 for diversity)
- Question: Can we tighten back to +1000-1400 once leg pool stabilizes?
- Resolution: After 5 days, check if most parlays fall in +1100-1400 subrange

### **2. Is 4 legs optimal or should we test 3 or 5?**
- Current: Fixed at 4 legs
- Alternative: Allow 3-5 legs based on coverage quality
- Trade-off: Flexibility vs complexity
- Resolution: After diversity constraint stabilizes, revisit leg count

### **3. Should we add team offense stats now or wait?**
- Current: Only pitcher-level stats (ERA, K/9)
- Alternative: Add opponent team K-rate, OBP, runs/game
- Trade-off: More data vs more complexity
- Resolution: Wait for Phase 1 results (3-5 days)

---

**Last Updated:** May 20, 2026  
**System Status:** ✅ Phase 1 Deployed  
**Next Review:** May 23-25, 2026 (after monitoring period)  
**Confidence Level:** High - 69% individual leg accuracy empirically validated
