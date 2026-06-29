import os
import re
import sqlite3
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from pathlib import Path

from amazon_mcp.paths import data_dir as mcp_data_dir
from .thresholds import InventoryThreshold, PriceWatch, AlertRecord

logger = logging.getLogger(__name__)


def get_default_alert_db_path() -> str:
    """Return tenant-scoped alert DB path based on AMAZON_SELLER_ID env var.

    Matches the routing logic in server._get_store() so notifier.py and
    server.py always point at the same file for a given seller configuration.
    """
    explicit = os.environ.get("AMAZON_MCP_ALERT_DB", "")
    if explicit:
        return explicit
    raw = os.environ.get("AMAZON_SELLER_ID", "").strip()
    if not raw or "PLACEHOLDER" in raw.upper() or "XXXXX" in raw:
        tenant_id = "default"
    else:
        tenant_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw)
    base_dir = mcp_data_dir()
    return str(base_dir / f"alerts_{tenant_id}.db")

class AlertStore:
    """SQLite-backed store for alert configurations and active alerts."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(mcp_data_dir() / "alerts.db")
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        """Initialize the database tables if they do not exist."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS inventory_thresholds (
                    sku TEXT PRIMARY KEY,
                    asin TEXT,
                    min_qty INTEGER,
                    enabled BOOLEAN,
                    created_at TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS price_watches (
                    asin TEXT PRIMARY KEY,
                    baseline_price REAL,
                    alert_pct REAL,
                    direction TEXT,
                    enabled BOOLEAN,
                    created_at TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    alert_type TEXT,
                    severity TEXT,
                    title TEXT,
                    detail TEXT,
                    asin TEXT,
                    sku TEXT,
                    data TEXT,
                    dismissed BOOLEAN,
                    created_at TEXT,
                    snoozed_until TEXT,
                slack_notified_at TEXT DEFAULT ''
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS replenishment_config (
                    asin TEXT PRIMARY KEY,
                    lead_time_days INTEGER NOT NULL,
                    updated_at TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS briefing_snoozes (
                    item_key TEXT PRIMARY KEY,
                    snoozed_until TEXT,
                    acknowledged INTEGER DEFAULT 0,
                    updated_at TEXT
                )
            """)
            self._ensure_column(conn, "alerts", "snoozed_until", "TEXT")
            self._ensure_column(conn, "alerts", "slack_notified_at", "TEXT DEFAULT ''")
            self._ensure_column(conn, "replenishment_config", "safety_stock_days", "INTEGER")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_pending ON alerts (dismissed, snoozed_until, created_at)"
            )
            conn.commit()

    def _ensure_column(self, conn, table: str, column: str, col_type: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not any(r[1] == column for r in rows):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    def upsert_inventory_threshold(self, threshold: InventoryThreshold):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO inventory_thresholds (sku, asin, min_qty, enabled, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (threshold.sku, threshold.asin, threshold.min_qty, threshold.enabled, threshold.created_at))

    def list_inventory_thresholds(self) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM inventory_thresholds WHERE enabled = 1").fetchall()
            return [dict(row) for row in rows]

    def upsert_price_watch(self, watch: PriceWatch):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO price_watches (asin, baseline_price, alert_pct, direction, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (watch.asin, watch.baseline_price, watch.alert_pct, watch.direction, watch.enabled, watch.created_at))

    def list_price_watches(self) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM price_watches WHERE enabled = 1").fetchall()
            return [dict(row) for row in rows]

    def add_alert(self, alert: AlertRecord):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO alerts (alert_id, alert_type, severity, title, detail, asin, sku, data, dismissed, created_at, snoozed_until, slack_notified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alert.alert_id, alert.alert_type, alert.severity, alert.title, alert.detail,
                alert.asin, alert.sku, json.dumps(alert.data), alert.dismissed, alert.created_at,
                getattr(alert, "snoozed_until", None),
                getattr(alert, "slack_notified_at", "") or "",
            ))

    def mark_slack_notified(self, alert_id: str, notified_at: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE alerts SET slack_notified_at=? WHERE alert_id=?",
                (notified_at, alert_id),
            )

    def get_pending_alerts(self, limit: int = 100) -> List[dict]:
        with self._get_conn() as conn:
            now = datetime.now(timezone.utc).isoformat()
            rows = conn.execute(
                """
                SELECT * FROM alerts
                WHERE dismissed = 0
                  AND (snoozed_until IS NULL OR snoozed_until <= ?)
                ORDER BY created_at DESC LIMIT ?
                """,
                (now, limit),
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                if isinstance(d.get("data"), str):
                    try:
                        d["data"] = json.loads(d["data"])
                    except (json.JSONDecodeError, TypeError):
                        d["data"] = {}
                result.append(d)
            return result

    def count_pending(self) -> int:
        with self._get_conn() as conn:
            now = datetime.now(timezone.utc).isoformat()
            return conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE dismissed = 0 AND (snoozed_until IS NULL OR snoozed_until <= ?)",
                (now,),
            ).fetchone()[0]

    def dismiss_alert(self, alert_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute("UPDATE alerts SET dismissed = 1 WHERE alert_id = ?", (alert_id,))
            return cursor.rowcount > 0

    def dismiss_all(self) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute("UPDATE alerts SET dismissed = 1 WHERE dismissed = 0")
            return cursor.rowcount

    def _iso_after_hours(self, hours: float) -> str:
        return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()

    def snooze_alert(self, alert_id: str, hours: float = 24.0) -> bool:
        until = self._iso_after_hours(hours)
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE alerts SET snoozed_until = ? WHERE alert_id = ? AND dismissed = 0",
                (until, alert_id),
            )
            return cursor.rowcount > 0

    def is_subject_snoozed(self, alert_type: str, sku: str = "", asin: str = "") -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM alerts
                WHERE dismissed = 0 AND alert_type = ?
                  AND snoozed_until IS NOT NULL AND snoozed_until > ?
                  AND (
                    (? != '' AND sku = ?) OR (? != '' AND asin = ?)
                  )
                LIMIT 1
                """,
                (alert_type, now, sku, sku, asin, asin),
            ).fetchone()
            return row is not None

    def has_active_alert(self, alert_type: str, sku: str = "", asin: str = "") -> bool:
        """Return True if an active (non-dismissed, non-snoozed) alert exists for this subject."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM alerts
                WHERE dismissed = 0
                  AND alert_type = ?
                  AND (snoozed_until IS NULL OR snoozed_until <= ?)
                  AND (
                    (? != '' AND sku = ?) OR (? != '' AND asin = ?)
                  )
                LIMIT 1
                """,
                (alert_type, now, sku, sku, asin, asin),
            ).fetchone()
            return row is not None

    def snooze_briefing_item(self, item_key: str, hours: float = 24.0) -> bool:
        until = self._iso_after_hours(hours)
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO briefing_snoozes (item_key, snoozed_until, acknowledged, updated_at)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(item_key) DO UPDATE SET
                    snoozed_until = excluded.snoozed_until,
                    acknowledged = 0,
                    updated_at = excluded.updated_at
                """,
                (item_key, until, now),
            )
            return True

    def acknowledge_briefing_item(self, item_key: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO briefing_snoozes (item_key, snoozed_until, acknowledged, updated_at)
                VALUES (?, NULL, 1, ?)
                ON CONFLICT(item_key) DO UPDATE SET
                    acknowledged = 1,
                    updated_at = excluded.updated_at
                """,
                (item_key, now),
            )
            return True

    def is_briefing_item_hidden(self, item_key: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT snoozed_until, acknowledged FROM briefing_snoozes WHERE item_key = ?",
                (item_key,),
            ).fetchone()
            if not row:
                return False
            if row[1]:
                return True
            return bool(row[0] and row[0] > now)

    def get_replenishment_lead_time(self, asin: str) -> int | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT lead_time_days FROM replenishment_config WHERE asin = ?",
                (asin.upper(),),
            ).fetchone()
            return int(row[0]) if row else None

    def set_replenishment_lead_time(self, asin: str, lead_time_days: int, safety_stock_days: int | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            if safety_stock_days is not None:
                conn.execute(
                    """
                    INSERT INTO replenishment_config (asin, lead_time_days, safety_stock_days, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(asin) DO UPDATE SET
                        lead_time_days = excluded.lead_time_days,
                        safety_stock_days = excluded.safety_stock_days,
                        updated_at = excluded.updated_at
                    """,
                    (asin.upper(), lead_time_days, safety_stock_days, now),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO replenishment_config (asin, lead_time_days, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(asin) DO UPDATE SET lead_time_days = excluded.lead_time_days, updated_at = excluded.updated_at
                    """,
                    (asin.upper(), lead_time_days, now),
                )

    def get_replenishment_safety_stock(self, asin: str) -> int | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT safety_stock_days FROM replenishment_config WHERE asin = ?",
                (asin.upper(),),
            ).fetchone()
            if not row or row[0] is None:
                return None
            return int(row[0])

