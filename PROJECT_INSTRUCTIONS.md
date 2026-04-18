# MLB Parlay Agent — Project Instructions

**Repository:** github.com/MrGweeod/mlb-agent  
**Stack:** Python 3.10, PostgreSQL (Supabase), Railway, Discord bot, MLB-StatsAPI  
**Full Technical Blueprint:** `MLB_Parlay_Agent_Blueprint_v1.docx` (read for architecture, data sources, build order)

---

## **Project Overview**

AI-powered MLB parlay recommendation system adapted from NBA Parlay Agent v6.0. Uses Branch-and-Bound parlay construction, composite five-factor leg scoring, and pitcher-aware matchup logic to generate 4-6 leg parlays targeting +1100 to +2000 odds.

### **Two-Pool Strategy**
- **Anchor legs:** Coverage ≥70%, odds -500 to -150, 2-4 per parlay (foundation)
- **Swing legs:** Coverage ≥55%, odds -150 to +250, exactly 2 per parlay (payout multipliers)

### **Daily Schedule** (9AM/12PM/5:30PM ET)
- 9:00 AM: Resolve last night + fresh pipeline
- 12:00 PM: Updated transactions, refreshed odds
- 5:30 PM: Final pipeline before first pitches

### **Discord Commands**
- `/run` — Trigger full pipeline manually
- `/resolve` — Run outcome resolver on pending bets
- `/status` — Show pending recommendations
- `/calibration` — Show calibration report on resolved legs
- `/dashboard` — Performance dashboard (hit rates, P&L, trends)

---

## **Current Status** (Updated: 2026-04-18)

✅ **Infrastructure Ready**
- Railway deployment: Running (`mlb-agent` project)
- Discord bot: Connected (slash commands synced)
- Supabase: Tables created (need to verify schema)
- Environment variables: Set in Railway

❓ **Codebase Status** (Need to verify)
- Phase 1 modules (direct copies from NBA agent): Unknown
- Phase 2 modules (MLB adaptations): Unknown
- Phase 3 modules (new builds): Unknown

**Next Action:** Inspect local repo structure to determine what's built and what's missing.

---

## **Workflow Rules — Cost & Efficiency Optimization**

### **When to Use Manual Actions (You)**

Always prefer manual actions when possible — they're free and often faster than spinning up Claude Code.

✅ **Use Terminal/Web UI For:**
- Updating environment variables (Railway, Discord Developer Portal, Supabase)
- Checking Railway logs, deployment status
- Git operations: `git pull`, `git status`, `git commit`, `git push`
- Reading small files: `cat README.md`, `less bot.py`
- Installing packages: `pip install -r requirements.txt`
- Running the bot locally: `python bot.py`
- Supabase: Table Editor for schema inspection, SQL Editor for queries
- GitHub: Creating repos, branches, reviewing diffs
- Discord Developer Portal: Creating bots, copying tokens, generating invite URLs

### **When to Use Claude Chat (This Session)**

Use Claude Chat for strategy, planning, and small code reviews.

✅ **Use Claude Chat For:**
- Architecture decisions, debugging strategy, interpreting error logs
- Reviewing **pasted code snippets** (< 100 lines) — paste code here instead of asking Claude Code to view it
- Writing SQL queries, environment variable templates, config snippets
- Explaining errors or suggesting targeted fixes
- Planning multi-step workflows before execution
- Cost-benefit analysis on whether a task needs Claude Code at all

### **When to Use Claude Code**

Use Claude Code only for actual coding work that requires file editing.

✅ **Use Claude Code For:**
- Writing or editing Python files (> 20 lines of changes)
- Refactoring modules, adding new features
- Running tests, linters, formatters across the codebase
- Debugging errors that require reading multiple interconnected files
- Building new pipelines, data models, or API integrations

### **Decision Tree — Which Tool?**

Before starting any task, ask:

1. **Can I do this manually in < 5 minutes?** → Do it yourself (free)
2. **Can I paste the code here and get a fix in chat?** → Use Claude Chat (minimal cost)
3. **Does this require editing/creating multiple Python files?** → Use Claude Code (necessary cost)

### **API Key & Token Hygiene**

- ❌ **Never paste raw API keys or tokens** in chat or Claude Code sessions
- ✅ **Use placeholders:** `ANTHROPIC_API_KEY=your_key_here`
- ✅ **Store all secrets in Railway Variables**, never in `.env` files committed to GitHub
- ✅ **Use `.env.example`** as a template with placeholder values only

### **Git Workflow**

- Always `git pull origin main` before starting work
- Commit small, logical units: "Add pitcher handedness split logic" not "Updates"
- Push after every working session: `git push origin main`
- Use branches only for experimental features, not for daily work

### **Railway Workflow**

- Check logs in Railway UI before asking for help
- Redeploy after environment variable changes (Railway → Deployments → Redeploy)
- Monitor build times — if builds take > 3 minutes, investigate dependency caching

### **Supabase Workflow**

- Use Table Editor (web UI) for schema inspection — no code needed
- Use SQL Editor for complex queries or bulk updates
- Export table data as CSV for local analysis before writing code to process it

---

## **Key MLB-Specific Differences from NBA Agent**

If you're familiar with the NBA agent, these are the critical changes:

| **Component** | **NBA Agent** | **MLB Agent** |
|---------------|---------------|---------------|
| **Stats API** | nba_api | MLB-StatsAPI (pip install MLB-StatsAPI) |
| **Injury data** | Official NBA injury PDF | MLB Transaction Wire via `statsapi.get('transactions')` |
| **Matchup logic** | Team DEF_RATING, paint/3P suppression | Pitcher ERA/K9/WHIP profiles |
| **Coverage calculation** | Overall season hit rate | **Split by opposing pitcher handedness (RHP vs LHP)** |
| **Trend windows** | 5/10/15 game rolling windows | 10/20 game rolling windows |
| **Stability metric** | Minutes stability (last 5 vs prior 10) | Plate appearance stability + batting order position |
| **Lineup confirmation** | NBA injury PDF at 5:30 PM ET | Starting lineups posted ~3.5 hours before first pitch |

**Most Important:** Every batter's coverage rate must be calculated separately for games vs RHP and vs LHP. A .280 hitter vs RHP but .320 vs LHP facing a LHP tonight has a different edge than overall season average suggests.

---

## **Build Order Reference**

See **Section 10** of `MLB_Parlay_Agent_Blueprint_v1.docx` for full build order.

**Phase 1:** Direct copies from NBA agent (Discord bot, database, parlay builder, Claude agent)  
**Phase 2:** MLB adaptations (MLB-StatsAPI, coverage calculator, pitcher matchup logic, leg scorer)  
**Phase 3:** New modules (Transaction Wire, lineup confirmation, main pipeline)

**Before building each module:** Check if it already exists in the repo. Don't rebuild what's already there.

---

## **Validation Checklist Before Building**

Complete these before writing any Phase 2/3 code:

- [ ] Verify SportsGameOdds API returns MLB props with `fairOdds` field (test with `sport='MLB'`)
- [ ] Verify pitcher prop markets (Strikeouts, Innings Pitched) are available on DraftKings in Massachusetts
- [ ] Verify MLB-StatsAPI provides real-time box scores for same-day outcome resolution
- [ ] Test that alt lines are available for MLB pitcher props on SGO
- [ ] Confirm all environment variables are set in Railway: `SPORTSGAMEODDS_API_KEY`, `ODDS_API_KEY`, `ANTHROPIC_API_KEY`, `DATABASE_URL`, `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `SCHEDULE_CHANNEL_ID`

---

## **For Claude Code Sessions**

When starting a Claude Code session:

1. **Always read these files first:**
   - `PROJECT_INSTRUCTIONS.md` (this file)
   - `SESSION_HANDOFF.md` (tracks what was done in the last session)
   - `WORKING_NOTES.md` (tracks open issues, TODOs, decisions)

2. **Check existing code before suggesting changes** — use `view` or `git log` to see what's already there

3. **Prefer targeted fixes over rewrites** — if a function works, don't rewrite it just to match a different style

4. **Commit and push at the end of every logical unit of work** — don't wait until the end of the session

5. **Update SESSION_HANDOFF.md before ending the session** — document what was built, what's next, any blockers

---

## **For Claude Chat Sessions**

When working in Claude Chat (Desktop Project):

1. **This session has access to uploaded files only** — if you need to reference code, paste it here or upload the file

2. **Before asking for code changes, paste the relevant code here first** — saves Claude Code tokens

3. **Use this session for planning, strategy, and small fixes** — escalate to Claude Code only when you need to edit multiple files

4. **Document decisions in WORKING_NOTES.md** — if we decide on an architectural approach, add it to the notes so Claude Code sessions can reference it

---

## **Common Commands Reference**

### **Local Development**
```bash
# Start bot locally
python bot.py

# Run a manual pipeline test
python -c "from main import run_pipeline; run_pipeline()"

# Check what's been built
ls -la src/apis/
ls -la src/engine/
ls -la src/pipelines/

# View recent commits
git log --oneline -10
```

### **Railway**
```bash
# View logs (web UI is easier)
railway logs

# Redeploy
railway up
```

### **API Testing**
```python
# Test SportsGameOdds API for MLB props
import requests
api_key = "YOUR_KEY"
response = requests.get(
    "https://api.sportsgameodds.com/v1/props",
    params={"sport": "MLB", "apiKey": api_key}
)
print(response.json()[:2])
```

---

## **When You Get Stuck**

1. **Check Railway logs first** — 90% of deployment issues show up there
2. **Paste error messages in Claude Chat** — get a diagnosis before spinning up Claude Code
3. **Verify environment variables** — missing or misnamed vars cause silent failures
4. **Check Discord Developer Portal** — bot permissions issues are common and easy to fix manually
5. **Review SESSION_HANDOFF.md** — previous sessions may have documented known issues

---

**For full technical details, architecture diagrams, and MLB-specific implementation notes, see `MLB_Parlay_Agent_Blueprint_v1.docx`.**
