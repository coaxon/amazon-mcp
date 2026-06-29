# AmazonMCP — Delivery Acceptance Tests

## Run automated (A + B)

```bash
cd amazon-mcp
./scripts/run_acceptance.sh
```

Or individually:

```bash
AMAZON_MCP_DRY_RUN=1 python3 tests/test_mcp_response.py      # Metric A
python3 tests/test_rate_limit_stress.py                     # Metric B
python3 scripts/verify_claude_desktop.py --check-config   # Metric C config
python3 scripts/verify_claude_desktop.py --print-config   # Claude JSON snippet
```

---

## Metric A — Contract Compliance

**Requirement:** SP-API auth path + structured JSON for Claude.

**Test:** `tests/test_mcp_response.py`

- Invokes MCP tools via `TOOL_HANDLERS`
- Wraps each response in MCP `ToolResult` shape: `{content:[{type:text,text:...}], isError:false}`
- Parses inner JSON; asserts `ok` / `service` / business fields

**Pass:** `A-RESULT: PASS (all tools, ToolResult JSON valid)`

---

## Metric B — Negative Testing (429 + Backoff)

**Requirement:** Rate limit handling with exponential backoff.

**Test:** `tests/test_rate_limit_stress.py`

- Simulates API returning 429 on global requests #2 and #3
- Runs 100 iterations through `RateLimitRegistry.call_with_backoff` (instant sleep in test)
- Asserts `throttled >= 2`, `backoff_sleeps >= 2`, `hard_failures == 0`

**Pass:** `B-RESULT: PASS (429 intercepted, exponential backoff, 100/100 survived)`

---

## Metric C — Cursor MCP E2E (primary)

**Requirement:** Agent calls tools from natural language in Cursor.

**Config:** `.cursor/mcp.json` → `amazon-sp` (project-scoped)

**Automated wire test:**

```bash
python3 scripts/verify_cursor_mcp.py
```

**Manual in Cursor chat:** ask **「列出我的库存中所有 ASIN」** → expect `list_inventory_asins` → `B0FIXTURE01`, `B0FIXTURE02`

Reload MCP after config change: Cursor Settings → MCP → enable `amazon-sp`.

---

## Metric C-alt — Claude Desktop (optional)

See `scripts/verify_claude_desktop.py --print-config`

---

## Employer demo script

> "I've built an MCP server with LWA OAuth, SP-API + Ads clients, token-bucket pacing, and 429 exponential backoff. Run `./scripts/run_acceptance.sh` for contract + stress tests; Claude Desktop validates end-to-end inventory query."
