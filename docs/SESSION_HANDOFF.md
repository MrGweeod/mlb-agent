# MLB Parlay Agent — Session Handoff
**Last Updated:** May 28, 2026 (Session 2 — Team SO Signal + Anchor/Swing Architecture)

## Current Status
✅ **OPERATIONAL — SESSION 2 DEPLOYED**
✅ **Anchor/Swing 5-leg parlay structure live**
✅ **Consistency signal deployed (enriched + production)**
✅ **Signal 4: Team SO Rank live in shadow pipeline**
✅ **Neutral consistency branch bug fixed**
✅ **Shadow pipeline: 4 signals fully operational**

---

## What Happened on May 28, 2026

### **Major Architecture Change — Anchor/Swing Parlay Structure**
Replaced the single-pool 4-leg +700–+1000 system with a 3-anchor + 2-swing 5-leg +900–+1100 structure.

- Anchor pool: `coverage_overall >= 75%`, odds `-300 to -150`
- Swing pool: `coverage_overall >= 55%`, odds `-150 to +150`
- All 4 call sites updated: `main.py` (×2), `server.py`, `run_enriched_pipeline.py`
- Shadow pipeline inherits new structure automatically

**Anchor pool win rates (data at time of decision):**
- SO over: 77.9%
- Hits under: 73.4%
- Hits over: 72.8%

**Swing pool win rates:**
- Hits under: 68.4%
- SO under: 62.5%
- TB under: 61.0%

---

### **Scoring Fixes (May 28)**
- Consistency signal added to both `simple_scorer.py` and `enriched_scorer.py`:
  - `gap = coverage_overall - coverage_recent_10`
  - gap ≥ 20 → -6, gap ≥ 12 → -4, gap ≥ 6 → -2, gap ≤ -10 → +2, gap ≤ -5 → +1, else → 0
- Removed +3 handedness bonus from `simple_scorer.py` (was double-counting with `coverage_vs_hand` base)
- Fixed neutral consistency branch bug in `enriched_scorer.py` (`score += 1` → `score += 0`)
- Pitcher `coverage_recent_5` renamed to `coverage_recent_10` in `coverage.py` (key mismatch was causing NULL for all pitchers)

---

### **Pipeline / Data Fixes (May 28)**
- `get_scored_legs()` in `src/utils/db.py` now partitions by `player_name, stat, direction` and orders by `logged_at DESC` — prevents stale lines from earlier pipeline runs appearing in regenerate
- Minimum pitcher SO line raised from 3.5 to 4.5 (3.5 line wins at 47.8%/44.7%)
- Pitcher SO unders blocked below 6.5 line (4.5u=47.2%, 5.5u=51.9%)

---

### **Signal 4: Team SO Rank — Shadow Pipeline**

Added opposing team strikeout ranking as the 4th enriched scoring signal.

**Motivation:** Jack Flaherty had 70% coverage on SO under 6.5 but was facing LAA (league-leading K lineup). He accumulated 7 Ks in 5.2 IP — the prop lost. The scorer had zero awareness of opposing lineup K-proneness.

**Implementation:**
- `get_team_strikeout_stats(season)` added to `mlb_stats.py`
  - Season SO rank: `/api/v1/teams/stats?stats=season` — 30 teams
  - Recent rank: `/api/v1/teams/stats?stats=byDateRange` with 14-day window (note: `lastXGames` with `limit=10` filters team count not game count — `byDateRange` is the correct approach)
  - 24hr TTL cache, refreshed at 9 AM
- `_compute_team_so_adjustment()` in `enriched_scorer.py`
  - Applies only to pitcher SO props (`position in _PITCHER_POSITIONS`, `stat == 'strikeouts'`)
  - Season rank primary signal: rank 1–8 → ±5, rank 9–15 → ±2, rank 16–22 → ∓2, rank 23–30 → ∓5
  - Recent rank modifier: rank 1–8 → +2, rank 23–30 → -2, else → 0
  - Net capped at ±6
  - Sign-flipped for unders (high-K lineup = penalty for SO unders, the Flaherty case)
- `team_so_adjustment` column added to `mlb_scored_legs_enriched`

**Validated test results:**
- LAA (rank 1): Flaherty SO under → -6.0, SO over → +6.0
- Batter hits prop → None (correctly scoped)

**Commits today:**
- `9f49aa3` — Anchor/swing + consistency signal + pitcher coverage_recent_10 + scoring fixes
- `5ff62f6` — get_scored_legs latest logged_at fix
- `0883f65` — Pitcher SO line minimum raised to 4.5
- `4747588` — Pitcher SO unders blocked below 6.5
- (Team SO signal commit) — Signal 4 + neutral consistency fix + DB migration

---

## Pending Items — Next Session

### **1. Validate Pitcher `coverage_recent_10` (Manual — Next 9 AM Pipeline)**
The pitcher `coverage_recent_10` was NULL yesterday due to the 24hr game log cache. Tomorrow's 9 AM pipeline will fetch fresh logs.

**Query to run after 9 AM:**
```sql
SELECT player_name, stat, coverage_overall, coverage_recent_10,
       (coverage_overall - coverage_recent_10) as gap, composite_score
FROM mlb_scored_legs
WHERE run_date = CURRENT_DATE::text
  AND stat IN ('strikeouts', 'hitsAllowed', 'earnedRuns', 'inningsPitched')
  AND coverage_recent_10 IS NOT NULL
ORDER BY gap DESC;
```

### **2. Validate Consistency Signal on Fresh Data (Manual — Next 9 AM Pipeline)**
First clean read on whether penalties are firing correctly for pitchers.

**Query to run:**
```sql
SELECT player_name, stat, coverage_overall, coverage_recent_10,
       (coverage_overall - coverage_recent_10) as gap, composite_score
FROM mlb_scored_legs
WHERE run_date = CURRENT_DATE::text
  AND coverage_recent_10 IS NOT NULL
ORDER BY gap DESC
LIMIT 30;
```
High-gap (cold) legs should have noticeably lower composite scores.

### **3. Validate Team SO Signal in Enriched Table (Manual — Next Pipeline Run)**
After the next enriched pipeline run, confirm `team_so_adjustment` is populating:

```sql
SELECT player_name, stat, direction, line,
       coverage_overall, team_so_adjustment, composite_score
FROM mlb_scored_legs_enriched
WHERE run_date = CURRENT_DATE
  AND stat = 'strikeouts'
  AND team_so_adjustment IS NOT NULL
ORDER BY team_so_adjustment DESC;
```

### **4. Gate 3 — Minimum `coverage_recent_10` Floor (Discussed, Not Built)**
Proposed: block any leg where `coverage_recent_10 < 50%` regardless of `coverage_overall`. Prevents cold-streak legs sneaking through on strong season averages. Deferred — validate consistency signal first.

### **5. `won_with_void` Outcome Tracking (Claude Code — Medium Priority)**
Add `"won_with_void"` outcome value in `src/tracker/parlay_outcome_resolver.py`.

### **6. Dead ERA/Pitcher Adjustment Cleanup (Claude Code — Low Priority)**
`opponent_adjustment` has returned 0 for 100% of legs over 14 days — the signal isn't firing. Worth removing from `simple_scorer.py` in a future cleanup session to reduce noise.

### **7. Shadow Pipeline Comparison Analysis (June 1–2)**
Compare enriched vs production win rates after sufficient data accumulates with Signal 4 live. Now has clean data from May 28 onward with all 4 signals running.

---

## Key Data Points

- ERA/pitcher adjustments in `simple_scorer` are effectively dead (opponent_adjustment = 0 for 100% of legs over 14 days)
- Plus-money props DO exist some days (hits under +102 to +123) but not at scale
- Pitcher SO 3.5 line: 47.8% over / 44.7% under — confirmed noise, now blocked
- Pitcher SO unders: 4.5u=47.2%, 5.5u=51.9%, 6.5u=40.7% — all weak, now blocked below 6.5
- `lastXGames` MLB Stats API param `limit=N` filters team count, not game count — use `byDateRange` for windowed team stats

---

## System Health Indicators

### **Green Lights**
- ✅ Anchor/swing structure live and producing parlays
- ✅ Coverage gates (Gate 1 + Gate 2) correctly enforced
- ✅ Shadow pipeline: all 4 signals operational
- ✅ Team SO stats: 30 teams loading, 24hr cache working
- ✅ Pitcher SO line filters in place (min 4.5, unders blocked below 6.5)
- ✅ Pipeline scheduler reliable (3×/day)
- ✅ 9 AM morning pipeline producing parlays
- ✅ DB schema consistent (team_so_adjustment column added)

### **Yellow Flags**
- ⚠️ Parlay win rate at ~11% — anchor/swing + consistency signal under evaluation, monitor 5–7 days
- ⚠️ Pitcher coverage_recent_10 not yet validated (cache lag from yesterday)
- ⚠️ Score-outcome correlation mildly inverted in production — ERA/K-rate adjustments under review
- ⚠️ Gate 3 (min recent coverage floor) deferred pending consistency signal data

### **Red Flags**
- None currently

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

**Last Review:** May 28, 2026
**System Status:** ✅ Operational — Signal 4 Deployed to Shadow Pipeline
**Next Review:** May 29, 2026 (Validate pitcher coverage_recent_10 + consistency signal + team SO adjustment on fresh data)
**Pending Code Changes:** Gate 3 (after validation), won_with_void tracking, dead ERA adjustment cleanup
