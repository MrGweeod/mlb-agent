MLB Parlay Agent — Project Instructions
Repository: github.com/MrGweeod/mlb-agent
Stack: Python 3.10, PostgreSQL (Supabase), Railway, Discord bot, MLB-StatsAPI
Full Technical Blueprint: MLB_Parlay_Agent_Blueprint_v1.docx (read for architecture, data sources, build order)

Project Overview
AI-powered MLB parlay recommendation system adapted from NBA Parlay Agent v6.0. Uses Branch-and-Bound parlay construction, composite five-factor leg scoring, and pitcher-aware matchup logic to generate 5-8 leg parlays targeting +1000 to +1500 odds.
Single-Pool Strategy (Updated 2026-04-18)

All legs ≥55% coverage scored with composite formula
Top 20 legs by composite score enter parlay builder
Branch-and-Bound finds 4-8 leg combinations in +600 to +1500 odds range
Constraints: Max 1 batter leg per player, max 3 legs per game

Daily Schedule (9AM/12PM/5:30PM ET)

9:00 AM: Resolve last night + fresh pipeline
12:00 PM: Updated transactions, refreshed odds
5:30 PM: Final pipeline before first pitches

Discord Commands

/run — Trigger full pipeline manually
/resolve — Run outcome resolver on pending bets
/status — Show pending recommendations
/calibration — Show calibration report on resolved legs
/dashboard — Performance dashboard (hit rates, P&L, trends)


Current Status (Updated: 2026-04-18)
✅ All Three Phases Complete

Railway deployment: Running (mlb-agent project)
Discord bot: Connected (slash commands synced, 3 daily runs active)
Web app: Deployed at Railway URL (interactive parlay builder)
Supabase: All mlb_* tables created and active
Environment variables: Set in Railway
Last confirmed run: 157 eligible legs, 5 parlays (+1441–+1482)

What Works:

Discord bot posts AI recommendations 3x/day (9AM/12PM/5:30PM ET)
Web app allows manual parlay building with real-time odds calculation
Lineup poller rescores legs every 30min from 6-8PM ET when lineups confirm
Full 8-step pipeline with pitcher-aware matchup logic
Single scored pool producing 5 parlays/day on 15-game slates


Workflow Rules — Cost & Efficiency Optimization
When to Use Manual Actions (You)
Always prefer manual actions when possible — they're free and often faster than spinning up Claude Code.
✅ Use Terminal/Web UI For:

Updating environment variables (Railway, Discord Developer Portal, Supabase)
Checking Railway logs, deployment status
Git operations: git pull, git status, git commit, git push
Reading small files: cat README.md, less bot.py
Installing packages: pip install -r requirements.txt
Running the bot locally: python bot.py
Supabase: Table Editor for schema inspection, SQL Editor for queries
GitHub: Creating repos, branches, reviewing diffs
Discord Developer Portal: Creating bots, copying tokens, generating invite URLs

When to Use Claude Chat (This Session)
Use Claude Chat for strategy, planning, and small code reviews.
✅ Use Claude Chat For:

Architecture decisions, debugging strategy, interpreting error logs
Reviewing pasted code snippets (< 100 lines) — paste code here instead of asking Claude Code to view it
Writing SQL queries, environment variable templates, config snippets
Explaining errors or suggesting targeted fixes
Planning multi-step workflows before execution
Cost-benefit analysis on whether a task needs Claude Code at all

When to Use Claude Code
Use Claude Code only for actual coding work that requires file editing.
✅ Use Claude Code For:

Writing or editing Python files (> 20 lines of changes)
Refactoring modules, adding new features
Running tests, linters, formatters across the codebase
Debugging errors that require reading multiple interconnected files
Building new pipelines, data models, or API integrations

Decision Tree — Which Tool?
Before starting any task, ask:

Can I do this manually in < 5 minutes? → Do it yourself (free)
Can I paste the code here and get a fix in chat? → Use Claude Chat (minimal cost)
Does this require editing/creating multiple Python files? → Use Claude Code (necessary cost)

API Key & Token Hygiene

❌ Never paste raw API keys or tokens in chat or Claude Code sessions
✅ Use placeholders: ANTHROPIC_API_KEY=your_key_here
✅ Store all secrets in Railway Variables, never in .env files committed to GitHub
✅ Use .env.example as a template with placeholder values only

Git Workflow

Always git pull origin main before starting work
Commit small, logical units: "Add pitcher handedness split logic" not "Updates"
Push after every working session: git push origin main
Use branches only for experimental features, not for daily work

Railway Workflow

Check logs in Railway UI before asking for help
Redeploy after environment variable changes (Railway → Deployments → Redeploy)
Monitor build times — if builds take > 3 minutes, investigate dependency caching

Supabase Workflow

Use Table Editor (web UI) for schema inspection — no code needed
Use SQL Editor for complex queries or bulk updates
Export table data as CSV for local analysis before writing code to process it


Web App — Interactive Parlay Builder
Access: Railway deployment URL → Enter WEB_APP_PASSWORD when prompted
Purpose: Manual parlay building with real-time feedback (Discord bot only posts AI recommendations)
Features:

Browse today's scored legs with coverage %, composite score, lineup status
Tap legs to select 4-8 for a parlay
Real-time combined odds calculation
Correlation blocking (pitcher/batter same game, max 2 legs per game)
"Reaches target" filter (highlights legs bringing odds into +1000-1500 range)
Auto-polls /api/legs every 5min for lineup updates
Mobile-first responsive design

Workflow:

Visit Railway URL in browser
Enter WEB_APP_PASSWORD
Review scored legs (green checkmark = lineup confirmed, amber clock = pending)
Select 4-8 legs by tapping cards
Submit for Claude analysis or place bet manually

Technical:

Runs on same Railway service as Discord bot (no extra cost)
Single-file HTML app (17.5 KB, vanilla JS, no build step)
Backend: src/web/server.py (aiohttp server)
Frontend: src/web/static/index.html
Data: Fetches from Supabase via /api/legs endpoint


Key MLB-Specific Differences from NBA Agent
If you're familiar with the NBA agent, these are the critical changes:
ComponentNBA AgentMLB AgentStats APInba_apiMLB-StatsAPI (pip install MLB-StatsAPI)Injury dataOfficial NBA injury PDFMLB Transaction Wire via statsapi.get('transactions')Matchup logicTeam DEF_RATING, paint/3P suppressionPitcher ERA/K9/WHIP profilesCoverage calculationOverall season hit rateSplit by opposing pitcher handedness (RHP vs LHP)Trend windows5/10/15 game rolling windows10/20 game rolling windowsStability metricMinutes stability (last 5 vs prior 10)Plate appearance stability + batting order positionLineup confirmationNBA injury PDF at 5:30 PM ETStarting lineups posted ~3.5 hours before first pitch
Most Important: Every batter's coverage rate must be calculated separately for games vs RHP and vs LHP. A .280 hitter vs RHP but .320 vs LHP facing a LHP tonight has a different edge than overall season average suggests.

Build Order Reference
See Section 10 of MLB_Parlay_Agent_Blueprint_v1.docx for full build order.
Phase 1: Direct copies from NBA agent (Discord bot, database, parlay builder, Claude agent)
Phase 2: MLB adaptations (MLB-StatsAPI, coverage calculator, pitcher matchup logic, leg scorer)
Phase 3: New modules (Transaction Wire, lineup confirmation, main pipeline, web app)
Before building each module: Check if it already exists in the repo. Don't rebuild what's already there.

Validation Checklist Before Building
Complete these before writing any Phase 2/3 code:

 Verify SportsGameOdds API returns MLB props with fairOdds field (test with sport='MLB')
 Verify pitcher prop markets (Strikeouts, Innings Pitched) are available on DraftKings in Massachusetts
 Verify MLB-StatsAPI provides real-time box scores for same-day outcome resolution
 Test that alt lines are available for MLB pitcher props on SGO
 Confirm all environment variables are set in Railway: SPORTSGAMEODDS_API_KEY, ODDS_API_KEY, ANTHROPIC_API_KEY, DATABASE_URL, DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, SCHEDULE_CHANNEL_ID, WEB_APP_PASSWORD


For Claude Code Sessions
When starting a Claude Code session:

Always read these files first:

PROJECT_INSTRUCTIONS.md (this file)
SESSION_HANDOFF.md (tracks what was done in the last session)
ARCHITECTURE_DECISIONS.md (tracks major architectural decisions)
BUILD_STATUS.md (tracks what's built vs what's missing)


Check existing code before suggesting changes — use view or git log to see what's already there
Prefer targeted fixes over rewrites — if a function works, don't rewrite it just to match a different style
Commit and push at the end of every logical unit of work — don't wait until the end of the session
Update SESSION_HANDOFF.md before ending the session — document what was built, what's next, any blockers


For Claude Chat Sessions
When working in Claude Chat (Desktop Project):

This session has access to uploaded files only — if you need to reference code, paste it here or upload the file
Before asking for code changes, paste the relevant code here first — saves Claude Code tokens
Use this session for planning, strategy, and small fixes — escalate to Claude Code only when you need to edit multiple files
Document decisions in ARCHITECTURE_DECISIONS.md — if we decide on an architectural approach, add it to the notes so Claude Code sessions can reference it


Common Commands Reference
Local Development
bash# Start bot locally
python bot.py

# Run a manual pipeline test
python -c "from main import run_pipeline; run_pipeline()"

# Check what's been built
ls -la src/apis/
ls -la src/engine/
ls -la src/pipelines/

# View recent commits
git log --oneline -10
Railway
bash# View logs (web UI is easier)
railway logs

# Redeploy
railway up
API Testing
python# Test SportsGameOdds API for MLB props
import requests
api_key = "YOUR_KEY"
response = requests.get(
    "https://api.sportsgameodds.com/v1/props",
    params={"sport": "MLB", "apiKey": api_key}
)
print(response.json()[:2])

When You Get Stuck

Check Railway logs first — 90% of deployment issues show up there
Paste error messages in Claude Chat — get a diagnosis before spinning up Claude Code
Verify environment variables — missing or misnamed vars cause silent failures
Check Discord Developer Portal — bot permissions issues are common and easy to fix manually
Review SESSION_HANDOFF.md — previous sessions may have documented known issues


For full technical details, architecture diagrams, and MLB-specific implementation notes, see MLB_Parlay_Agent_Blueprint_v1.docx.
