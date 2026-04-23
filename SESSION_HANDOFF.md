# MLB Parlay Agent — Session Handoff
**Last Updated:** April 23, 2026

## Current Status
✅ **Historical training data backfill COMPLETE** — 66,174 resolved samples (March 28 - April 22)
✅ **Coverage model fixed** — Log-odds transformation, range 23.1%–90.5%
✅ **Dashboard built** — 6-section analytics page
✅ **Database cleaned** — 614 production legs deduplicated
⚠️ **EV signal dropped** — Weight set to 0% (not useful for parlay construction)
⚠️ **Coverage still overconfident** — 12-23pp errors in upper buckets

---

## What Was Built This Session (April 23, 2026)

### ML Pivot — Training Data Collection System

**Decision:** Build ML-powered leg scoring model instead of hand-coded heuristics

**Strategy:**
- Phase 1 (COMPLETE): Historical backfill — collect 26 days of props + outcomes
- Phase 2 (NEXT): Prospective collection — add to daily pipeline going forward  
- Phase 3 (FUTURE): Train gradient boosting classifier on features → P(hit)

### Historical Backfill Script

**File:** `scripts/backfill_training_data.py` (410 lines)

**What it does:**
1. Fetches historical SGO props for date range (tested: March 28 - April 22 works)
2. Logs to `mlb_training_data` table with basic fields (player, stat, line, odds, fair_line)
3. Resolves outcomes from MLB box scores (one API call per game, not per prop)
4. Handles DNP/scratched players as NULL (excluded from training)

**Key technical details:**
- Uses `_get_historical_player_props()` — ignores `available: false` flag on closed lines
- Prefixes `odd_id` with `game_date|` to prevent cross-date collisions
- Idempotent: safe to re-run (uses `ON CONFLICT (odd_id) DO NOTHING`)
- Three modes: full backfill, props-only, resolve-only

**Results:**
- 73,942 total props logged
- 66,174 resolved (31,450 hits, 34,724 misses)
- 7,768 NULL (DNP/scratched, excluded from ML)
- 89.5% resolution rate

**Database table:** `mlb_training_data`
```sql
CREATE TABLE mlb_training_data (
    id SERIAL PRIMARY KEY,
    game_date DATE NOT NULL,
    game_pk TEXT,
    player_id TEXT NOT NULL,
    player_name TEXT,
    stat TEXT NOT NULL,
    direction TEXT NOT NULL,
    line FLOAT NOT NULL,
    odds TEXT,
    fair_line FLOAT,
    
    -- Features (NULL for now, calculated in Phase 2)
    coverage_pct FLOAT,
    coverage_vs_hand FLOAT,
    games_vs_hand INTEGER,
    pitcher_id TEXT,
    pitcher_hand TEXT,
    pitcher_era_rank INTEGER,
    pitcher_k9_rank INTEGER,
    pitcher_whip_rank INTEGER,
    home_away TEXT,
    batting_order_position INTEGER,
    pa_last_10 FLOAT,
    trend_score FLOAT,
    opponent_adjustment FLOAT,
    
    -- Outcome (resolved from box scores)
    actual_stat FLOAT,
    result TEXT,  -- 'hit' or 'miss'
    resolved_at TIMESTAMP,
    
    -- Metadata
    logged_at TIMESTAMP DEFAULT NOW(),
    odd_id TEXT UNIQUE,
    
    CONSTRAINT valid_result CHECK (result IN ('hit', 'miss') OR result IS NULL)
);
```

---

## Production Pipeline Status (Unchanged)

**Still running 3x/day:**
- 9:00 AM: Resolve last night + early props
- 12:00 PM: Afternoon slate
- 5:30 PM: Evening slate (final run)

**Current scoring weights:**
- Coverage: 70%
- Opponent adjustment: 20%
- PA stability: 10%
- Trend: 0% (no predictive value)
- EV: 0% (dropped — not useful for parlays)

**Calibration (614 production legs, April 17-22):**
- Overall win rate: 47.7%
- Coverage errors: 12-23pp overconfident in 60%+ buckets
- Best prop: Pitcher Ks (53.3% hit rate)
- Direction bias: Overs 50.0%, Unders 44.3%

---

## Next Session Priorities

### HIGH PRIORITY
1. **Add prospective collection to daily pipeline** — log today's props to training_data each run
2. **Build feature calculation module** — populate NULL feature columns for all 66K rows
3. **Train initial ML model** — sklearn GradientBoostingClassifier with 66K samples
4. **A/B test ML vs heuristic scoring** — compare parlay quality over 3-5 days

### MEDIUM PRIORITY
- Investigate why coverage is systematically overconfident (global 0.85× deflation?)
- Filter unders more aggressively (44.3% vs 50.0% overs)
- Add ballpark factors, weather signals to feature set

### LOW PRIORITY
- Parlay-level ML optimizer (learns which leg combinations work best)
- Reinforce learning approach for parlay construction

---

## Key Files Modified Today

| File | Changes |
|------|---------|
| `scripts/backfill_training_data.py` | NEW — 410 lines, historical backfill script |

## Database Changes

| Table | Action |
|-------|--------|
| `mlb_training_data` | CREATED — 73,942 rows inserted, 66,174 resolved |

## Git Status

HEAD: (to be committed)
Branch: master
Untracked: scripts/backfill_training_data.py

---

## SGO API Usage
- Monthly quota: 5,000 / 100,000 objects (5%)
- Backfill consumed: ~400 objects
- Plenty of headroom for daily prospective collection

---

## Environment
- Repository: github.com/MrGweeod/mlb-agent
- Deployment: Railway (mlb-agent project) — production pipeline still running
- Web app: https://mlb-agent-production.up.railway.app
- Database: Supabase PostgreSQL (mlb_training_data + mlb_scored_legs tables)
- Python: 3.14 in venv (WSL2 Ubuntu)
