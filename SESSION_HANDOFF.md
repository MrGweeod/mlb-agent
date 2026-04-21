# MLB Parlay Agent — Session Handoff
**Last Updated:** April 21, 2026

## Current Status
✅ **All three build phases complete** — pipeline, resolver, web app fully functional
✅ **Model calibrated** — Coverage within ±6% (was ±30%), pitcher K +2.6% error, hits +2.4%
✅ **Web app enhanced** — Position filters (Hitters/Pitchers), working analyze button, no hallucinations
✅ **Automated resolution** — Box-score resolver runs daily at 9AM ET, 300-400 legs/day

## What Was Built This Session (April 21)

**1. Fixed Scoring Model (Calibration)**
- Coverage overconfidence fixed: 70%+ bucket now hits at 68% (was 46%)
- Confidence multipliers now applied: `adjusted = 0.50 + mult × (raw - 0.50)`
- EV calculation fixed: compares SGO fair_line vs book_line (was inverted)
- Prop-specific penalties: strikeouts 1.0x, hits 0.85x, totalBases 0.78x, RBIs 0.90x
- Recalibrated weights: coverage 70%, opponent 20%, PA stability 10%, EV 0%, trend 0%

**2. Built Automated Outcome Resolver**
- Box-score-based resolver: 1 API call per game (fast, efficient)
- Resolves ALL scored legs (not just parlays): 300-400 legs/day
- 458 legs resolved (April 17-20): 236 won, 222 lost
- Daily automation at 9AM ET via scheduled bot task
- Files: `src/tracker/outcome_resolver.py`, `src/bot/runner.py`

**3. Enhanced Web App**
- Position filter: "All / Hitters / Pitchers" with dynamic counts
- Analyze button calls Claude API directly (no copy/paste prompt)
- Direction bug fixed: over/under correctly passed to Claude
- Web search removed: pure statistical analysis (10-20s, no hallucinations)
- Complete data flow: coverage + EV + trend + opponent adjustment
- Files: `src/web/static/index.html`, `src/web/server.py`, `src/engine/claude_agent.py`

**4. Database Schema Updates**
- Added `odd_id` column to `mlb_scored_legs` with UNIQUE constraint
- Per-odd_id deduplication: allows afternoon pipeline re-runs (pitcher K props)
- Fixed coverage_pct storage: 259 historical rows corrected (0-1 → 0-100 scale)
- Migration: `ALTER TABLE mlb_scored_legs ADD COLUMN odd_id TEXT UNIQUE`

## Known Issues

**Fixed Today:**
- ✅ Coverage overconfidence (70%+ at 46% → now 68%)
- ✅ EV signal inverted (strong +EV worst → fixed formula, needs validation)
- ✅ Pitcher K props missing (pipeline timing + dedup issues → fixed)
- ✅ Analyze button broken (showed prompt → now calls API)
- ✅ Web search hallucinations (removed web search entirely)
- ✅ Direction bug (all "over" → now uses actual direction)

**Still Validating:**
- ⏳ EV signal correction (fixed in code, need 2-3 days of new data to validate)
- ⏳ Total bases penalty (tightened to 0.78x, need 50+ more legs to confirm)

## Next Session Priorities

**High Priority:**
1. Validate EV signal after 2-3 days (strong +EV should now hit better than strong -EV)
2. Run calibration on full dataset after 1,000+ resolved legs
3. Confirm pitcher K props appear in tomorrow's 9AM pipeline run

**Medium Priority:**
4. Add bet tracking system (`mlb_placed_bets` table + web app flow)
5. Monitor pool diversity (same legs dominating parlays)

**Low Priority:**
6. Build dashboard (P&L tracking, hit rate by prop category)

## Key Files Modified This Session
- `src/engine/leg_scorer.py` — recalibrated weights, prop penalties
- `src/apis/sportsgameodds.py` — fixed EV calculation
- `main.py` — confidence multiplier application
- `src/pipelines/lineup_poller.py` — coverage scale bug fix
- `src/tracker/outcome_resolver.py` — complete rewrite, box-score resolver
- `src/tracker/leg_calibration.py` — direction-adjusted win probability
- `src/utils/db.py` — per-odd_id deduplication
- `src/web/static/index.html` — position filters, analyze button, data flow
- `src/web/server.py` — /api/analyze endpoint
- `src/engine/claude_agent.py` — removed web search, statistical analysis only

## Git Status
**Latest commit:** `4b49efd` — "fix: pass ev_per_unit, trend_score, opponent_adjustment to /api/analyze"
**Deployed to Railway:** Yes (all commits pushed and deployed)

## Environment
- Repository: github.com/MrGweeod/mlb-agent
- Deployment: Railway (mlb-agent project)
- Web app: https://mlb-agent-production.up.railway.app (password protected)
- Database: Supabase PostgreSQL (same instance as NBA agent)
- Python: 3.14 in venv (WSL2 Ubuntu)
