# MLB Parlay Agent — Session Handoff
**Last Updated:** April 21, 2026

## Current Status
✅ **Web app deployed and functional** — interactive parlay builder with selection, correlation blocking, combined odds
✅ **Pitcher K props enabled** — Poisson coverage model implemented, 278 pitcher K props available
⚠️ **Web app needs work** — analyze button broken (shows modal instead of analyzing), no bet tracking system
⚠️ **Pipeline needs cleanup** — still generating automated parlays 3x/day (wasting tokens)

## What Was Built This Session (April 21)

**Interactive Web App Parlay Builder:**
- Click to select legs (4-8 leg limit)
- Real-time combined odds calculation
- Correlation blocking (max 1 leg per player, max 2 per game, no pitcher+batter same game)
- "Reaches target" indicator for legs that bring odds into +1000-1500 range
- Mobile-first responsive design (bottom drawer on mobile, right sidebar on desktop)
- File: `src/web/static/index.html` (17.5 KB single-file app)

**Pitcher Strikeout Props:**
- Added `calculate_pitcher_k_coverage()` to `src/engine/coverage.py`
- Uses Poisson distribution based on season K/game rate (prefers games started, falls back to games pitched)
- Minimum 3 appearances required for reliability
- Removed blocking gates in `main.py` for pitcher K props
- Fixed `leg_scorer.py` to route pitcher props correctly
- Result: 278 pitcher K props now available (up from 0)
- Files modified: `src/engine/coverage.py`, `main.py`, `src/engine/leg_scorer.py`

## Known Issues

**High Priority:**
1. **Web app analyze flow broken** — "Analyze Parlay" button shows modal with prompt text instead of calling Claude API
2. **No bet tracking** — can't log bets or track outcomes
3. **Pitcher props not visible in web app** — need to debug (props exist in pipeline but not displaying)

**Medium Priority:**
4. **Pool diversity** — same 2 legs (Del Castillo + Hicks RBI) anchor all 5 parlays every day
5. **Pipeline wastes tokens** — generates automated parlays 3x/day that aren't used

## Architecture Debt from NBA Agent

**Current (Legacy):**
- Discord bot posts automated parlay recommendations 3x/day
- Pipeline runs: resolve + fetch props + build parlays + Claude analysis → Discord
- Web app is secondary (manual parlay builder with broken submit flow)

**Desired (User-Defined):**
- Web app is primary interface: browse legs → build parlay → analyze → place bet → auto-resolve
- Morning run (9AM): resolve yesterday's legs + bets, fetch today's props, score legs (no parlay building)
- Midday/evening runs (12PM/5:30PM): refresh odds, check lineups, rescore legs (no parlay building)
- Claude analysis: only triggered manually from web app (not automated)
- Bet tracking: user places bets via web app, resolver checks them next day

## Next Session Priority

**Goal:** Make web app fully functional with bet tracking (Option C from session discussion)

**Tasks:**
1. Create `mlb_placed_bets` table in Supabase
2. Add `/api/analyze` endpoint — calls Claude API directly, returns analysis
3. Add `/api/bets` endpoints — POST to place bet, GET for bet history
4. Fix web app analyze flow — remove modal fallback, call API directly
5. Add "Place Bet" button (appears after analysis)
6. Add "Bet History" view in web app
7. Update `outcome_resolver.py` to resolve placed bets
8. Clean up pipeline: remove automated parlay generation from scheduled runs

**Estimated time:** 3-4 hours in Claude Code

## Key Files Modified This Session
- `src/web/static/index.html` — full parlay builder UI
- `src/engine/coverage.py` — pitcher K coverage model
- `main.py` — removed pitcher K blocking gates
- `src/engine/leg_scorer.py` — pitcher prop routing

## Git Status
**Latest commit:** `edf227c` — "feat: enable pitcher strikeout props with Poisson coverage model"
**Deployed to Railway:** Yes (deployment successful)

## Environment
- Repository: github.com/MrGweeod/mlb-agent
- Deployment: Railway (mlb-agent project)
- Web app: https://mlb-agent.up.railway.app
- Database: Supabase PostgreSQL (same instance as NBA agent)
- Python: 3.14 in venv (WSL2 Ubuntu)
