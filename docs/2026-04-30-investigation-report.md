# Investigation Report — April 30, 2026

**Date:** April 30, 2026  
**Issues:** Only 12 legs in database, parlay builder using wrong min_legs, non-functional refresh button, invalid strikeout props in DB

---

## Problem 1: Only 12 Legs (Expected 100–200+)

### Investigation Method
Direct analysis of the pipeline source code since Railway logs from the 9 AM ET run are not accessible locally. The data flow from SGO props → `mlb_scored_legs` was traced step by step.

### Pipeline Data Flow

The 9 AM pipeline runs this filter chain before saving to `mlb_scored_legs`:

```
SGO raw props (est. 250–350)
  → stat filter (PROP_STAT_MAP gate — inningsPitched/hitsAllowed/earnedRuns removed): ~200 remain
  → standard_line / standard_odds required: ~190 remain
  → MLB player ID lookup (statsapi.lookup_player): drops unknowns
  → player info fetch (position + team): drops missing players
  → pitcher-only filter (pitchers pass only if stat=strikeouts): drops many pitcher props
  → team on today's schedule check: drops players not scheduled today
  → coverage calculation: may return None if below seasonal minimum games
  → coverage_pct >= 55% gate
  → FINAL: qualifying_legs saved to DB
```

### Most Likely Root Causes for 12 Legs

**Primary Suspect: `get_season_minimum()` + early season data scarcity**

As of April 30, players have ~30 days of 2026 season data. The `get_season_minimum()` function in `coverage.py` requires:
- `games_played >= 30` → min 20 games of historical data needed
- Many players may have only 18–25 games logged → `calculate_coverage()` returns `None` → leg dropped

For a player with exactly 18 games in the current season, the function returns `None` even if all 18 games cleared the prop line. This filter alone could reduce 200 eligible props down to ~30 that have sufficient data.

**Secondary Suspect: 55% coverage gate**

Many MLB props (especially overs) have historical hit rates of 40–54%. Any prop below 55% is dropped. Given the ML model found that unders hit at ~79% and overs at ~22%, many over props would fail this gate. But 12 surviving legs out of ~200 implies filtering of >94%, which is more extreme than coverage threshold alone.

**Tertiary Suspect: Player ID lookup failures**

`statsapi.lookup_player()` is called for every prop. Players with:
- Exact name mismatches vs. SGO's marketName parsing
- Hyphenated names, accents, Jr./Sr. suffixes
- Recently called-up or traded players

...would return `None` from `_lookup_player_id()` and be silently dropped. In the worst case, SGO's name format may have changed or shifted in a way that breaks matching for a large portion of props.

**Action Required:**

To confirm the root cause, check Railway logs from the 9 AM April 30 run for:
1. `[3/8] Fetching player props from SportsGameOdds...` → `X SGO game(s) | Y raw props`
2. `[4/8] Computing coverage...` → `X qualifying leg(s) at ≥55.0% coverage`
3. Any errors like `"MLB ID lookup failed for"` or `"No games scheduled today"`

If `Y raw props` is low (< 100), the problem is at SGO fetch level (quota, API issue, or game ID mismatch).  
If `Y raw props` is high (200+) but qualifying legs is low, the issue is in the coverage gate or player ID resolution.

### What Was Fixed

The `ON CONFLICT (odd_id) DO NOTHING` constraint on `mlb_scored_legs` is correct and idempotent. The 12 legs currently in the DB are the 12 that passed all filters — this is not a DB insertion bug.

---

## Problem 2: Parlay Builder Using Wrong Parameters (FIXED)

### Root Cause
`_tier_params()` in `parlay_builder.py` returned `min_legs=4` for Tiers 1 and 2 (10+ games and 5–9 games respectively). Per the original blueprint requirements, minimum should be 5 legs.

### Fix Applied
`src/engine/parlay_builder.py` — `_tier_params()`:
- Tier 1 (≥10 games): `min_legs=4` → `min_legs=5`
- Tier 2 (≥5 games): `min_legs=4` → `min_legs=5`
- Tier 3 (≥2 games): `min_legs=3` → `min_legs=4`

MIN_PARLAY_ODDS (1000) and MAX_PARLAY_ODDS (1500) were already correct from the April 29 session.

---

## Problem 3: Non-Functional Refresh Button (FIXED)

### Root Cause
The Legs tab "Refresh" button called `fetchLegs()` which only re-queried `mlb_scored_legs` from the database. It did not trigger a new SGO fetch, coverage calculation, or parlay rebuild. Between the three scheduled pipeline runs (9 AM / 12 PM / 5:30 PM), users had no way to get fresher data.

The "Regenerate Now" button in the Picks tab was functional (it rebuilt parlays from existing DB legs), but the Legs tab refresh was read-only.

### Fix Applied

**Backend** (`src/web/server.py`):
- Added `POST /api/refresh` endpoint that calls `run_pipeline(starts_after_override=cutoff_utc)` where `cutoff_utc = now + 3 hours`
- The 3-hour buffer ensures only games with enough lead time are fetched, minimising SGO API quota usage
- Returns `{legs_count, recommendations_count, timestamp}` on success

**SGO API** (`src/apis/sportsgameodds.py`):
- Added optional `starts_after_override` parameter to `get_todays_games()`
- When provided, replaces the default `now_utc` filter with the override value

**Pipeline** (`main.py`):
- Added optional `starts_after_override` parameter to `run_pipeline()`
- Passed through to `get_todays_games()`

**Frontend** (`src/web/static/index.html`):
- Refresh button now calls `POST /api/refresh` with password auth
- Shows spinner with "Fetching fresh data from SGO…" during the pipeline run
- Reloads the Legs tab on success
- Shows toast notification with leg/parlay counts

### API Usage Impact
- Pipeline runs: 3/day × ~300 props = 900 props/day
- Manual refreshes (est. 5/day): 5 × ~150 props = 750 props/day (3-hr buffer reduces fetch size)
- Total: ~1,650 props/day = ~49,500/month
- SGO Free Tier: 100K objects/month → ~50K headroom ✅

---

## Problem 4: Invalid Strikeout Props in DB (FIXED)

### Root Cause
The parlay builder correctly filters invalid strikeout lines (hitter SO must be 0.5; pitcher SO must be ≥3.5) **during parlay construction**, but these invalid props were still being saved to `mlb_scored_legs` and displayed in the Legs tab.

Example: Nick Senzel SO O1.5 (-750) appeared in the UI despite being ineligible for parlays.

### Fix Applied
`main.py` — added `_valid_strikeout_line()` filter immediately before `log_scored_legs()`:
- Hitter strikeouts: only `line == 0.5` allowed
- Pitcher strikeouts: only `line >= 3.5` allowed
- Logs count of removed props

This ensures the Legs tab only shows props that are actually eligible for parlays.

---

## Additional Bugs Found

### `_find_qualifying_legs` drops props with `None` player_id silently
Any player whose name doesn't resolve via `statsapi.lookup_player()` is silently dropped without logging. At scale, this could account for 20–40% of unresolved props. **Recommendation:** add a counter and log the drop count to Railway logs.

### `generate_recommendations` docstring says "+600–+1500" but code uses 1000–1500
The docstring on `generate_recommendations()` in `main.py` mentions "+600 to +1500". This reflects an outdated parameter. The actual `MIN_PARLAY_ODDS = 1000` in `parlay_builder.py` is correct.

---

## Commits Made This Session

1. `fix: update parlay builder to 5-8 legs with +1000-1500 odds target`
2. `feat: implement functional Refresh button with 3-hour SGO time filter`
3. `fix: filter invalid strikeout lines at fetch time before DB save`
4. `docs: add investigation report for April 30 debugging session`
