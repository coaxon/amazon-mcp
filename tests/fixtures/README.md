# AmazonMCP API Fixtures

Official-format JSON samples for contract tests. Field names and nesting match Amazon SP-API / Ads API documentation.

| Fixture | API | Doc reference |
|---|---|---|
| `sp_api/product_pricing.json` | Product Pricing v0 `getPricing` | `payload[].Product.Offers[].BuyingPrice` |
| `sp_api/competitive_pricing_offers.json` | Product Pricing v0 `getItemOffers` | `payload.Summary`, `payload.Offers[]` |
| `sp_api/inventory_summaries.json` | FBA Inventory v1 `getInventorySummaries` | `payload.inventorySummaries[]` |
| `sp_api/financial_events.json` | Finances v0 `listFinancialEvents` | `payload.FinancialEvents.ShipmentEventList[]` |
| `sp_api/catalog_item.json` | Catalog Items 2022-04-01 `getCatalogItem` | `summaries[]`, `classifications[]`, `salesRanks[]` |
| `sp_api/orders_list.json` | Orders v0 `getOrders` | `payload.Orders[]` |
| `sp_api/fees_estimate.json` | Product Fees v0 `getMyFeesEstimateForASIN` | `payload.FeesEstimateResult.FeesEstimate` |
| `ads_api/campaign_performance_report.json` | Ads Reporting v3 SP campaign report rows | `campaignId`, `acosClicks7d`, `sales7d` |
| `ads_api/sponsored_ads_summary.json` | Ads Profiles v2 | `accountInfo`, `currencyCode` |

Use `from tests.fixtures.loader import load_fixture` in tests.
