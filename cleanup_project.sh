#!/bin/bash
# MLB Parlay Agent - Project Cleanup Script

set -e

echo "🧹 MLB Parlay Agent - Project Cleanup"
echo "======================================"

if [ ! -f "main.py" ]; then
    echo "❌ Error: Run this script from the mlb-agent project root"
    exit 1
fi

mkdir -p docs

FILES_TO_MOVE=(
    "ARCHITECTURE_DECISIONS.md"
    "BUILD_STATUS.md"
    "SESSION_HANDOFF.md"
    "WORKING_NOTES.md"
    "PROJECT_INSTRUCTIONS.md"
    "MLB_Parlay_Agent_Blueprint_v1.docx"
    "SupabaseSchemaReference"
    "SYSTEM_DIAGNOSTIC_REPORT_2026-05-12.md"
)

MOVED_COUNT=0
for file in "${FILES_TO_MOVE[@]}"; do
    if [ -f "$file" ]; then
        echo "   Moving $file"
        mv "$file" docs/
        MOVED_COUNT=$((MOVED_COUNT + 1))
    fi
done

cat > docs/README.md << 'DOCEOF'
# MLB Parlay Agent - Documentation

This directory contains reference documentation moved here to reduce Claude Code cache size.

## 📚 Project Documentation
- **MLB_Parlay_Agent_Blueprint_v1.docx** - Original system design
- **ARCHITECTURE_DECISIONS.md** - Key technical decisions
- **SupabaseSchemaReference** - Database schema

## 📋 Project Tracking
- **SESSION_HANDOFF.md** - Latest session context
- **BUILD_STATUS.md** - System health status
- **WORKING_NOTES.md** - Development notes
- **SYSTEM_DIAGNOSTIC_REPORT_2026-05-12.md** - Diagnostic report

See [../README.md](../README.md) for quick start and API docs.
DOCEOF

cat > .claudeignore << 'IGNOREEOF'
# Reduce Claude Code cache size
models/*.pkl
docs/
__pycache__/
*.pyc
.venv/
.git/
*.log
IGNOREEOF

echo ""
echo "✅ Moved $MOVED_COUNT files to /docs"
echo "💰 Expected savings: ~$35/month in Claude Code costs"
