# AmazonMCP Operations Runbook

> **Audience:** Operators / on-call · **Last updated:** 2026-06-15
>
> **Quick health:** `AMAZON_MCP_DRY_RUN=1 python -m amazon_mcp` (stdio) or `curl -s http://127.0.0.1:8780/health` (if HTTP health exposed)

---

## 1. Service topology

| Component | Path / env | Notes |
|-----------|------------|-------|
| MCP server | `python -m amazon_mcp` | stdio (Cursor/Claude) or `AMAZON_MCP_TRANSPORT=streamable-http` |
| Tenant registry | `data/tenants.json` | Fernet-encrypted credentials |
| Credential key | `data/.tenant_credential_key` | `AMAZON_TENANT_CREDENTIAL_KEY_PATH` override |
| Usage ledger | `data/usage_ledger.db` | Background thread writes; failures are non-blocking |
| Per-tenant DBs | `data/tenants/{id}/alerts.db`, `cogs.db` | Created on first use |
| systemd unit | `scripts/amazon-mcp.service` | Production on your-vps VPS |
| Deploy | `scripts/deploy_remote.sh` | rsync + remote `install.sh`; does **not** overwrite remote `.env` |

**CI / local test env:**
```bash
export AMAZON_MCP_DRY_RUN=1
export NOTIFY_SLACK_ENABLED=0 NOTIFY_DISCORD_ENABLED=0 NOTIFY_WEBHOOK_ENABLED=0 NOTIFY_EMAIL_ENABLED=0
unset AMAZON_MCP_API_KEY
export AMAZON_COGS_DB_PATH="$(mktemp -t amazon_mcp_cogs.XXXXXX.db)"
pytest tests/ -q && bash scripts/run_acceptance.sh
```

---

## 2. Credential expiry / 401 Unauthorized

### Symptoms
- Tools return `"error": "401"` or LWA refresh failures
- `get_auth_token_status` shows expired or missing token
- Logs: `SP-API error ... Unauthorized`

### Diagnosis
```bash
# Check token cache (if CoAxon co-deployed)
ls -la Shared_Memory/.runtime/lwa_token_*.json 2>/dev/null

# Verify env / tenant record
python3 -c "from amazon_mcp.gateway.tenant import TenantRegistry; print(TenantRegistry().get('default'))"
```

### Resolution
1. Confirm `AMAZON_LWA_CLIENT_ID`, `AMAZON_LWA_CLIENT_SECRET`, `AMAZON_LWA_REFRESH_TOKEN` in `.env` or tenant record.
2. Re-authorize app in Seller Central → Developer Console → regenerate refresh token.
3. For multi-tenant: update specific `tenant_id` in `data/tenants.json` (use `scripts/migrate_tenant_credentials.py` after edit).
4. Delete stale token cache files; restart service.
5. If `AMAZON_MCP_DRY_RUN=0`, verify credentials are **not** placeholders (`config.py` placeholder detection).

### Prevention
- Proactive refresh triggers when TTL < 5 minutes (`get_auth_token_status`).
- Monitor 401 rate in logs; alert if > 3 in 10 minutes.

---

## 3. HTTP 429 Rate limiting

### Symptoms
- Intermittent tool failures with 429 / `QuotaExceeded`
- Slow responses during bulk operations (`amazon_catalog(action="bulk_lookup")`, report polling)

### Diagnosis
- Review logs for `429` and backoff retries
- Run stress test: `python tests/test_rate_limit_stress.py`
- Check per-tenant `rate_limit_rps` in tenant registry (default 5)

### Resolution
1. **Wait** — client implements exponential backoff (acceptance B validates this).
2. Reduce concurrent tool calls from MCP client.
3. Increase cache TTL: `AMAZON_CACHE_TTL=600`.
4. For sustained load: lower tenant `rate_limit_rps` or shard sellers across instances.
5. If Amazon developer account suspended: stop live calls, set `AMAZON_MCP_DRY_RUN=1`, contact Amazon Developer Support.

---

## 4. Tenant resolution failure

### Symptoms
- `"error": "Unknown tenant"` or `KeyError` on `tenant_id`
- Wrong seller data returned (cross-tenant — **critical**)

### Diagnosis
```bash
python3 -c "
from amazon_mcp.gateway.router import GatewayRouter
from amazon_mcp.gateway.tenant import TenantRegistry
r = TenantRegistry()
print('tenants:', list(r.list_ids()))
print(GatewayRouter(r).resolve('YOUR_TENANT_ID'))
"
```

### Resolution
1. Verify `tenant_id` parameter matches registry entry (case-sensitive after strip).
2. Add tenant via registry API / edit `data/tenants.json` + run credential migration.
3. Ensure `_ensure_default_tenant()` ran at startup (check `amazon_health` for default tenant).
4. **Cross-tenant suspicion:** immediately set `AMAZON_MCP_DRY_RUN=1`, rotate `AMAZON_MCP_API_KEY`, audit `usage_ledger.db` for wrong `tenant_id` on calls.

---

## 5. usage_ledger write failure

### Symptoms
- Log warnings from billing background thread
- `amazon_billing` → `usage_summary` missing recent events
- SQLite errors on `data/usage_ledger.db`

### Diagnosis
```bash
ls -la data/usage_ledger.db
sqlite3 data/usage_ledger.db "SELECT COUNT(*), MAX(ts) FROM usage_events;"
python3 -c "from amazon_mcp.gateway.billing import get_usage_ledger; print(get_usage_ledger().summary('default'))"
```

### Resolution
1. Check disk space and directory permissions on `data/`.
2. If DB corrupt: stop service → `mv data/usage_ledger.db data/usage_ledger.db.bak` → restart (creates fresh DB).
3. Usage recording is **non-blocking** — core MCP tools still work if ledger fails.
4. Reconcile billing manually from application logs if needed (pilot phase).

---

## 6. Dry-run vs live confusion

### Symptoms
- Customer sees fixture ASINs (`B0FIXTURE01`) in production
- `dry_run: true` in all responses but customer expects live data

### Resolution
1. Check `AMAZON_MCP_DRY_RUN` env (must be `0` for live).
2. Check tenant-level `dry_run` flag in registry.
3. Communicate clearly in UI/Slack — all outputs should expose `dry_run` field.
4. See [OPERATOR_QUICKSTART.md](OPERATOR_QUICKSTART.md) for credential setup.

---

## 7. MCP HTTP unauthorized (401 on /mcp)

### Symptoms
- Cursor/remote client cannot connect to streamable-http endpoint
- `{"error": "Unauthorized"}`

### Resolution
1. Set `AMAZON_MCP_API_KEY` on server.
2. Client must send `Authorization: Bearer <same key>`.
3. For local dev without auth: **unset** `AMAZON_MCP_API_KEY` (middleware skipped).
4. Rotate key if leaked; update Cursor MCP config.

---

## 8. Slack / notification failures

### Symptoms
- Alerts not delivered; `test_notification_channel` fails

### Diagnosis
- Verify `NOTIFY_SLACK_ENABLED=1` and webhook URL (redacted in logs via `redact_webhook_url`)
- Check Slack signing secret for inbound interactions (B17)

### Resolution
1. Disable broken channel: `NOTIFY_SLACK_ENABLED=0` (other channels unaffected).
2. Re-create webhook in Slack app settings.
3. Map Slack `user_id` → `tenant_id` for confirm actions (see B17 docs).

---

## 9. Deploy / sync drift

### Symptoms
- Remote install differs from local git tree

### Resolution
1. Run `bash scripts/deploy_remote.sh user@your-host --dry-run` from a clean git tree.
2. Deploy: `bash scripts/deploy_remote.sh user@your-host` (or `bash scripts/install.sh` on the host).
3. **Never** overwrite production `.env` manually via deploy script.
4. Compare versions: `amazon_health` → check server responds with expected tool count.

---

## 10. Tenant lifecycle (offboarding)

1. Revoke SP-API authorization in Seller Central for the app.
2. Remove tenant from `data/tenants.json` (or delete file entry).
3. Delete `data/tenants/{tenant_id}/` directory (alerts + COGS).
4. Purge usage ledger rows: `DELETE FROM usage_events WHERE tenant_id = ?` (optional).
5. Rotate `AMAZON_MCP_API_KEY` if shared endpoint was used.
6. Document completion in pilot customer record.

---

## 11. Escalation

| Severity | Action |
|----------|--------|
| P1 — cross-tenant leak, credential exposure | `AMAZON_MCP_DRY_RUN=1`, rotate keys, notify customers within 24h |
| P2 — full service down | Restart systemd; check VPS disk/memory |
| P3 — single tool failure | File issue; dry-run repro via `AMAZON_MCP_DRY_RUN=1 pytest tests/ -q` |

**Contact:** [info@coaxon.me](mailto:info@coaxon.me?subject=AmazonMCP%20Incident)

---

## 12. Useful commands

```bash
# Full test gate (matches CI)
bash scripts/run_acceptance.sh

# Contract only
python tests/test_mcp_response.py

# Credential encryption migration (dry-run)
python scripts/migrate_tenant_credentials.py --dry-run

# Billing summary
python -c "import asyncio; from amazon_mcp.tools.billing import usage_summary; print(asyncio.run(usage_summary()))"
```
