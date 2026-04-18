# Workflow Rules — Cost & Efficiency

## When to Use Claude Chat vs Claude Code vs Manual Actions

### Use Manual Actions (You in Terminal/Web UI) When:
- Updating environment variables (Railway, Discord, Supabase)
- Checking Railway logs or deployment status
- Git operations: pull, status, commit, push
- Reading small files: `cat README.md`
- Installing packages: `pip install -r requirements.txt`
- Running bot locally: `python bot.py`
- Supabase: Table Editor (schema), SQL Editor (queries)
- Discord Developer Portal: bot setup, tokens, invite URLs

### Use Claude Chat When:
- Debugging strategy, interpreting logs
- Reviewing pasted code (< 100 lines)
- Writing SQL queries, config snippets
- Explaining errors, suggesting fixes
- Planning workflows before execution

### Use Claude Code When:
- Writing/editing Python files (> 20 lines)
- Refactoring modules, adding features
- Running tests, linters, formatters
- Debugging across multiple files
- Building new pipelines or integrations

## Decision Rule
1. Can I do this manually in < 5 minutes? → Do it yourself
2. Can I paste code here and get a fix? → Claude Chat
3. Need to edit multiple Python files? → Claude Code

## Security
- Never paste raw API keys in chat
- Store secrets in Railway Variables only
- Use `.env.example` with placeholders

## Git Workflow
- `git pull` before starting work
- Commit small units: "Fix pitcher handedness logic"
- `git push` after every session
