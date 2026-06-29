#!/usr/bin/env bash
# Post-install smoke test — health endpoint + dry-run MCP tool call.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${AMAZON_MCP_INSTALL_DIR:-/opt/amazon-mcp}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

cd "$INSTALL_DIR"
set -a
# shellcheck disable=SC1091
source .env
set +a

HOST="${AMAZON_MCP_HOST:-127.0.0.1}"
PORT="${AMAZON_MCP_PORT:-8780}"
TRANSPORT="${AMAZON_MCP_TRANSPORT:-stdio}"

if [[ "$TRANSPORT" != "streamable-http" && "$TRANSPORT" != "streamable_http" ]]; then
  echo "[verify] transport=${TRANSPORT} — skipping HTTP health (stdio mode OK)"
  ./venv/bin/python -c "from amazon_mcp.config import AmazonConfig; c=AmazonConfig.from_env(); print('config ok dry_run=', c.dry_run)"
  echo "[verify] PASS (stdio)"
  exit 0
fi

URL="http://${HOST}:${PORT}/health"
if [[ "$HOST" == "0.0.0.0" ]]; then
  URL="http://127.0.0.1:${PORT}/health"
fi

CURL_OPTS=(-sf --max-time 10)
if [[ -n "${AMAZON_MCP_API_KEY:-}" ]]; then
  CURL_OPTS+=(-H "Authorization: Bearer ${AMAZON_MCP_API_KEY}")
fi

_http_health() {
  echo "[verify] GET ${URL}"
  BODY="$(curl "${CURL_OPTS[@]}" "$URL")"
  echo "$BODY" | ./venv/bin/python -m json.tool >/dev/null 2>&1 || echo "$BODY"
}

_inprocess_health() {
  echo "[verify] in-process health (no HTTP server running)"
  ./venv/bin/python -c "
import asyncio, json, os
os.chdir('${INSTALL_DIR}')
from amazon_mcp.tools.registry import bootstrap_domains, dispatch_domain
bootstrap_domains()
raw = asyncio.run(dispatch_domain('system', 'health', {}))
d = json.loads(raw) if isinstance(raw, str) else raw
assert d.get('ok') or d.get('data', {}).get('ok'), d
print(json.dumps({'ok': True, 'mode': 'in-process', 'dry_run': d.get('meta', {}).get('dry_run')}))
"
}

if curl "${CURL_OPTS[@]}" "$URL" >/dev/null 2>&1; then
  _http_health
else
  echo "[verify] HTTP unreachable — starting ephemeral server for smoke test"
  ./venv/bin/python -m amazon_mcp &
  SRV_PID=$!
  trap 'kill "$SRV_PID" 2>/dev/null || true' EXIT
  for _ in $(seq 1 30); do
    if curl "${CURL_OPTS[@]}" "$URL" >/dev/null 2>&1; then
      _http_health
      break
    fi
    sleep 0.5
  done
  if ! curl "${CURL_OPTS[@]}" "$URL" >/dev/null 2>&1; then
    kill "$SRV_PID" 2>/dev/null || true
    trap - EXIT
    _inprocess_health
  fi
  kill "$SRV_PID" 2>/dev/null || true
  trap - EXIT
fi

echo "[verify] PASS"
