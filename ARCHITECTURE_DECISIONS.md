# MLB Parlay Agent — Architecture Decisions

**Last Updated:** April 24, 2026

---

## Smart Parlay Filter (April 24, 2026)

**Decision:** Block poison overs entirely, allow only high-confidence risky overs with max 1 per parlay.

**Context:**
- Training data analysis revealed massive direction bias (79.2% under vs 21.9% over)
- Some stat+direction combos are poison (RBI over 14.6%, walks over 19.4%, HR over 6.1%)
- High-score hits over 0.5 shows 44.4% hit rate (marginal but viable)
- User wanted to continue tracking hits overs but not overuse them

**Filter rules:**

**Poison overs (BLOCKED):**
- RBI overs: 14.6% hit rate
- Walks overs: 19.4% hit rate
- Home runs overs: 6.1% hit rate

**Risky overs (max 1 per parlay):**
- Hits over 0.5 with 65+ composite score: 44.4% hit rate
- Pitcher strikeouts over 4.5+ with 65+ composite score: 44.6% hit rate

**All other overs:** BLOCKED (low-score hits overs, ambitious lines, etc.)

**Implementation:**
- `filter_and_tag_legs()` runs after scoring, before pool selection
- Branch-and-Bound tracks risky_overs counter (max 1)
- Filter logs breakdown: "blocked N poison overs, M other overs | kept X unders + Y risky overs"

**Rationale:**
- Prevents catastrophic parlay compositions (all overs = 3.88% 4-leg win rate)
- Allows data collection on viable overs (hits 0.5, pitcher Ks)
- Protects parlay probability from tanking below breakeven
- User retains some flexibility without shooting themselves in the foot

**Expected impact:** Win rate improvement from 47.7% to 52-58%

---

## ML-Powered Leg Scoring (April 24, 2026)

**Decision:** Build a machine learning model to predict P(hit) for each prop leg instead of using hand-coded composite scoring weights.

**Context:**
- Current system uses fixed weights: coverage 70%, opponent 20%, stability 10%
- These are "principled priors" that need calibration with real data
- 49,222 training samples available with features + outcomes
- Coverage formula is systematically overconfident (12-23pp errors)

**New Architecture:**

### Model Trained (COMPLETE)
- **Algorithm:** GradientBoostingClassifier + IsotonicCalibration
- **Training data:** 49,222 samples (March 28 - April 22, 2026)
- **Features:** coverage_pct, composite_score, opponent_adjustment, trend_score, pa_last_10, line, direction, stat (one-hot)
- **Performance:** ROC AUC 0.8648, Accuracy 80%
- **Top features:** direction (76.6%), composite_score (6.9%), opponent_adjustment (4.9%)

**Key insight:** Model correctly learned that direction (over/under) is the DOMINANT signal — even more important than coverage.

### Deployment Strategy (PENDING)

**Phase 1 (Current):** Filter deployed, ML model trained but not in production
**Phase 2 (After 3-5 days):** A/B test ML vs heuristic scoring
**Phase 3 (If ML wins):** Replace heuristic scoring in production

**Rationale:**
- Smart filter is the higher-impact change (blocks poison bets)
- Need to validate filter works before changing scoring system
- ML model learns optimal feature weights from data (no more guessing 70% vs 20%)
- Automatically discovers interactions ("high coverage + over direction = lower than formula")
- Can add new features (weather, ballpark, line movement) without manual weight tuning

**What stays the same:**
- Production pipeline still runs 3×/day (9AM/12PM/5:30PM)
- Branch-and-Bound parlay builder unchanged
- Discord delivery, web app unchanged

**What changes (when enabled):**
- `leg_scorer.py` replaced with `ml_scorer.py` for scoring
- Legs sorted by `ml_hit_probability` instead of `composite_score`
- Parlay builder uses ML probabilities for pool selection

---

## Training Data Analysis Findings (April 24, 2026)

**Decision:** Use training data insights to inform filter design and validate ML model approach.

**Key findings from 66,174 resolved samples:**

### 1. Composite Score Profitability Thresholds
