# Amazon 开发者凭证可获取数据 — SP-API / Ads API 全景与 AmazonMCP 对照

> 文档版本: 2026-06-27 | 官方: developer-docs.amazon.com/sp-api | 对照: sp_api.py, ads_api.py, domain_tools.py (28 domain tools)

---

## 1. 凭证体系

| 凭证 | 用途 | 环境变量 |
|------|------|----------|
| LWA OAuth | SP-API token | AMAZON_LWA_* |
| SP-API Role | 卖家授权 Orders/Inventory/Finance | refresh_token |
| Ads OAuth | 广告 API | AMAZON_ADS_* |

约束: 未授权 Role 403; Brand Analytics 需 Brand Registry; COGS 本地 B8 (`cogs/store.py`).

---

## 2. SP-API vs AmazonMCP 状态

已用: Catalog, Data Kiosk, FBA Inventory, Finances v0 + v2024, Inbound v2024, Orders v0, Product Fees/Pricing, Reports(20+: incl. IPI/RESTOCK/Brand Analytics x6), Seller Feedback, Sellers, Notifications(subscribe+unsubscribe: ANY_OFFER_CHANGED, FBA_INVENTORY_AVAILABILITY, LISTINGS_STATUS, LISTINGS_ISSUES, PRICING_HEALTH), Listings Items CRUD.

未用: MFN/Shipping/MCF, A+ Content, AWD, Wallet, Messaging, Solicitations, Tokens, Uploads.

---

## 3. 已接入 REST 端点

catalog, pricing, fees, fba/inventory, orders, finances, reports, inbound, dataKiosk, seller-feedback, sellers, notifications.

Reports: SALES_AND_TRAFFIC, FBA_INVENTORY, LISTINGS, ORDERS, SETTLEMENT, RETURNS, FBA_FEES, STRANDED, SUPPRESSED, BRAND_ANALYTICS x4.

Ads: profiles, campaigns, keywords, reporting v3 (spCampaigns/Keywords/SearchTerm/AdvertisedProduct/Targeting, sb/sd).

复合: daily_briefing, operations_health, replenishment, profit_snapshot, alerts.

---

## 4. 未使用高价值数据

✅ P0.6 GET_FBA_REIMBURSEMENTS_DATA — `sp_api.py` + `scenarios/fba_reimbursement.py`.

✅ RESTOCK — `amazon_inventory("restock_recommendations")` GET_RESTOCK_INVENTORY_RECOMMENDATIONS_REPORT.
✅ IPI — `amazon_inventory("ipi_score")` GET_FBA_INVENTORY_PLANNING_DATA.
✅ Notifications (5种) — `amazon_account("subscribe_*")` ANY_OFFER_CHANGED / FBA_INVENTORY_AVAILABILITY / LISTINGS_STATUS / LISTINGS_ISSUES / PRICING_HEALTH.
✅ Finances v2024 — `amazon_finance("transaction_list" / "fee_breakdown")`.
✅ Brand Analytics x6 — `amazon_report(action="brand_analytics", report_type=...)`.
✅ Listings Items CRUD — `amazon_listings("update_price" / "update_quantity" / ...)`.
✅ Ads Pause Campaign — `amazon_ads("pause_campaign")`.

未接: ORDER_CHANGE Notification, STORAGE_FEE_CHARGES, A+ Content, Ads Purchased Product.

---

## 5. Amazon 不提供

COGS, 完整买家PII(需RDT), A9算法, 竞品卖家身份.

---

## 6. 覆盖率

REST ~35%, Reports ~14%, Notifications ~3%, Ads ~40%. 产品聚焦非全量封装.

---

## 7. 接入顺序

1 ✅FBA_REIMB 2 ✅COGS 3 SELLER_PERF(P1) 4 Notifications(P1) 5 Brand 6 Fin v2024 7 Listings+Ads

---

## 8. 最小 Role

Product Listing + Inventory/Orders + Finance + Fulfillment + Advertising + (opt) Brand Analytics.

---

## 9. 链接

- developer-docs.amazon.com/llms.txt
- sp-api/docs/sp-api-models
- sp-api/docs/report-type-values
- sp-api/docs/notification-type-values
- docs/composite_insights_roadmap.md

---

## 附录 A: 官方 Reports 分类（Seller，节选）

来源: developer-docs.amazon.com/sp-api/docs/report-type-values

| 分类 | 代表 reportType | AmazonMCP |
|------|-----------------|-----------|
| Analytics | GET_SALES_AND_TRAFFIC_REPORT, GET_BRAND_ANALYTICS_* | 部分已用 |
| FBA Inventory | GET_FBA_MYI_*, GET_RESTOCK_*, GET_STRANDED_* | 部分已用 |
| FBA Payment | GET_FBA_REIMBURSEMENTS_DATA ✅, GET_FBA_STORAGE_FEE_* | 报销已接 |
| FBA Customer | GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA | 已映射 returns |
| Inventory/Listings | GET_MERCHANT_LISTINGS_*, GET_MERCHANTS_LISTINGS_FYP | 部分已用 |
| Order | GET_FLAT_FILE_ALL_ORDERS_* | 已映射 orders |
| Payment/Settlement | GET_V2_SETTLEMENT_* | 已映射 settlement |
| Performance | GET_V2_SELLER_PERFORMANCE (P1), GET_SELLER_FEEDBACK | 部分 |
| Returns | GET_FLAT_FILE_RETURNS_* | 未用 |
| Tax/VAT/GST | 各区域税务报告 | 未用 |

---

## 附录 B: MCP Domain Tool 到 SP-API 完整映射（28 domain tools 中 SP/Ads 相关）

| Domain Tool | Action(s) | 底层 API |
|-------------|-----------|----------|
| `amazon_health` | — | 本地状态 |
| `amazon_catalog` | `lookup` · `bulk_lookup` · `search` · `listing_quality` | Catalog Items 2022-04-01 |
| `amazon_pricing` | `product_pricing` · `competitive_offers` · `fee_estimate` · `profit_analysis` | Product Pricing v0 / Product Fees v0 |
| `amazon_inventory` | `levels` · `list_asins` · `health` · `stranded` · `suppressed` | FBA Inventory v1 + Reports |
| `amazon_inventory` | `reorder_calculator` · `aging_inventory` · `fnsku_reorder` | 本地计算（基于 FBA Inventory 数据） |
| `amazon_inventory` | `restock_recommendations` | Reports GET_RESTOCK_INVENTORY_RECOMMENDATIONS_REPORT |
| `amazon_inventory` | `ipi_score` | Reports GET_FBA_INVENTORY_PLANNING_DATA |
| `amazon_orders` | `list` · `order_details` · `next_page` · `revenue_summary` · `sales_by_asin` | Orders v0 + Reports SALES_AND_TRAFFIC |
| `amazon_finance` | `financial_summary` | Finances v0 financialEvents |
| `amazon_finance` | `transaction_list` · `fee_breakdown` | Finances v2024 |
| `amazon_finance` | `import_cogs` · `get_cogs` | SQLite COGS (`cogs/store.py`) |
| `amazon_report` | `create` · `status` · `download` | Reports 2021-06-30 |
| `amazon_report` | `brand_analytics` (6 types) | Reports BRAND_ANALYTICS |
| `amazon_fulfillment` | `create_inbound_plan` · `get_inbound_plan` · `operation_status` | Inbound 2024-03-20 |
| `amazon_fulfillment` | `reimbursement_summary` | Reports GET_FBA_REIMBURSEMENTS_DATA |
| `amazon_analytics` | `sales_traffic` · `kiosk_status` · `custom_kiosk_query` | Data Kiosk 2023-11-15 |
| `amazon_account` | `feedback` | Seller Feedback v1 |
| `amazon_account` | `subscribe_*` · `unsubscribe` · `subscription_status` | Notifications v1 (5 event types) |
| `amazon_system` | `marketplaces` | Sellers v1 |
| `amazon_ads` | `profile` · `campaign_list` · `keyword_performance` | Ads API v2 |
| `amazon_ads` | `sponsored_metrics` · `campaign_performance` · `search_term_performance` · `product_ad_performance` | Ads Reporting v3 |
| `amazon_ads` | `pause_campaign` | Ads API v2 (write, live only) |
| `amazon_listings` | `get_listing` · `update_price` · `update_quantity` · `deactivate_listing` · `activate_listing` · `delete_listing` | Listings Items v2021-08-01 (write, confirm gate) |
| `amazon_alerts` | `configure_inventory` · `add_price_watch` · `pending_alerts` · `dismiss` | 本地 alerts.db + SP 轮询 |
| `amazon_insights` | `operations_health` · `inventory_last` · `protect_margin` · `competitor_price_alert` | 复合层（多 API 融合） |
| `amazon_meli` · `amazon_tiktok` · `amazon_cross_platform` | 各域 actions | 美客多 API v2 · TikTok Shop API |
| `amazon_rto_geo` | `returns_geo_cluster` · `rto_region_alert` 等 | Reports RETURNS（本地聚合） |
| `amazon_command_center` · `amazon_inventory_pool` · `amazon_sync_schedule` | write + confirm gate | 美客多 / TikTok（跨平台写，confirm gate） |
| `amazon_benchmark` | `get_percentile` · `full_benchmark_report` 等 | 本地匿名分位数分布 |

---

## 附录 C: 凭证能获取的数据 — 按卖家业务域

| 业务域 | 官方可获取 | AmazonMCP 覆盖 |
|--------|------------|----------------|
| 销售/流量 | Orders, Sales API, SALES_AND_TRAFFIC Report, Data Kiosk | 高 |
| 库存/FBA | FBA Inventory + Reports | 中（报销已接；缺 IPI/仓储费） |
| 定价/竞品 | Product Pricing, ANY_OFFER_CHANGED 通知 | 高（通知未订阅） |
| 广告 | Ads Reporting v3, Campaign CRUD | 中（缺写操作/归因） |
| 财务/利润 | Finances v0/v2024, Settlement | 中（B8 COGS 本地；v2024 未接） |
| 账户健康 | Seller Performance Report, Feedback, Account Status 通知 | 低 |
| Listing 质量 | Listings Items, Suppressed/Defect Reports | 低 |
| 品牌分析 | Brand Analytics Reports (需 Registry) | 中（缺 2 种） |
| 买家沟通 | Messaging, Solicitations | 无 |
| 税务合规 | VAT/GST/EPR Reports | 无 |

## Shopify (GAP-CONN-01)

| 能力 | 端点 | 环境变量 |
|------|------|----------|
| Shop health | `GET /admin/api/{version}/shop.json` | `SHOPIFY_SHOP`, `SHOPIFY_ACCESS_TOKEN` |
| List products | `GET /admin/api/{version}/products.json` | 同上 |
| dry_run | fixtures | `SHOPIFY_DRY_RUN=1` (default) |

详见 `03_Perception/connectors/README.md`。
## Klaviyo (GAP-CONN-02)

| 能力 | 端点 | 环境变量 |
|------|------|----------|
| Account health | `GET /api/accounts/` | `KLAVIYO_API_KEY` |
| List campaigns | `GET /api/campaigns/` | 同上 + `KLAVIYO_API_REVISION` |
| dry_run | fixtures | `KLAVIYO_DRY_RUN=1` (default) |

详见 `03_Perception/connectors/README.md`。

