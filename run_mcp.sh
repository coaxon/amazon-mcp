#!/usr/bin/env bash
# Amazon MCP — stdio server for Claude Desktop / Cursor MCP
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${AMAZON_MCP_PYTHON:-${COAXON_VENV:-}/bin/python3}"
if [[ -z "$PY" || ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
export AMAZON_MCP_DRY_RUN="${AMAZON_MCP_DRY_RUN:-1}"
export AMAZON_MCP_DATA_DIR="${AMAZON_MCP_DATA_DIR:-$ROOT/data}"
cd "$ROOT"
exec "$PY" -m amazon_mcp "$@"
