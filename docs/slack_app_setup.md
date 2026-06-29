# Slack App Setup — Interactive Briefing (B13/B14)

AmazonMCP uses **two HTTP paths** on the same Starlette app (streamable-http, default port **8780**):

| Path | Caller | Purpose |
|------|--------|---------|
| `/mcp` | Cursor / MCP clients | MCP streamable-http protocol |
| `/slack/interactions` | Slack servers | Block Kit button callbacks |

No separate HTTP process is required — routes are registered via FastMCP `@mcp.custom_route()`.

## Slack App configuration (admin UI)

### 1. Interactivity & Shortcuts

- **Request URL:** `https://<your-public-host>/slack/interactions`
- **your-vps (Tailscale only):** replace with a **public URL** when deploying (e.g. reverse proxy, ngrok for local dev).
  - Placeholder: `https://YOUR_PUBLIC_HOST/slack/interactions`
  - Tailscale IP `100.x.x.x:8780` is **not** reachable by Slack — plan pubic ingress separately (do not bind your-vps :443 per infra constraint).

### 2. OAuth & Permissions (for interactive messages + updates)

Minimum scopes (Bot Token Scopes):

- `chat:write` — post/update messages via `response_url` follow-ups

> **Note:** Outbound daily briefing today may still use an **Incoming Webhook**. Interactive Block Kit buttons require the app to have Interactivity enabled; message updates use the `response_url` from the interaction payload.

### 3. Signing Secret

- **Location:** Slack App → *Basic Information* → *App Credentials* → **Signing Secret**
- Set in `.env`:

```bash
SLACK_SIGNING_SECRET=your_signing_secret
AMAZON_MCP_SLACK_INTERACTIVE_ENABLED=1   # 0 = legacy attachment-only webhook
```

### 4. Environment summary

| Variable | Default | Description |
|----------|---------|-------------|
| `SLACK_SIGNING_SECRET` | (empty) | HMAC verification for `/slack/interactions` |
| `AMAZON_MCP_SLACK_INTERACTIVE_ENABLED` | `0` | Send Block Kit briefing + action buttons |
| `NOTIFY_SLACK_WEBHOOK_URL` | — | Outbound webhook (existing) |
| `NOTIFY_SLACK_CHANNEL` | `#amazon-alerts` | Optional channel hint |

## Local curl test (mock Slack)

```bash
export SLACK_SIGNING_SECRET=test_secret
export AMAZON_MCP_TRANSPORT=streamable-http
export AMAZON_MCP_HOST=127.0.0.1
export AMAZON_MCP_PORT=8780

# Terminal 1 — start server
python -m amazon_mcp

# Terminal 2 — signed POST (see scripts/mock_slack_interaction.sh)
bash scripts/mock_slack_interaction.sh acknowledge
```

## Buttons (MVP)

| Button | Action | Effect |
|--------|--------|--------|
| **Acknowledge** | `acknowledge` | `dismiss_alert(alert_id)` or hide low-score item |
| **Snooze 24h** | `snooze_24h` | Set `snoozed_until` (+24h); AlertEngine skips re-push |

No Amazon account write operations in this phase.

---

**Support / beta access:** [info@coaxon.me](mailto:info@coaxon.me?subject=Amazon%20Seller%20Intelligence%20Demo%20Request)

## your-vps production checklist (Pause Ad / Acknowledge buttons)

Slack **cannot** call private LAN / Tailscale IPs (e.g. `100.x.x.x:8780`). Use a **public HTTPS** host that forwards to your MCP server:

| Setting | Value |
|---------|-------|
| **Interactivity Request URL** | `https://your-domain.example/slack/interactions` |
| **your-vps `.env` key** | `SLACK_SIGNING_SECRET=<from Slack App → Basic Information → App Credentials>` |

### Get `SLACK_SIGNING_SECRET`

1. Open [api.slack.com/apps](https://api.slack.com/apps) → select **your Amazon MCP app** (the same app that owns the Incoming Webhook).
2. Left sidebar → **Basic Information**.
3. Under **App Credentials** → **Signing Secret** → **Show** → copy value.
4. On your-vps: `ssh your-vps` → `nano /opt/amazon-mcp/.env` → add line:
   ```
   SLACK_SIGNING_SECRET=paste_secret_here
   ```
5. Restart: `sudo systemctl restart amazon-mcp`
6. Smoke test (401 without secret → 200 with invalid payload but valid sig):
   ```bash
   cd /opt/amazon-mcp && ./venv/bin/python scripts/run_pause_ad_slack_flow.py
   ```

### Configure Interactivity URL (Slack admin UI)

1. Same app → **Interactivity & Shortcuts** → toggle **On**.
2. **Request URL:** `https://your-domain.example/slack/interactions`
3. Save Changes. Slack sends a verification POST; server must return 200 (requires service running + reachable URL).

> **Rationale text (daily briefing)** uses `section` + `"expand": false` — Slack client **See more** only; **no** `/slack/interactions` call. Only write-action buttons (Pause Ad, Acknowledge, Preview Inbound) need the signing secret.

