# MLB Parlay Agent — Build Status

**Last Updated:** 2026-04-18 (after single-pool refactor)  
**Blueprint Version:** v1.0  
**Repo:** github.com/MrGweeod/mlb-agent

---

## Infrastructure Status

| Component | Status | Notes |
|-----------|--------|-------|
| Railway Deployment | ✅ Running | Project: `mlb-agent`, logs clean as of 2026-04-18 18:00 ET |
| Discord Bot | ✅ Connected | Slash commands synced, scheduled tasks active |
| Supabase PostgreSQL | ✅ Live | Same instance as NBA agent, `mlb_*` tables created |
| Environment Variables | ✅ Set | All required vars in Railway Variables |

---

## Codebase Status — Phase Completion

### ✅ Phase 1 — Direct Copies from NBA Agent (Complete)

| Module | File | Status | Notes |
|--------|------|--------|-------|
| Discord bot | `bot.py` | ✅ Done | 3 scheduled runs (9AM/12PM/5:30PM ET), slash commands working |
| Supabase layer | `src/utils/db.py` | ✅ Done | Tables: `mlb_recommendations`, `mlb_parlay_legs`, `mlb_scored_legs`, `mlb_calibration`, `mlb_placed_bets`, `mlb_player_positions`, `pitcher_profiles` |
| Props API | `src/apis/sportsgameodds.py` | ✅ Done | DraftKings MLB props via SportsGameOdds API |
| Parlay builder | `src/engine/parlay_builder.py` | ✅ Done | **ARCHITECTURE CHANGE**: Single scored pool (see below) |
| Claude agent | `src/engine/claude_agent.py` | ✅ Done | LLM analysis with web_search tool |
| Trackers | `src/tracker/*.py` | ✅ Done | All 4 modules: recommendation_logger, outcome_resolver, calibration, bet_logger |

### ✅ Phase 2 — MLB Adaptations (Complete)

| Module | File | Status | Notes |
|--------|------|--------|-------|
| MLB stats | `src/apis/mlb_stats.py` | ✅ Done | MLB-StatsAPI wrapper for game logs, box scores, transactions |
| Coverage calc | `src/engine/coverage.py` | ✅ Done | Handedness-split coverage (RHP vs LHP) with Poisson fallback |
| Trend analysis | `src/pipelines/trend_analysis.py` | ✅ Done | 10/20 game windows, PA stability, HOT/COLD/NEUTRAL labels |
| Matchup logic | `src/apis/matchup.py` | ✅ Done | Pitcher ERA/K9/WHIP rank normalization |
| Leg enrichment | `src/pipelines/enrich_legs.py` | ✅ Done | Prop routing per Blueprint §5.2 |
| Leg scorer | `src/engine/leg_scorer.py` | ✅ Done | Composite scoring with PA stability |
| RotoWire scraper | `src/apis/rotowire.py` | ✅ Done | Lineup/injury page scraper |

### ✅ Phase 3 — New Modules (Complete)

| Module | File | Status | Notes |
|--------|------|--------|-------|
| Main pipeline | `main.py` | ✅ Done | Full 8-step pipeline (see below) |
| Lineup poller | `src/pipelines/lineup_poller.py` | ✅ Done | Confirms lineups 6–8PM ET, rescores legs every 30 min |
| Web server | `src/web/server.py` | ✅ Done | Railway health check endpoint |

---

## Architecture Deviations from Blueprint

### ⚠️ **MAJOR CHANGE: Single Scored Pool (2026-04-18)**

**Blueprint Spec (§6):**
- Two pools: Anchors (≥70% coverage, -500 to -150 odds) + Swings (≥55% coverage, -150 to +250 odds)
- Target: +1000 to +1500 parlays

**Current Implementation:**
- Single pool: All legs ≥55% coverage
- Score all legs with composite formula (40% coverage, 25% EV, 15% trend, 15% opponent, 5% PA stability)
- Take top 20 by `composite_score`
- Branch-and-Bound finds 4-8 leg combos in **+600 to +1500 odds range** (lowered floor from +1000)

**Reason for Change:**
- Two-pool architecture produced 0 parlays on live slates
- High-coverage positive-odds legs (+130–+215) fell into swing bucket but required connector legs (rarely available)
- Single pool with wider odds range (+600–+1500) produces 5 parlays per day on 15-game slates

**Impact:**
- Lower average parlay odds (now +1400–+1500 vs +1100–+2000 target)
- Higher parlay volume (5/day vs 2-3/day expected)
- Better leg diversity (no more "same 2 legs in every parlay" issue from anchor pool dominance)

### ⚠️ **Trend Pass Removed (2026-04-18)**

**Blueprint Spec (§4.2):**
- `trend_pass` boolean gate: Only legs with sufficient trend momentum enter pool

**Current Implementation:**
- `trend_pass` removed entirely
- Trend score (HOT/COLD/NEUTRAL) contributes 15% weight to composite score but does NOT hard-gate eligibility
- Early-season `avg_10 ≈ avg_20` caused near-universal trend_pass failures

**Impact:**
- More legs eligible (no hard trend gate)
- COLD legs can enter pool (risk: might lower overall hit rate)

---

## Pipeline Architecture (main.py)

8-step pipeline runs at 9AM/12PM/5:30PM ET:

1. **Transaction Wire** — `get_transactions()` → filter Status Changes/Designations/Options/Recalls → blocked_names set
2. **Schedule** — `get_schedule()` → build team_id_to_abbr, pitcher_id_map, opponent_map
3. **SGO Props** — `get_todays_games()` + `get_player_props()` per game
4. **Coverage Gate** — `calculate_coverage()` for each batter prop at standard line (min 55%)
5. **Injury Filter** — Transaction wire blocked_names only (LLM check removed)
6. **Enrichment** — `enrich_legs()` adds pitcher signals
7. **Trend Signals** — `get_trend_signal()` per leg
8. **Parlay Builder** — `build_hybrid_parlays()` → `log_recommendations()` + `log_scored_legs()` → `analyze_parlays()` (LLM + web_search)

---

## Known Issues & Workarounds

| Issue | Workaround | Status |
|-------|-----------|--------|
| Pool diversity (same 2 legs in every parlay) | Single-pool refactor fixed this | ✅ Resolved (2026-04-18) |
| Trend pass failing early-season | Removed hard gate, now 15% weight only | ✅ Resolved (2026-04-18) |
| COLD legs entering pool | Accept as tradeoff for larger pool | ⚠️ Monitoring |
| `get_batter_game_log(701678)` error | One player ID in SGO feed returns `list index out of range` | 🐛 Open (low priority) |

---

## What's NOT Built (Roadmap)

| Item | Priority | Reason |
|------|----------|--------|
| Pitcher prop coverage model | Low | Skipped via `_PITCHER_POSITIONS` — Phase 4 extension |
| Weather adjustment | Medium | Outdoor game totals (wind > 15 mph, temp < 45°F) — roadmap |
| HR/9 pitcher signal | Medium | Blueprint §5.2 — currently ERA-only for HR props |
| Baseball Reference scraper | Medium | Pitcher vs batter handedness splits — roadmap |
| Same-game parlay correlation detection | Medium | Pitcher dominance thesis — roadmap |
| Learning loop (weight recalibration) | Low | Requires 500+ resolved legs |
| Dashboard (P&L, hit rates) | Low | After data accumulates |

---

## Validation Status

| Item | Status | Notes |
|------|--------|-------|
| SportsGameOdds API returns MLB props with `fairOdds` | ✅ Validated | Confirmed on 2026-04-17 |
| Pitcher props available in MA on DraftKings | ❓ Unknown | Need manual check on game day |
| MLB-StatsAPI provides real-time box scores | ✅ Validated | Confirmed via `statsapi.boxscore()` |
| Alt lines available for MLB pitcher props | ❓ Unknown | Need to test when markets open |
| Lineup lead time (cards → first pitch) | ❓ Unknown | Observe 3-5 game days at season start |

---

## Recent Fixes (Last 10 Commits)

1. `fc8f85b` — Outcome resolver stat lookup stubs + SGO key mappings for K/BB
2. `ced05de` — **MAJOR:** Single scored pool refactor (replaces two-pool arch)
3. `32d9ef8` — Loosen anchor trend_pass, remove LLM injury check
4. `fe96415` — Four pre-launch cleanup items
5. `320996a` — Strip stat label suffix from SGO marketName
6. `34778e9` — Correct SGO prop key prefix (hitting_ → batting_)
7. `5259067` — Fix `statsapi.teams()` → `statsapi.get('teams')`
8. `7e9d211` — Lower anchor pool eligibility from 70% → 62%
9. `d55c268` — Phase 3 complete: main.py full pipeline
10. `dbd5e7b` — Lineup poller, web server, mobile parlay builder

---

**Blueprint:** `MLB_Parlay_Agent_Blueprint_v1.docx` (original design spec)  
**Session Log:** `SESSION_HANDOFF.md` (tracks what was done each session)  
**Working Notes:** `WORKING_NOTES.md` (open issues, TODOs, decisions)
