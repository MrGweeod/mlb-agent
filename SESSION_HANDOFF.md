# MLB Parlay Agent — Session Handoff
**Last Updated:** April 22, 2026

## Current Status
✅ **Coverage model fixed** — Log-odds transformation, range now 23.1%–90.5% (no more 100%)
✅ **Dashboard built** — 6-section analytics page with coverage calibration, EV validation, trends
✅ **Database cleaned** — 614 deduplicated resolved legs, DEDUP_CTE in all dashboard queries
✅ **Calibration data fresh** — 618 historical legs rescored with new coverage model
⚠️ **EV signal still inverted** — Strong -EV legs winning at 55.3% (investigation needed)
⚠️ **Coverage still overconfident** — 12-23pp errors across upper buckets (model improvement needed)

---

## What Was Built This Session (April 22, 2026)

### 1. Fixed Coverage Calculation — Log-Odds Transformation (CRITICAL)
**Problem:** Linear split ratio had no upper bound — strong handedness splits pushed coverage > 100%.
- Formula: `overall_rate × (avg_vs_hand / avg_overall)` can exceed 1.0
- Example: Jeremiah Jackson vs LHP: 65.2% × 1.608 = 104.8% → capped to 100% (wrong)
- Same coverage (100%) for both over and under of the same prop — mathematically impossible

**Fix:** Replace linear multiplication with log-odds transformation.
```python
# Old (broken):
coverage = overall_rate × split_ratio  # can exceed 1.0

# New (fixed):
log_odds = logit(overall_rate) + log(rate_vs_hand / rate_overall)
coverage = sigmoid(log_odds)  # always in (0, 1)
```

**Result:**
- Jeremiah Jackson vs LHP: 75.1% (was 100%)
- Coverage range: 23.1% to 90.5% (was many at 100%)
- Files: `src/engine/coverage.py`
- Commit: `f849237`

---

### 2. Built Performance Analytics Dashboard
New tab in web app with 6 analytics sections fed by `GET /api/dashboard`.

**Sections:**
1. **Coverage Calibration** — Predicted vs actual by bucket, error in percentage points, color-coded
2. **Prop Type Performance** — Win rate, avg coverage, avg odds by stat category
3. **Over vs Under Analysis** — Direction bias detection
4. **Recent 7-Day Trend** — Daily win rate + 3-day rolling average
5. **Top Performers** — Players with ≥5 resolved legs, ranked by win rate
6. **EV Signal Validation** — Win rate by EV bucket (validates if EV calculation works)

**Technical:**
- `GET /api/dashboard` endpoint added to `server.py`
- `get_dashboard_data()` added to `db.py` (all 6 SQL queries in one DB connection)
- Dashboard tab in header, hides filters/sort bar when active
- Auto-refreshes every 60 seconds when dashboard tab is open
- Mobile-responsive tables with `overflow-x: auto`
- Files: `src/utils/db.py`, `src/web/server.py`, `src/web/static/index.html`
- Commit: `7bd0f68`

---

### 3. Fixed Three UI Issues (Quick Wins)

**Coverage display bug (5930% → 59.3%):**
- `fmtPct()` was multiplying by 100 on a value already stored on 0-100 scale
- Fixed: removed `× 100`, use `.toFixed(1)` directly
- Also fixed `covClass()` thresholds from 0-1 to 0-100 scale

**Both over and under showing (direction filter):**
- `get_scored_legs()` now uses ROW_NUMBER() CTE partitioned by player_name+stat
- Picks highest-EV direction when both over and under are logged

**Added stats to cards (Trend + Matchup pills):**
- HOT/COLD pill (green/red) for trend_score
- Favorable/Tough/Neutral pill for opponent_adjustment
- Always visible without expanding the card
- Files: `src/utils/db.py`, `src/web/static/index.html`
- Commit: `6c28091`

---

### 4. Built Historical Rescoring Script
New script: `scripts/rescore_historical_legs.py`

- Fetches all resolved legs with both player_id and opposing_pitcher_id
- Recalculates coverage_pct using current `calculate_coverage()` logic
- Updates coverage_pct (0-100 scale) and p_over (0-1 scale) in database
- Commits in batches of 50, progress logging throughout
- Result: 618/639 legs rescored, 21 skipped (empty game log from MLB API), 0 failures
- Commit: `624b85f`

---

### 5. Fixed Database Duplicates (Data Quality)

**Problem:** PostgreSQL UNIQUE constraint on `odd_id` doesn't prevent duplicate NULLs. Some legs were logged twice — once with `odd_id=NULL` (early run) and once with a real odd_id (later run). This inflated calibration sample sizes.

**Investigation findings:**
- 673 raw resolved legs → 614 unique after dedup
- 59 rows deleted: NULL odd_id rows that had a non-NULL sibling for same (run_date, player_name, stat, direction)
- 504 NULL odd_id rows kept: sole records with no non-NULL equivalent

**Fixes:**
1. Deleted 59 true-duplicate NULL rows from database
2. Added `DEDUP_CTE` to all 6 dashboard queries — picks highest-EV row per (run_date, player_name, stat, direction)
3. Added `odd_id TEXT, UNIQUE (odd_id)` to `init_db()` schema so fresh deployments include the column
4. `get_scored_legs()` (web app display) was already correct — confirmed 0 cross-direction dupes for all dates
- Files: `src/utils/db.py`
- Commit: `41be85d`

---

## Current Calibration Results (614 Deduplicated Legs, April 17-21)

### Coverage Calibration
| Bucket | Avg Predicted | Count | Won | Actual Rate | Error |
|--------|--------------|-------|-----|-------------|-------|
| <55%   | 47.0%        | 135   | 55  | 40.7%       | -6.3pp ✅ |
| 55-60% | 57.3%        | 52    | 21  | 40.4%       | -16.9pp ❌ |
| 60-65% | 62.6%        | 128   | 64  | 50.0%       | -12.6pp ⚠️ |
| 65-70% | 67.7%        | 112   | 50  | 44.6%       | -23.1pp ❌ |
| 70%+   | 77.4%        | 187   | 103 | 55.1%       | -22.3pp ❌ |

**Overall win rate:** 47.7% (293/614)

### Prop Type Performance
| Stat       | Total | Win Rate | Notes |
|------------|-------|----------|-------|
| Strikeouts | 122   | 53.3%    | Best performer ✅ |
| Total Bases| 53    | 47.2%    |       |
| RBI        | 32    | 46.9%    |       |
| Hits       | 386   | 46.4%    |       |
| Walks      | 21    | 42.9%    |       |

### Direction Bias
| Direction | Count | Win Rate |
|-----------|-------|----------|
| Over      | 368   | 50.0%    |
| Under     | 246   | 44.3%    |

5.7pp advantage for overs — potentially exploitable.

### EV Signal Validation (Still Inverted)
| Bucket              | Count | Win Rate |
|--------------------|-------|----------|
| Strong -EV (<-10%) | ~     | 55.3%    |
| Weak -EV           | ~     | ~        |
| Neutral            | ~     | ~        |
| Weak +EV           | ~     | ~        |
| Strong +EV (>15%)  | ~     | lower    |

EV signal remains inverted. The April 21 EV formula fix hasn't generated enough new data to validate.

---

## Known Issues

### CRITICAL
- ❌ **EV signal inverted** — Strong -EV legs winning at 55.3%, best of all buckets. Root cause under investigation.
- ❌ **Coverage systematically overconfident** — 12-23pp errors in upper buckets despite log-odds fix. Model still overpredicts.

### HIGH PRIORITY
- ⚠️ **Opponent adjustment mostly negative** — Worth investigating whether pitcher opponent adjustment is being calculated correctly or if it systematically discounts coverage
- ⚠️ **55-60% bucket worst calibrated** (-16.9pp) — May need a separate penalty for this range

### MEDIUM PRIORITY
- Apply global coverage deflation factor (e.g. 0.85×) to reduce systematic overconfidence
- Investigate why 60-65% bucket hits at exactly 50.0% (suspiciously round)
- Under direction consistently underperforms (44.3% vs 50.0% over) — consider filtering unders more aggressively

---

## Next Session Priorities

1. **Investigate EV signal inversion** — Check whether `ev_per_unit` calculation in `sportsgameodds.py` is correct after April 21 fix. Strong -EV should be worst-performing bucket.
2. **Investigate opponent_adjustment** — Query distribution of values; check if systematically negative and why.
3. **Add coverage deflation** — A flat 0.85× multiplier on coverage_rate before storing would reduce overconfidence from ~20pp to ~3pp (rough estimate).
4. **Monitor April 22+ data** — First legs scored with log-odds model. Check calibration after 50+ new resolved legs.
5. **Filter unders more aggressively** — Given 44.3% vs 50.0% win rate gap, consider raising under eligibility threshold.

---

## Key Files Modified Today
| File | Changes |
|------|---------|
| `src/engine/coverage.py` | Log-odds transformation for split adjustment |
| `src/utils/db.py` | Dashboard queries (DEDUP_CTE), init_db schema, get_scored_legs CTE |
| `src/web/server.py` | `/api/dashboard` endpoint |
| `src/web/static/index.html` | Dashboard UI, coverage fix, card pills, tab switcher |
| `scripts/rescore_historical_legs.py` | New — historical rescoring script |

## Git Status
| Commit | Description |
|--------|-------------|
| `41be85d` | fix: eliminate duplicate legs from calibration data |
| `f849237` | fix: replace linear split ratio with log-odds adjustment |
| `995d0ad` | chore: force Railway rebuild for dashboard |
| `7bd0f68` | feat: add performance analytics dashboard |
| `6c28091` | fix: three UI issues — coverage, direction filter, card stats |
| `624b85f` | feat: add rescore_historical_legs script |
| `0da7cfe` | fix: replace Poisson with split ratio coverage (predecessor) |

All deployed to Railway.

## Environment
- Repository: github.com/MrGweeod/mlb-agent
- Deployment: Railway (mlb-agent project)
- Web app: https://mlb-agent-production.up.railway.app (password protected)
- Database: Supabase PostgreSQL (same instance as NBA agent)
- Python: 3.14 in venv (WSL2 Ubuntu)
