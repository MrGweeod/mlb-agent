# Workflow Rules — Cost & Efficiency

**Last Updated:** May 14, 2026

---

## When to Use Claude Chat vs Claude Code vs Manual Actions

### ⚡ Use Manual Actions (You in Terminal/Web UI) When:
- Updating environment variables (Railway, Supabase)
- Checking Railway logs or deployment status
- Git operations: pull, status, commit, push
- Reading small files: `cat README.md`
- Installing packages: `pip install -r requirements.txt`
- Running pipeline locally: `python main.py`
- Supabase: Table Editor (schema), SQL Editor (queries)
- Quick file edits (< 10 lines)

### 💬 Use Claude Chat When:
- **Data analysis and diagnostics** (SQL queries, performance reviews)
- **Debugging strategy** (interpreting logs, error patterns)
- **Planning workflows** before execution
- **Reviewing pasted code** (< 100 lines)
- **Writing SQL queries, config snippets**
- **Explaining errors, suggesting fixes**
- **Cost analysis** (like this session!)

**Why:** Claude Chat is **free** for you in claude.ai, while Claude Code costs ~$0.30 per message due to caching overhead.

### 💻 Use Claude Code When:
- **Writing/editing Python files** (> 20 lines)
- **Refactoring modules, adding features**
- **Multi-file code changes**
- **Running tests, linters, formatters**
- **Building new pipelines or integrations**

**Cost awareness:** Each Claude Code session costs ~$0.20 to open (cache write) + ~$0.30 per message (cache reads). A 30-message session = ~$9.00.

---

## 💰 Cost Optimization Best Practices

### **Reduce Claude Code Cache Size:**
✅ **Keep only essential files in project root:**
- Code files (`src/`, `scripts/`, `main.py`)
- Config files (`requirements.txt`, `railway.toml`, `.env.example`)
- Essential README

✅ **Move to `/docs` directory:**
- Reference documentation (architecture, blueprints)
- Historical notes (session handoffs, working notes)
- Schema references and design docs

✅ **Use `.claudeignore`:**
```
# Exclude from Claude Code cache
models/*.pkl
docs/
__pycache__/
*.log
```

### **Decision Rule:**
1. **Can I do this manually in < 5 minutes?** → Do it yourself
2. **Can I paste code here and get a fix?** → Claude Chat (free)
3. **Need to edit multiple Python files?** → Claude Code (paid, but necessary)

---

## 🔐 Security

- **Never paste raw API keys in chat** (use placeholders)
- **Store secrets in Railway Variables only**
- **Use `.env.example` with placeholders for documentation**
- **Git ignore:** Ensure `.env` is in `.gitignore`

---

## 🔄 Git Workflow

### **Before Starting Work:**
```bash
git pull origin main
```

### **During Work:**
- Commit small, logical units
- Use descriptive messages: `"fix: correct coverage calculation for UNDER props"`
- Test locally before committing (when possible)

### **After Work:**
```bash
git add -A
git commit -m "feat: your descriptive message"
git push origin main
```

Railway will auto-deploy within ~2 minutes.

---

## 🤝 Collaboration Rules — Domain Expert + Technical Guide

### **Every New Feature or Change:**

1. **Claude asks:** What betting edge are you trying to capture?
2. **Claude proposes:** High-level plan + tradeoffs + recommendation
3. **You validate:** Approve, redirect, or reject based on betting reality
4. **Claude executes:** Small milestones with checkpoints for validation

### **Decision Authority:**

**You decide:**
- What edges to target
- What success looks like
- Betting strategy and risk tolerance
- When to bet, how much, which props

**Claude decides:**
- How to implement features technically
- What tools/libraries to use
- Code architecture and patterns
- Performance optimizations

**Shared decision:**
- When technical constraints conflict with betting goals
- When there are multiple valid approaches with different tradeoffs
- When changing core system behavior (scoring, filtering, thresholds)

---

## 🚨 Red Flags — When Claude Must Stop and Ask

Claude should **STOP and get your approval** before making these changes:

### **Architectural Changes:**
- Changing parlay construction logic (e.g., two-pool → single-pool)
- Modifying the ML model structure or training process
- Adding/removing data sources or APIs
- Changing database schema (tables, columns, types)

### **Betting Logic Changes:**
- Coverage threshold changes (affects leg quality)
- Composite score weight adjustments
- Filter changes that could reduce hit rates
- Changes to minimum/maximum parlay odds
- Same-game leg caps or correlation rules

### **Cost-Impact Changes:**
- Adding new API calls in the scheduled pipeline
- Increasing frequency of pipeline runs
- Changing LLM call frequency or prompt size

---

## ✅ Green Lights — When Claude Can Proceed

Claude can proceed **without asking first** for:

### **Bug Fixes:**
- Broken code (syntax errors, crashes)
- Wrong stat mappings
- Incorrect data transformations
- Missing error handling

### **Performance Optimizations:**
- Faster database queries
- Better caching strategies
- Reduced API calls (without changing functionality)
- Code cleanup and refactoring (no behavior changes)

### **Documentation:**
- README updates
- Code comments
- Inline documentation
- Session handoff notes

### **Infrastructure:**
- Railway configuration tweaks
- Environment variable additions (non-breaking)
- Dependency updates (minor versions)

---

## 📊 Data Analysis Workflow

When investigating system performance or debugging:

1. **Start in Claude Chat** (free)
   - Discuss the problem
   - Design diagnostic SQL queries
   - Run queries in Supabase SQL Editor
   - Paste results back to Claude Chat for analysis

2. **Only move to Claude Code when:**
   - You need to modify Python code based on findings
   - You need to create new scripts (> 20 lines)
   - You need to refactor multiple files

**Example from today:** 
- API usage analysis → all in Claude Chat (free)
- Creating cleanup script → Claude Chat generated it (free)
- If we needed to edit 5+ Python files → would use Claude Code (paid)

---

## 🎯 Current System State (May 14, 2026)

### **Active Components:**
- ✅ Pipeline: 3x daily (9 AM, 12 PM, 5:30 PM ET)
- ✅ Web app: https://mlb-agent.up.railway.app
- ✅ Database: Supabase PostgreSQL
- ✅ ML Model: leg_scorer_v2.pkl (retrained May 13)
- ✅ Coverage: Direction-aware (fixed May 13)

### **API Usage:**
- **MLB parlay agent:** ~$3.50/month (automated analysis)
- **Claude Code:** ~$107/month (development sessions)
- **Target after cleanup:** ~$30/month total

### **Known Issues:**
- Direction feature dominance in ML model (monitoring)
- Low coverage population (7%, improves as season progresses)

---

## 📝 Quick Reference Commands

### **Check Railway Logs:**
```bash
railway logs --tail 100
railway logs | grep "ERROR"
railway logs | grep "[parlay_builder]"
```

### **Manual Pipeline Trigger:**
```bash
curl -X POST https://mlb-agent.up.railway.app/api/admin/run_full_pipeline \
  -H "Authorization: Bearer MLBparlays"
```

### **Database Queries:**
```sql
-- Check today's legs
SELECT COUNT(*), AVG(composite_score) 
FROM mlb_scored_legs 
WHERE run_date = CURRENT_DATE::text;

-- Check recent parlays
SELECT * FROM mlb_parlay_recommendations_v2 
WHERE run_date >= CURRENT_DATE - 7 
ORDER BY created_at DESC;
```

### **Local Development:**
```bash
# Pull latest
git pull origin main

# Install dependencies
pip install -r requirements.txt

# Run pipeline
python main.py

# Run web server
python src/web/server.py
```

---

## 🔍 Troubleshooting

### **Pipeline Not Running:**
1. Check Railway logs: `railway logs --tail 50`
2. Check Railway dashboard for deployment status
3. Verify environment variables are set
4. Check Supabase connection health

### **API Key Errors:**
1. Check Railway environment variables
2. Ensure no secrets in code (should be in env vars only)
3. Verify API key hasn't expired (SportsGameOdds, Anthropic)

### **Database Errors:**
1. Check Supabase dashboard for connection issues
2. Verify queries use correct type casting (see SUPABASE_SCHEMA_REFERENCE.md)
3. Check for rate limiting (unlikely with current usage)

---

## 📚 Related Documentation

- **[README.md](../README.md)** - System overview and quick start
- **[/docs/SESSION_HANDOFF.md](../docs/SESSION_HANDOFF.md)** - Latest session context
- **[/docs/BUILD_STATUS.md](../docs/BUILD_STATUS.md)** - System health status
- **[/docs/ARCHITECTURE_DECISIONS.md](../docs/ARCHITECTURE_DECISIONS.md)** - Key technical decisions
- **[/docs/SUPABASE_SCHEMA_REFERENCE.md](../docs/SUPABASE_SCHEMA_REFERENCE.md)** - Database schema

---

**Remember:** Claude Chat is free, Claude Code costs ~$3-10 per session. Use Chat for planning and analysis, Code for implementation.
