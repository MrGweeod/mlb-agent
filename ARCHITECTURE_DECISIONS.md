---

## ML-Powered Leg Scoring (Pivot Decision)
**Date:** April 23, 2026

**Decision:** Build a machine learning model to predict P(hit) for each prop leg instead of using hand-coded composite scoring weights.

**Context:**
- Current system uses fixed weights: coverage 70%, opponent 20%, stability 10%
- These are "principled priors" that need calibration with real data
- We have access to unlimited historical data via SGO API + MLB-StatsAPI
- 614 production legs show coverage is systematically overconfident (12-23pp errors)

**New Architecture:**

### Phase 1: Training Data Collection (COMPLETE)
- Built `scripts/backfill_training_data.py` to fetch historical props + outcomes
- Collected 66,174 resolved training samples (March 28 - April 22, 2026)
- Database: `mlb_training_data` table with props, outcomes, and feature slots

### Phase 2: Feature Engineering (NEXT)
- Calculate features for all 66K samples:
  - Player performance: coverage_pct, coverage_vs_hand, games_vs_hand, avg_last_10
  - Matchup: pitcher_era_rank, pitcher_k9_rank, pitcher_whip_rank, pitcher_hand
  - Context: home_away, batting_order_position, pa_last_10
  - Market: fair_line (SGO sharp consensus)
- Store in training_data table feature columns

### Phase 3: Model Training (FUTURE)
- Train sklearn GradientBoostingClassifier:
```python
  X = [coverage_vs_hand, pitcher_era_rank, trend_score, ...]  # ~15 features
  y = [1 if result=='hit' else 0]  # binary target
  model.fit(X, y)
  p_hit = model.predict_proba(X_new)[:, 1]
```
- Use p_hit as leg score (replaces hand-coded composite_score)
- Keep Branch-and-Bound parlay builder (architecture-agnostic)

**Rationale:**
- ML learns optimal feature weights from data (no more guessing 70% vs 20%)
- Automatically discovers interactions ("high coverage + tough pitcher = lower than formula")
- Can add new features (weather, ballpark, line movement) without manual weight tuning
- 66K samples is plenty for gradient boosting (needs 2K+, we have 30×)

**What stays the same:**
- Production pipeline still runs 3×/day (9AM/12PM/5:30PM)
- Branch-and-Bound parlay builder unchanged
- Discord delivery, web app unchanged
- Database, Railway deployment unchanged

**What changes:**
- `leg_scorer.py` eventually replaced with `ml_scorer.py`
- Daily pipeline adds training data collection step
- New table: `mlb_training_data` (separate from production `mlb_scored_legs`)

---

## Training Data Collection Architecture
**Date:** April 23, 2026

**Decision:** Build separate training data table and backfill script instead of trying to retrofit production scored_legs table.

**Database schema:**
```sql
mlb_training_data:
  - Raw prop data: player_id, stat, line, odds, fair_line, odd_id
  - Features: coverage_pct, pitcher_era_rank, trend_score, etc. (NULL initially)
  - Outcome: actual_stat, result ('hit'/'miss'), resolved_at
  - Allows WHERE result IS NOT NULL for clean training set
```

**Backfill strategy:**
- SGO API confirmed to have historical access (tested April 15, worked)
- Full backfill: March 28 - April 22 (26 days, Opening Day through yesterday)
- Result: 73,942 props logged, 66,174 resolved (89.5% resolution rate)

**Key implementation details:**
1. **odd_id collision fix** — SGO reuses IDs across dates, so we prefix with `game_date|` to make each day independent
2. **Historical prop extraction** — `_get_historical_player_props()` ignores `available: false` flag (closed lines still have valid data)
3. **Efficient resolution** — One box score fetch per game covers all props in that game (not one API call per prop)
4. **DNP handling** — Players not in box score → result=NULL (excluded from training, not marked as 'void')

**Prospective collection (Phase 2):**
- Add to daily 9AM run: log today's props → resolve tomorrow morning
- Adds ~300 samples/day going forward
- Same table, same schema, idempotent inserts

---

## EV Signal Dropped from Scoring
**Date:** April 23, 2026

**Decision:** Set EV weight to 0% in composite scoring.

**Rationale:**
- EV measures single-bet profitability: `(fair_prob × profit) - (1-fair_prob × loss)`
- We're building PARLAYS where combined probability is exponential: `0.70^5 = 0.168`
- In parlays, coverage quality >> individual leg EV
- Example: 4 legs at 70% coverage + 0% EV crushes 4 legs at 55% coverage + 15% EV

**What EV was supposed to do:**
- Compare SGO fair line vs DK book line
- Positive line_diff = easier to beat = positive EV
- Used a 0.25 probability shift heuristic per line unit

**Why it didn't work:**
- The 0.25 multiplier was a guess (could be 0.15 or 0.35 for MLB)
- Historical data showed inversion: strong -EV legs won at 55.3% (best bucket)
- Root cause unclear — could be bad multiplier, bad formula, or EV genuinely doesn't matter for parlays

**Better use of fair lines:**
- Use as coverage calibration: "My model says 72%, market says 45% → I'm probably wrong"
- Implement divergence penalty instead of EV calculation
- Or just use for filtering: "Don't bet legs where my coverage disagrees with market by >20pp"

**Current weights (post-EV drop):**
- Coverage: 70%
- Opponent adjustment: 20%
- PA stability: 10%
- Trend: 0%
- EV: 0%
