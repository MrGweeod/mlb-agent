# MLB Parlay Agent — Build Status

**Last Updated:** 2026-05-01 (End of Day)
**System Status:** ⚠️ Partially Operational (4/5 fixes complete)
**Repo:** github.com/MrGweeod/mlb-agent

## Infrastructure Status
| Component | Status | Notes |
|-----------|--------|-------|
| Railway Deployment | ✅ Live | Commit `98fd9bb`, auto-deploys |
| Web App | ⚠️ Partial | Legs working, Picks showing 1/5 parlays |
| Supabase PostgreSQL | ✅ Active | Schema fixed May 1 |
| ML Model | ✅ Deployed | leg_scorer_v2.pkl, AUC 0.8532 |
| Discord Bot | ❌ Removed | Deleted April 29 |

---

## Critical Issue (May 1)

**Problem:** Only 1 parlay displaying instead of 5

**Root Cause:** Pipeline processes 352 legs but doesn't save them to database

**Impact:**
- Legs Tab: ✅ Works (213 legs from morning)
- Picks Tab: ⚠️ Only 1 parlay (needs 5)

**Next Steps:** Investigate `log_scored_legs()` in main.py

---

## Phase Completion Status

### ✅ Phase 1 — NBA Agent Copies
All core modules copied and operational.

### ✅ Phase 2 — MLB Adaptations

**Coverage Calculation (April 29):**
- 3 signals for hitters: overall, vs_hand, recent_10
- 2 signals for pitchers: overall, recent_5
- File: `src/engine/coverage.py`

**Composite Scoring (April 29-30):**
- Replaced with ML model predictions
- `composite_score = ML_model.predict_proba() × 100`
- File: `src/engine/leg_scorer.py`

**Database Schema (May 1):**
- ✅ Added `composite_score REAL` column
- ✅ Changed to `UNIQUE (run_date, odd_id)`
- Migration run in Supabase
- Impact: 10 legs/day → 200+ legs/day

### ✅ Phase 3 — New Modules

**Dynamic Picks Tab (April 30, Fixed May 1):**
- `/api/build-parlays` endpoint
- Builds fresh parlays on-demand
- ⚠️ Currently showing 1 parlay (diversity issue)

**Data Pipeline (May 1):**
- ✅ Schema migration complete
- ✅ composite_score populates
- ✅ ML pickle deserialization fixed
- ⚠️ Leg persistence issue

### ✅ Phase 4 — ML Training Data
- 77,025+ training samples
- Date coverage: March 28 - April 30, 2026
- Prospective collection: ✅ Active

### ✅ Phase 5 — ML Model

**Status:** ✅ Deployed and Working

**Specifications:**
- Algorithm: GradientBoostingClassifier
- Features: 19 (7 coverage + direction + 11 stat one-hots)
- Calibration: Platt Scaling
- AUC: 0.8532
- Size: 681 KB

**Feature Importance:**
1. Direction: 77.2%
2. Strikeouts: 5.6%
3. Stolen Bases: 3.4%

### ✅ Phase 6 — Trust ML Uniformly (April 30)
- Removed directional bias
- Uniform 55% threshold
- Commit: `a38467f`

### ✅ Phase 7 — Fix Production Issues (May 1)

**Fix 1: ML Pickle (Commit `4df6b28`)**
- Added `_CompatUnpickler` shim
- File: `src/engine/ml_leg_scorer.py`

**Fix 2: Database Type (Commit `4df6b28`)**
- `str(date.today())` for TEXT columns
- File: `src/web/server.py`

**Fix 3: Schema Migration (Commit `20d8777`)**
- Added composite_score column
- Per-day uniqueness constraint
- Files: `src/utils/db.py`, migration SQL

**Fix 4: Function Signature (Commit `7fcbc2b`)**
- Removed invalid parameters
- File: `src/web/server.py`

**Fix 5: Combined Odds (Commit `98fd9bb`)**
- Parse `parlay_odds` → `combined_odds`
- Fixed edge calculation formula
- Increased `top_n=10`
- File: `src/web/server.py`

---

## Database Schema

### mlb_scored_legs Table
```sql
CREATE TABLE mlb_scored_legs (
    id SERIAL PRIMARY KEY,
    run_date TEXT NOT NULL,
    player_name TEXT,
    stat TEXT,
    line REAL,
    direction TEXT,
    odds INT,
    composite_score REAL,  -- NEW May 1
    -- ... other columns ...
    UNIQUE (run_date, odd_id)  -- FIXED May 1
);
```

**Constraints:**
- ✅ PRIMARY KEY (id)
- ✅ UNIQUE (run_date, odd_id) - per-day scope
- ❌ Old global UNIQUE (odd_id) - REMOVED

**Current Data:**
- May 1: 215 legs (stale from morning)
- Training: 77K+ samples

---

## Production Metrics

### Pipeline (5:30 PM Run)
- Props fetched: 2,504 from SGO
- Qualifying legs: 352 at ≥55%
- Parlays built: 5
- **Legs saved:** ⚠️ Unknown (missing log)

### Web App
- **Legs Tab:** ✅ 213 legs displayed
- **Picks Tab:** ⚠️ 1 parlay (should be 5)
- **Dashboard:** ✅ 77K training samples
- **Training:** ✅ Data quality monitoring

### ML Model
- **Predictions:** ✅ Populating composite_score
- **Calibration:** ✅ Working (±4pp accuracy)
- **Pickle:** ✅ Deserialization fixed

---

## Git History (May 1)

| Commit | Description | Status |
|--------|-------------|--------|
| `4df6b28` | ML pickle + DB type fix | ✅ Deployed |
| `20d8777` | Schema migration | ✅ Deployed |
| `7fcbc2b` | Function signature fix | ✅ Deployed |
| `98fd9bb` | Combined odds parsing | ✅ Deployed |

---

## Outstanding Items

### CRITICAL (Tomorrow)
1. ⚠️ Fix pipeline leg persistence
2. Verify `log_scored_legs()` actually saves
3. Ensure database updates after each run

### HIGH
4. Monitor 9 AM pipeline
5. Validate edge calculations
6. Track actual outcomes

### MEDIUM
7. Review diversity filter parameters
8. Investigate 124/215 filter pass rate
9. Parlay-level outcome tracking

### LOW
10. Deprecate `mlb_parlay_recommendations` table
11. Update blueprint v2.0
12. Integration tests for schema

---

## Key Learnings (May 1)

1. **Database schema changes → migration first, code second**
2. **Pickle serialization fragile when moving classes**
3. **Field name mismatches fail silently** (parlay_odds vs combined_odds)
4. **UNIQUE constraints need proper scope** (per-day vs global)
5. **Always verify data structure field names** before accessing

---

## System Health

**Overall:** ⚠️ 80% Operational

**Working:**
- ✅ ML model predictions
- ✅ Database schema
- ✅ Legs display
- ✅ Odds calculation

**Broken:**
- ⚠️ Pipeline leg persistence
- ⚠️ Multiple parlay generation

**Critical Path:** Fix pipeline saving → enables 5 parlays → system fully operational
