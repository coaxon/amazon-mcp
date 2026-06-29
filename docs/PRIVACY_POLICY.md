# Privacy Policy (Draft)

> **Status:** Draft — not reviewed by legal counsel. Do not publish externally until counsel approval.
>
> **Last updated:** 2026-06-15 · **Product:** AmazonMCP (Amazon Seller Intelligence MCP Server)

---

## 1. Who we are

AmazonMCP is operated by the project maintainer (contact: [info@coaxon.me](mailto:info@coaxon.me)). This draft describes how we handle data when you use our MCP server, Slack integrations, or hosted SaaS instances.

**[TODO — legal]** Registered legal entity name, jurisdiction, and DPO contact.

---

## 2. What Amazon data we collect

We access **your authorized Amazon seller data** via Login with Amazon (LWA) and SP-API / Advertising API. We do **not** scrape Seller Central. Data categories include:

| Category | Examples | Source |
|----------|----------|--------|
| Catalog & listings | ASIN, title, brand, BSR, listing quality | SP-API Catalog |
| Inventory | FBA quantities, stranded/suppressed listings | FBA Inventory + Reports |
| Orders & sales | Order IDs, status, units, revenue aggregates | Orders API / Reports |
| Pricing & fees | Buy Box price, competitive offers, FBA/referral fees | Pricing, Product Fees |
| Finance | Settlement events, reimbursement summaries | Finances v0, Reports |
| Advertising | Campaigns, keywords, ACoS/ROAS, search terms | Amazon Ads API |
| Account health | Seller feedback, performance metrics (where authorized) | Reports / Feedback API |
| Notifications | Subscription metadata (not buyer PII by default) | SP-API Notifications |

**We do not collect:** buyer names, full shipping addresses, or payment card data unless explicitly authorized via Restricted Data Token (RDT) flows — **currently not implemented**.

**Locally entered data:** Cost of Goods Sold (COGS) via CSV import is **seller-provided**, not from Amazon.

---

## 3. How we use data

- Generate operational insights (daily briefing, health scores, alerts, profit snapshots).
- Execute seller-authorized actions (e.g., inbound plan preview/confirm in dry-run or live mode).
- Meter tool usage for billing readiness (`usage_ledger` — dry-run quota enforcement not yet active).
- Improve product reliability (aggregated, non-PII logs).

We **do not** sell Amazon seller data to third parties.

---

## 4. Storage & encryption

| Data type | Location | Protection |
|-----------|----------|------------|
| LWA / Ads credentials | `data/tenants.json` (per-tenant registry) | Fernet encryption (`enc:v1:` prefix); key at `data/.tenant_credential_key` or `AMAZON_TENANT_CREDENTIAL_KEY_PATH` |
| COGS | `data/cogs.db` or per-tenant `data/tenants/{id}/cogs.db` | File-system permissions; not encrypted at rest (Phase B: optional SQLCipher) |
| Alerts | `data/alerts.db` or per-tenant path | SQLite; tenant-scoped paths |
| Usage ledger | `data/usage_ledger.db` | SQLite; tenant_id + tool name + timestamp |
| LWA access tokens | Runtime cache (`Shared_Memory/.runtime/lwa_token_*.json` when CoAxon co-deployed) | Ephemeral; auto-refresh |

**Production recommendation (not yet default):** AWS KMS / GCP KMS via `KmsEncryptorStub` placeholder; secrets manager for master key; encrypted volumes at rest.

---

## 5. Tenant data isolation

- Each tenant has a unique `tenant_id`. Tool calls accept optional `tenant_id` (default `"default"`).
- `GatewayRouter` resolves SP-API and Ads clients per tenant from `TenantRegistry`.
- Per-tenant SQLite: `data/tenants/{tenant_id}/alerts.db`, `cogs.db`.
- Credential records are encrypted independently per tenant row.
- **Gap:** Single-process deployment shares one OS user; true isolation requires per-tenant VPC/namespace (future).

---

## 6. Third-party sharing

| Third party | Purpose | Data shared |
|-------------|---------|-------------|
| Amazon (SP-API / Ads API) | Core product | Authorized seller API payloads only |
| Slack (optional) | Alert delivery & interactive ack | Alert summaries, ASINs, configured webhook URLs |
| Discord / Email / Generic webhook (optional) | Notification channels | Same as Slack — user-configured |
| Hosting provider (e.g., VPS) | Infrastructure | Encrypted-at-rest disk per provider policy |

**No** analytics trackers, ad networks, or data brokers in the current codebase.

**[TODO — legal]** Sub-processor list (hosting, email, payment when Stripe added).

---

## 7. Retention & deletion

| Data | Default retention | Deletion |
|------|-------------------|----------|
| API credentials | Until tenant offboarded | Remove tenant from registry + rotate keys |
| COGS / alerts SQLite | Until deleted by operator | Delete tenant DB files |
| Usage ledger | Indefinite (billing audit) | **[TODO]** Define retention policy (e.g., 24 months) |
| Logs | Server log rotation (systemd) | Operator-managed |

Tenant offboarding procedure: **[TODO — ops]** documented in `RUNBOOK.md` § Tenant lifecycle.

---

## 8. Your rights

Depending on jurisdiction (GDPR, CCPA, etc.), you may have rights to access, correct, export, or delete personal data.

**[TODO — legal]** Formal request process, response SLA, and applicable jurisdictions.

Seller-provided COGS and alert configs are deletable on request by removing tenant data files.

---

## 9. Security measures

- Optional Bearer auth for HTTP MCP (`AMAZON_MCP_API_KEY`) on `/mcp` endpoint.
- Slack inbound signature verification (when enabled).
- Dry-run default (`AMAZON_MCP_DRY_RUN=1`) prevents accidental live API calls in dev/CI.
- Rate limiting / 429 exponential backoff to protect Amazon API quotas.

See `docs/RUNBOOK.md` for incident response.

---

## 10. Changes & contact

We will update this draft before any public SaaS launch. Material changes will be notified to active beta users.

**Privacy questions:** [info@coaxon.me](mailto:info@coaxon.me?subject=AmazonMCP%20Privacy)

---

*This document is a technical draft aligned with the current AmazonMCP codebase (28 domain tools, multi-tenant routing v1, Stripe quota enforcement). It is not legal advice.*
