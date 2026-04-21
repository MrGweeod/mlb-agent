# MLB Parlay Agent — Build Status

**Last Updated:** 2026-04-21
**Blueprint Version:** v1.0
**Repo:** github.com/MrGweeod/mlb-agent

## Infrastructure Status
| Component | Status | Notes |
|-----------|--------|-------|
| Railway Deployment | ✅ Running | Commit: edf227c |
| Discord Bot | ✅ Connected | Slash commands working, scheduled runs active |
| Web App | ⚠️ Partial | UI works, analyze flow broken, no bet tracking |
| Supabase PostgreSQL | ✅ Live | mlb_* tables active |

## Build Progress

### ✅ Phase 1 — Direct NBA Agent Copies (Complete)
All modules copied and working.

### ✅ Phase 2 — MLB Adaptations (Complete)
All modules adapted for MLB including pitcher K props.

### ⚠️ Phase 3 — New Modules (Partial)
| Module | Status | Notes |
|--------|--------|-------|
| main.py pipeline | ✅ Done | Full 8-step pipeline with pitcher K props |
| Web app UI | ✅ Done | Interactive parlay builder complete |
| Web app backend | ⚠️ Partial | /api/legs works, /api/analyze missing, no bet tracking |
| Bet tracking | ❌ Not built | mlb_placed_bets table doesn't exist yet |

## Recent Changes (April 21, 2026)

**Pitcher Strikeout Props:**
- Added `calculate_pitcher_k_coverage()` using Poisson distribution
- Removed pipeline blocking gates for pitcher K props
- Result: 278 pitcher K props now eligible (up from 0)

**Interactive Web App:**
- Complete parlay builder with selection, correlation blocking, odds calculation
- Mobile-first responsive design
- Issue: analyze button shows modal instead of calling API

## What's NOT Built
| Item | Priority | Notes |
|------|----------|-------|
| Bet tracking system | HIGH | No mlb_placed_bets table, no /api/bets endpoints |
| Web app analyze flow | HIGH | Shows modal instead of calling Claude API |
| Bet history UI | HIGH | Can't view placed bets or outcomes |
| Pipeline cleanup | MEDIUM | Still generating unused automated parlays |
| Pool diversity fix | MEDIUM | Same 2 legs anchor every parlay |
| Pitcher IP/HA/ER props | LOW | Only K props enabled, others skipped |
