#!/usr/bin/env bash
# Mock Slack interactive payload against local /slack/interactions
set -euo pipefail

ACTION="${1:-acknowledge}"
HOST="${AMAZON_MCP_HOST:-127.0.0.1}"
PORT="${AMAZON_MCP_PORT:-8780}"
SECRET="${SLACK_SIGNING_SECRET:-test_secret}"
TS=$(date +%s)

case "$ACTION" in
  acknowledge)
    VALUE='{"action_type":"acknowledge","item_kind":"inventory_alert","alert_id":"mock-001","asin":"B0MOCK001"}'
    ;;
  snooze_24h)
    VALUE='{"action_type":"snooze_24h","item_kind":"inventory_alert","alert_id":"mock-001","asin":"B0MOCK001"}'
    ;;
  *)
    echo "Usage: $0 [acknowledge|snooze_24h]" >&2
    exit 1
    ;;
esac

PAYLOAD=$(python3 - <<PY
import json, urllib.parse
inner = {
  "type": "block_actions",
  "user": {"username": "local_tester"},
  "response_url": "https://example.invalid/response",
  "message": {"blocks": [
    {"type": "section", "text": {"type": "mrkdwn", "text": "test"}},
    {"type": "actions", "block_id": "actions_inventory_alert_mock-001", "elements": []},
  ]},
  "actions": [{
    "action_id": "$ACTION",
    "block_id": "actions_inventory_alert_mock-001",
    "value": """$VALUE""",
  }],
}
print(urllib.parse.urlencode({"payload": json.dumps(inner)}))
PY
)

SIG=$(python3 - <<PY
import hashlib, hmac, os
secret = os.environ.get("SLACK_SIGNING_SECRET", "$SECRET")
body = """$PAYLOAD"""
ts = "$TS"
base = f"v0:{ts}:{body}"
print("v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest())
PY
)

curl -sS -X POST "http://${HOST}:${PORT}/slack/interactions" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-Slack-Request-Timestamp: ${TS}" \
  -H "X-Slack-Signature: ${SIG}" \
  --data-binary "${PAYLOAD}" \
  -w "\nHTTP %{http_code}\n"
