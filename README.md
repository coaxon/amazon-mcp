# amazon-mcp

<p align="center">
  <img src="docs/images/coaxon_command_center_demo.png" alt="Claude Code Demo - CoAxon Command Center" width="100%"/>
</p>

MCP server for Amazon Selling Partner API (SP-API) and Advertising API — exposes orders, inventory, pricing, ads, reports, and related read paths to Claude, Cursor, and other MCP clients.

## Quick Start

```bash
git clone https://github.com/coaxon/amazon-mcp.git
cd amazon-mcp
cp .env.example .env
python run_mcp.sh
```

🔒 0 violations across 6 projects — CodeQL audited. [View Report](docs/security-audit.md)

This connects **your own** Seller Central and Ads API data — an operations tool for sellers who already run a store, not a market or product-research tool. If you want category research, keyword mining, or competitor intel on products you do not yet sell, look elsewhere.

**Audience:** developers who already use MCP. You are expected to read tool docstrings, configure LWA credentials yourself, and run the server locally or on your own host.

---

## 30-second start

```bash
git clone https://github.com/coaxon/amazon-mcp.git
cd amazon-mcp
pip install -r requirements.txt
cp .env.example .env            # defaults: dry-run, no credentials
python -m amazon_mcp            # stdio → Claude Desktop / Cursor
```

**Planned (not on PyPI yet):** `pip install amazon-mcp` · `uvx amazon-mcp`

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "amazon-sp": {
      "command": "python3",
      "args": ["-m", "amazon_mcp"],
      "cwd": "/path/to/amazon-mcp",
      "env": {
        "AMAZON_MCP_DRY_RUN": "1",
        "AMAZON_MCP_DATA_DIR": "/path/to/amazon-mcp/data"
      }
    }
  }
}
```

**HTTP transport** (Cursor / remote client). Set `AMAZON_MCP_API_KEY` in server `.env` first.

```bash
AMAZON_MCP_TRANSPORT=streamable-http AMAZON_MCP_HOST=127.0.0.1 AMAZON_MCP_PORT=8780 python -m amazon_mcp
```

```json
{
  "mcpServers": {
    "amazon-sp": {
      "url": "http://127.0.0.1:8780/mcp",
      "headers": {
        "Authorization": "Bearer ${AMAZON_MCP_API_KEY}"
      }
    }
  }
}
```

See [`claude_desktop_config.example.json`](claude_desktop_config.example.json).

---

## Dry-run (no credentials)

Default `AMAZON_MCP_DRY_RUN=1` serves bundled fixtures — no LWA app, no Seller Central auth. **Defaulted to DRY_RUN=1 to keep your seller account safe while testing the logic.**

```bash
cp .env.example .env
python -m amazon_mcp
```

In your MCP client, call:

```
amazon_health()
amazon_inventory(action="list_asins")
amazon_catalog(action="lookup", asin="B0POC00001")
amazon_orders(action="revenue_summary")
amazon_alerts(action="alert_config")
```

Fixture ASINs include `B0POC00001`, `B0FIXTURE01`, etc. Responses include `"dry_run": true` in metadata.

---

## Live SP-API

Set in `.env`:

| Variable | Source |
|----------|--------|
| `AMAZON_LWA_CLIENT_ID` | [Developer Console](https://developer.amazon.com) → your SP-API app → LWA credentials |
| `AMAZON_LWA_CLIENT_SECRET` | same |
| `AMAZON_LWA_REFRESH_TOKEN` | Seller Central → authorize app → refresh token |
| `AMAZON_SELLER_ID` | optional but recommended (Merchant Token) |
| `AMAZON_MCP_DRY_RUN` | set to `0` |

Step-by-step credential setup: [docs/OPERATOR_QUICKSTART.md](docs/OPERATOR_QUICKSTART.md) (§ SP-API 客户凭证申请指引).

---

## Core tools (open source)

Domain tools follow `amazon_<domain>(action="...")`. Core includes:

| Domain | Actions (summary) |
|--------|-------------------|
| `system` | `health`, `auth_token`, `metrics`, `marketplaces` |
| `account` | seller feedback, SP-API notification subscriptions |
| `catalog` | `lookup`, `bulk_lookup`, `search`, `listing_quality`, `competitor_insights` |
| `pricing` | `product_pricing`, `competitive_offers`, `fee_estimate`, `profit_analysis` |
| `orders` | `revenue_summary`, `list`, `order_details`, `sales_by_asin` |
| `inventory` | `levels`, `list_asins`, `health`, `stranded`, `suppressed` |
| `listings` | read/update listing fields (preview gate on writes) |
| `report` | `create`, `status`, `download`, `brand_analytics` |
| `ads` | profiles, campaigns, keyword/search-term performance |
| `finance` | `financial_summary`, COGS import/read |
| `fulfillment` | FBA inbound plan create/read, operation status |
| `analytics` | sales & traffic, Data Kiosk queries |
| `alerts` | **read only:** `pending_alerts`, `alert_config` |

Also in core: `run_dag_plan` / `resume_dag_plan` — three-phase SP-API executor (`amazon_mcp/dag/`); no Pro dependency.

---

## Core vs Pro

Pro is a separate optional package (`amazon-mcp-pro`). Core detects it via `importlib.util.find_spec("amazon_mcp_pro")`. No license keys.

**Without Pro**, these return `{"error": "pro_required", ...}` (see [Getting Pro](#getting-pro) for how to enable Pro today):

| Category | Gated |
|----------|-------|
| **Entire domains** | `insights`, `notify`, `billing`, `features`, `admin`, `meli`, `tiktok`, `cross_platform`, `rto_geo`, `command_center`, `benchmark`, `inventory_pool`, `sync_schedule` |
| **`alerts` writes** | `configure_inventory`, `add_price_watch`, `dismiss`, `manual_check` |
| **`inventory` advanced** | `reorder_calculator`, `restock_recommendations`, `ipi_score`, `aging_inventory`, `fnsku_reorder` |
| **`fulfillment`** | `reimbursement_summary` |
| **Scenarios** | `run_scenario(...)`, `amazon_daily()` — e.g. `daily_briefing`, `profit_protection` |

Pro adds: multi-tenant gateway, AlertEngine polling, Slack/Stripe integrations, scenario orchestration, cross-platform connectors. There is no self-serve install path yet — see [Getting Pro](#getting-pro) below.

### Getting Pro

Pro is not yet published as a standalone package. There is no PyPI release (public or private), so `pip install amazon-mcp-pro` will fail. Current options:

- **Private deployment** — we set up and host the full stack (multi-tenant gateway, AlertEngine, Slack/Stripe integrations, scenario orchestration) on your infrastructure or ours.
- **Questions / business inquiries** — open a [GitHub Issue](https://github.com/coaxon/amazon-mcp/issues) or email [info@coaxon.me](mailto:info@coaxon.me).

---

## Environment reference

Full template: [`.env.example`](.env.example).

| Variable | Notes |
|----------|-------|
| `AMAZON_MCP_DRY_RUN` | `1` (default) = fixtures; `0` = live API |
| `AMAZON_MCP_DATA_DIR` | SQLite / tenant data (required when installed via pip into site-packages) |
| `AMAZON_MCP_TRANSPORT` | `stdio` \| `streamable-http` \| `sse` |
| `AMAZON_MCP_API_KEY` | Bearer auth for HTTP `/mcp` endpoint |

---

## Deploy

Generic VPS install:

```bash
bash scripts/install.sh --install-dir /opt/amazon-mcp --systemd
bash scripts/verify_install.sh
```

Details: [docs/DEPLOY_HANDBOOK.md](docs/DEPLOY_HANDBOOK.md), [docs/RUNBOOK.md](docs/RUNBOOK.md).

---

## Development

```bash
AMAZON_MCP_DRY_RUN=1 python -m amazon_mcp
AMAZON_MCP_FORCE_CORE=1 python -m amazon_mcp   # simulate core-only in monorepo
```

Tests are being updated for the core/pro split; not required for trying dry-run locally.

---

## License

[MIT](LICENSE)
