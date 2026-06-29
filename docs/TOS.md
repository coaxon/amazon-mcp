# Terms of Service (Draft)

> **Status:** Draft — not reviewed by legal counsel. Do not publish externally until counsel approval.
>
> **Last updated:** 2026-06-15 · **Product:** AmazonMCP

---

## 1. Agreement

By accessing or using AmazonMCP (the "Service"), you agree to these Terms. If you do not agree, do not use the Service.

**[TODO — legal]** Governing law, dispute resolution, and entity name.

---

## 2. Service description

AmazonMCP is a Model Context Protocol (MCP) server that connects AI assistants (e.g., Claude, Cursor) to **your** Amazon Selling Partner API and Advertising API data to provide:

- Daily operational briefings and health scores
- Inventory, pricing, and advertising insights
- Proactive alerts (Slack and other channels)
- Seller-authorized workflow helpers (reports, inbound plans, COGS tracking)

The Service is offered in **beta / early access**. Features, uptime, and pricing may change without notice until general availability.

---

## 3. Eligibility

You must:

- Be an authorized user of the Amazon seller account(s) you connect.
- Hold valid SP-API developer authorization from the selling account owner.
- Comply with [Amazon SP-API Acceptable Use Policy](https://developer-docs.amazon.com/sp-api/docs/acceptable-use-policy) and Ads API terms.
- Be at least 18 years old (or age of majority in your jurisdiction).

---

## 4. Your responsibilities

| Responsibility | Detail |
|----------------|--------|
| Credentials | Provide and maintain valid LWA / refresh tokens; revoke on offboarding |
| Accuracy | COGS and custom inputs you provide are your responsibility |
| Authorized use | Do not use the Service to violate Amazon policies or scrape unauthorized data |
| API quotas | Accept Amazon rate limits; we implement backoff but cannot guarantee unlimited throughput |
| Dry-run awareness | When `dry_run=true`, outputs are fixture/sample data — not live marketplace state |

---

## 5. Our responsibilities (beta tier)

We will use commercially reasonable efforts to:

- Keep dry-run and documented live paths functional
- Protect stored credentials with encryption (Fernet v1)
- Isolate tenant data by `tenant_id` in multi-tenant deployments
- Notify beta users of material security incidents

**We do not guarantee:** 99.9% uptime, real-time data latency, profit accuracy without complete COGS, or outcomes of Amazon write operations.

---

## 6. Fees & billing (early access)

**Current state:** Usage metering (`amazon_billing` / `usage_ledger`) is **record-only**; quota enforcement and payment (e.g., Stripe) are **not active**.

**[TODO — commercial]** Pricing tiers, trial period, refund policy, and tax handling before paid GA.

Early paid pilot customers will receive a separate order form or pilot agreement superseding this section.

---

## 7. Intellectual property

- Amazon, Selling Partner API, and related marks are property of Amazon.com, Inc.
- AmazonMCP software, documentation, and composite insight logic remain property of the operator.
- You retain ownership of your seller data and COGS inputs.

You grant us a limited license to process your data solely to provide the Service.

---

## 8. Prohibited uses

You may not:

- Share MCP endpoints or API keys with unauthorized parties
- Reverse-engineer Amazon APIs beyond authorized developer access
- Use the Service for competitive intelligence on third-party sellers you do not own
- Circumvent tenant isolation or billing meters
- Resell raw Amazon API payloads without Amazon's and our written consent

---

## 9. Disclaimers

THE SERVICE IS PROVIDED **"AS IS"** WITHOUT WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, OR NON-INFRINGEMENT.

Profit snapshots, reimbursement estimates, and replenishment suggestions are **informational** — not financial, tax, or legal advice. Verify all figures in Seller Central before acting.

---

## 10. Limitation of liability

**[TODO — legal]** Cap on liability (e.g., fees paid in prior 12 months), exclusion of indirect damages, carve-outs for gross negligence.

---

## 11. Termination

Either party may terminate beta access with reasonable notice. We may suspend access immediately for:

- Amazon policy violations or API access revocation
- Non-payment (when billing is enabled)
- Security abuse or credential sharing

Upon termination: credentials should be revoked in Amazon Developer Console; we will delete tenant data per `PRIVACY_POLICY.md` retention section upon request.

---

## 12. Amazon API compliance

Use of the Service requires compliance with Amazon's developer agreements. See `docs/SP_API_COMPLIANCE_CHECKLIST.md` for operator self-audit items.

You are responsible for ensuring your connected roles and data use match your authorization scope.

---

## 13. Contact

**General / beta access:** [info@coaxon.me](mailto:info@coaxon.me?subject=AmazonMCP%20Terms)

---

*Draft aligned with AmazonMCP v2.0 (858 tests, 28 domain tools, multi-tenant quota enforcement). Not legal advice.*
