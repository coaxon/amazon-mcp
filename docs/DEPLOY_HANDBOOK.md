# Deployment handbook

> **Version:** 2026-06-28 · Generic VPS install via `scripts/install.sh` and `scripts/deploy_remote.sh`

---

## 1. Pre-deploy checks (local)

```bash
cd amazon-mcp
pip install -r requirements.txt
bash scripts/run_acceptance.sh
bash scripts/deploy_remote.sh user@your-host --dry-run | tee /tmp/amazon-mcp-rsync-dryrun.log
```

### rsync dry-run expectations

| Rule | Effect |
|------|--------|
| `--exclude 'data/'` + `--filter 'P data/'` | **整目录不同步、不覆盖** |
| `--exclude '.env'` + `--filter 'P .env'` | 服务器 `.env` SSOT，不被覆盖 |
| Sensitive paths | `data/tenants/`、`usage_ledger.db`、`.tenant_credential_key` **均不在传输列表** |

---

## 2. Deploy to a remote host

```bash
export AMAZON_MCP_DEPLOY_HOST=user@your-host   # optional default
bash scripts/deploy_remote.sh user@your-host
```

Or on the target host directly:

```bash
bash scripts/install.sh --install-dir /opt/amazon-mcp --systemd --verify
```

**Will not:** overwrite `/opt/amazon-mcp/.env` or `data/` on the remote host.

---

## 3. 生产 `.env` 必填/推荐（本轮新增高亮）

```bash
# 核心
AMAZON_MCP_DRY_RUN=0                    # live 前确认；demo 可保持 1
AMAZON_MCP_TRANSPORT=streamable-http
AMAZON_MCP_API_KEY=<strong-secret>      # 生产建议强制

# Slack — 必须使用 Block Kit 交互通道
NOTIFY_SLACK_ENABLED=1
NOTIFY_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
AMAZON_MCP_SLACK_INTERACTIVE_ENABLED=1   # =1 → 有按钮；=0 → plain attachments（已封闭/弃用）
SLACK_SIGNING_SECRET=<from Slack app>

# 图表/PDF（B-MVP）
AMAZON_MCP_PUBLIC_BASE_URL=https://YOUR_PUBLIC_HOST   # Slack 拉图/PDF 必需 HTTPS
AMAZON_BRIEFING_ASSETS_DIR=data/briefing_assets

# 多租户 / COGS / 补货默认值
AMAZON_TENANT_CREDENTIAL_KEY_PATH=data/.tenant_credential_key
AMAZON_COGS_DB_PATH=data/cogs.db
AMAZON_MCP_ALERT_DB=                      # 可选；默认 alerts_{tenant}.db
AMAZON_DEFAULT_LEAD_TIME_DAYS=14
AMAZON_DEFAULT_SAFETY_STOCK_DAYS=14

# IP allowlist + Stripe（商业化必须项）
AMAZON_MCP_IP_ALLOWLIST=127.0.0.1,<your-ip>/32   # 留空=无限制
STRIPE_WEBHOOK_SECRET=whsec_...                   # Stripe webhook 签名密钥
STRIPE_PRICE_TIER_MAP={"price_XXX":"standard"}    # Stripe price_id→tier 映射
```

完整模板：`.env.example`

---

## 4. 部署后验证

### 4.1 服务

```bash
ssh your-vps 'sudo systemctl is-active amazon-mcp && sudo journalctl -u amazon-mcp -n 20 --no-pager'
```

### 4.2 daily_briefing JSON

```bash
ssh your-vps 'cd /opt/amazon-mcp && ./venv/bin/python -c "
import asyncio, json, os
os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")
from amazon_mcp.server import run_scenario
d = json.loads(asyncio.run(run_scenario("daily_briefing", "{\"generate_assets\": true}")))
print(json.dumps({"ok": d["ok"], "assets": d.get("briefing_assets", {})}, indent=2))
"'
```

### 4.3 Slack 双消息推送验证（Block Kit 通道）

```bash
ssh your-vps 'cd /opt/amazon-mcp && ./venv/bin/python scripts/push_slack_deploy_verify.py'
```

| 消息 | 类型 | 说明 |
|------|------|------|
| **单条** | 实时 CRITICAL alert | `build_alert_blocks` + Ack/Snooze 按钮 |
| **固定 2** | daily_briefing | `B0FIXTURE01` / `B0FIXTURE02` + 图表/PDF blocks |

期望：`AMAZON_MCP_SLACK_INTERACTIVE_ENABLED=1` 且 webhook 返回 200。

### 4.4 资产 URL（Slack 拉图）

```bash
# 从 briefing 输出取 token
curl -I "https://YOUR_PUBLIC_HOST/briefing/assets/TOKEN/sales_trend.png"
```

---

## 5. 故障速查

| 现象 | 处理 |
|------|------|
| Slack 无按钮 | 设 `AMAZON_MCP_SLACK_INTERACTIVE_ENABLED=1`，重启 service |
| 图片不显示 | 检查 `AMAZON_MCP_PUBLIC_BASE_URL` 为 Slack 可达 HTTPS |
| deploy 后数据丢失 | 不应发生 — 确认 rsync 未传 `data/` |
| plain attachment 消息 | 交互未开 — 勿用简化通道 |

详见 [`RUNBOOK.md`](RUNBOOK.md)

---

## 6. your-vps 实测记录（2026-06-15）

| 项 | 结果 |
|----|------|
| deploy | ✅ `amazon-mcp.service` active |
| 单条 CRITICAL alert（Block Kit） | ✅ Slack 200 |
| 固定-2 briefing B0FIXTURE01/02 | ✅ Slack 200（localhost chart 降级为文字提示） |
| rsync | ✅ 无 `data/` / `.env` 传输 |

## 7. 签核清单

- [ ] rsync dry-run 无 `data/` / `.env`
- [ ] 858 pytest PASS（部署前）
- [ ] `systemctl is-active amazon-mcp`
- [ ] `AMAZON_MCP_API_KEY` + `AMAZON_MCP_IP_ALLOWLIST` 已配置
- [ ] Slack 单条 alert + 固定-2 briefing 各 1 条（Block Kit）
- [ ] chart/PDF URL 200（若已配置公网 BASE_URL）
- [ ] Stripe webhook 端点在 Stripe Dashboard 已注册

---

*Post-install verification: `bash scripts/verify_install.sh` · Operator runbook: [`RUNBOOK.md`](RUNBOOK.md)*
