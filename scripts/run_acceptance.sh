#!/usr/bin/env bash
# Run all three AmazonMCP acceptance checks (A + B automated; C manual checklist)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${AMAZON_MCP_PYTHON:-${COAXON_VENV:-}/bin/python3}"
if [[ -z "$PY" || ! -x "$PY" ]]; then PY="$(command -v python3)"; fi
[[ -x "$PY" ]] || PY="$(command -v python3)"
export AMAZON_MCP_DRY_RUN=1
export NOTIFY_SLACK_ENABLED=0
export NOTIFY_DISCORD_ENABLED=0
export NOTIFY_WEBHOOK_ENABLED=0
export NOTIFY_EMAIL_ENABLED=0
unset AMAZON_MCP_API_KEY
COGS_DB="$(mktemp -t amazon_mcp_cogs.XXXXXX.db)"
export AMAZON_COGS_DB_PATH="$COGS_DB"
cd "$ROOT"

echo "[acceptance] A — contract compliance"
"$PY" tests/test_mcp_response.py

echo "[acceptance] B — 429 backoff stress"
"$PY" tests/test_rate_limit_stress.py

echo "[acceptance] C — Cursor MCP (amazon-sp)"
"$PY" scripts/verify_cursor_mcp.py

echo "[acceptance] ALL automated checks PASS"
