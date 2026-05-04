#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/report.log"

echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Starting email report" >> "$LOG_FILE"

/opt/node22/bin/claude \
  --model claude-sonnet-4-6 \
  --print \
  "$(cat "$SCRIPT_DIR/prompt.txt")" \
  >> "$LOG_FILE" 2>&1

echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Email report complete" >> "$LOG_FILE"
