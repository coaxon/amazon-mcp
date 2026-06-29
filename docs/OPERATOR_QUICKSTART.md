# Amazon MCP — 运营快速参考

> 受众：自托管运维 · 场景：在自有 VPS 上配置 LWA 凭证并接入 MCP 客户端

---

## 服务器现状（示例）

| 项 | 值 |
|----|-----|
| 主机 | `your-vps`（自建 VPS / 云主机） |
| MCP 端点 | `http://127.0.0.1:8780/mcp`（本机）或 `https://your-domain.example/mcp`（公网反代） |
| 服务 | `amazon-mcp.service`（systemd，自启） |
| 代码路径 | `/opt/amazon-mcp/` |
| 当前模式 | `AMAZON_MCP_DRY_RUN=1`（演示固定数据） |

**查 API Key**（首次或忘记时）：

```bash
ssh your-vps "grep AMAZON_MCP_API_KEY /opt/amazon-mcp/.env"
```

---

## 快速接入（有 SP-API 凭证）

### 第一步：准备 LWA 三件套

```
AMAZON_LWA_CLIENT_ID       — Developer Console → App → LWA client ID
AMAZON_LWA_CLIENT_SECRET   — 同上，client secret
AMAZON_LWA_REFRESH_TOKEN   — Seller Central → 授权你的 app → 复制 refresh token
```

可选（更完整功能）：

```
AMAZON_SELLER_ID           — Seller Central → Account Info → Merchant Token
AMAZON_MARKETPLACE_ID      — US=ATVPDKIKX0DER / EU/JP 按需
AMAZON_ADS_CLIENT_ID       — Ads API（广告功能需要）
AMAZON_ADS_REFRESH_TOKEN   — 同上
AMAZON_ADS_PROFILE_ID      — GET /v2/profiles 返回的 ID
```

### 第二步：写入服务器 .env

```bash
ssh your-vps
sudo nano /opt/amazon-mcp/.env
# 修改以下项：
# AMAZON_LWA_CLIENT_ID=<你的值>
# AMAZON_LWA_CLIENT_SECRET=<你的值>
# AMAZON_LWA_REFRESH_TOKEN=<你的值>
# AMAZON_MCP_DRY_RUN=0          ← 切换实盘
```

### 第三步：重启

```bash
sudo systemctl restart amazon-mcp
sudo systemctl is-active amazon-mcp   # 期望: active
```

### 第四步：验证

```bash
# 健康检查（替换 <KEY> 为实际 API Key）
curl -s http://127.0.0.1:8780/health \
  -H "Authorization: Bearer <KEY>"

# Cursor / Claude MCP URL:
# http://127.0.0.1:8780/mcp
# Header: Authorization: Bearer <KEY>
```

---

## 演示模式（无需凭证）

服务器默认 `AMAZON_MCP_DRY_RUN=1`，所有 core 工具返回 fixture 数据。

```bash
amazon_health()
amazon_inventory(action="list_asins")
amazon_catalog(action="lookup", asin="B0POC00001")
```

> `run_scenario("daily_briefing")` 等场景编排属于 **Pro** 包；core-only 安装会返回 `pro_required`。

---

## 切回演示模式

```bash
ssh your-vps
sudo sed -i 's/^AMAZON_MCP_DRY_RUN=0/AMAZON_MCP_DRY_RUN=1/' /opt/amazon-mcp/.env
sudo systemctl restart amazon-mcp
```

---

## SP-API 凭证申请指引

1. 登录 [developer.amazon.com](https://developer.amazon.com/apps-and-games/console) → **SP-API** → 注册应用
2. 应用类型选 **Private Seller App**，角色勾选只读权限（按需）
3. 生成 LWA 凭证：App → **LWA credentials** → 复制 Client ID + Secret
4. 授权：Seller Central → **Apps & Services** → Authorize your app → 复制 Refresh Token

---

## 常用运维命令

```bash
ssh your-vps "sudo journalctl -u amazon-mcp -n 30 --no-pager"
ssh your-vps "sudo systemctl restart amazon-mcp"
ssh your-vps "grep -E '^(AMAZON_MCP_DRY_RUN|AMAZON_MCP_TRANSPORT|AMAZON_MCP_PORT)' /opt/amazon-mcp/.env"

# 本地重新部署（代码更新后）
bash scripts/deploy_remote.sh user@your-vps
```

---

*Last updated: 2026-06-28 · 示例端点: localhost:8780*
