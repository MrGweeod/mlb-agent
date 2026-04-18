# Workflow Rules — Cost & Efficiency

## When to Use Claude Chat vs Claude Code vs Manual Actions

### Use Manual Actions (You in Terminal/Web UI) When:
- Updating environment variables (Railway, Discord Developer Portal)
- Creating Discord bot applications, copying tokens/IDs
- Checking Railway logs
- Git operations: `git pull`, `git status`, `git log`
- Reading small files: `cat README.md`, `cat .env.example`
- Installing Python packages locally: `pip install -r requirements.txt`
- Running the bot locally for testing: `python bot.py`
- Supabase: checking table schemas, running manual SQL queries
- GitHub: creating repos, setting up branches, reviewing PRs

### Use Claude Chat (This Session) When:
- Architecture decisions, debugging strategy, interpreting logs
- Reviewing pasted code snippets (< 100 lines)
- Writing SQL queries, environment variable templates
- Explaining errors or suggesting fixes
- Planning multi-step workflows before execution

### Use Claude Code When:
- Writing or editing Python files (> 20 lines of changes)
- Refactoring modules, adding new features
- Running tests, linters, or formatters across the codebase
- Debugging errors that require reading multiple files
- Building new pipelines or data models

## Token & Rate Limit Guidelines

### Always Prefer:
1. **Reading existing code by pasting it here** vs asking Claude Code to `view` it (saves compute)
2. **Manual git commands** vs asking Claude Code to commit/push
3. **Railway web UI** for checking logs vs asking Claude Code to fetch them
4. **Discord Developer Portal** for token resets vs asking Claude Code to interact with Discord API
5. **Supabase web UI** for schema changes vs asking Claude Code to run migrations

### Before Starting Any Claude Code Session:
- [ ] Is this task something you can do manually in < 5 minutes? (If yes, do it yourself)
- [ ] Does this require reading/editing code? (If no, don't use Claude Code)
- [ ] Can you paste the relevant code here and get the fix in chat? (If yes, do that first)

### API Key & Token Hygiene:
- Never paste raw API keys or tokens in chat or Claude Code sessions
- Use placeholders: `ANTHROPIC_API_KEY=your_key_here`
- Store all secrets in Railway Variables, never in `.env` files committed to GitHub
- Use `.env.example` as a template with placeholder values only

## GitHub Workflow
- Always pull before starting work: `git pull origin main`
- Commit small, logical units: "Fix Discord permissions scope" not "Updates"
- Push after every working session: `git push origin main`
- Use branches only for experimental features, not for daily work

## Railway Workflow
- Check logs before asking for help: Railway → Deployments → View Logs
- Redeploy after environment variable changes: Railway → Deployments → Redeploy
- Monitor build times — if builds take > 3 minutes, investigate caching issues

## Supabase Workflow
- Use Table Editor for schema inspection (web UI, no code)
- Use SQL Editor for complex queries or bulk updates
- Export table data as CSV for local analysis before writing code to process it
