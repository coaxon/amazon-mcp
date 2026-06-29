"""SQLite store for ASIN → COGS mappings."""
from __future__ import annotations

import csv
import io
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from amazon_mcp.paths import data_path


def get_default_cogs_db_path() -> str:
    explicit = os.environ.get("AMAZON_COGS_DB_PATH", "").strip()
    if explicit:
        p = Path(explicit)
        return str(p if p.is_absolute() else data_path(p.name))
    return str(data_path("cogs.db"))


class CogsStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or get_default_cogs_db_path()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cogs (
                    asin TEXT PRIMARY KEY,
                    cogs REAL NOT NULL,
                    sku TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cogs_sku ON cogs(sku)")

    def upsert(self, asin: str, cogs: float, *, sku: str = "") -> None:
        asin = asin.strip().upper()
        if not asin:
            raise ValueError("asin is required")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cogs (asin, cogs, sku, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(asin) DO UPDATE SET
                    cogs=excluded.cogs,
                    sku=CASE WHEN excluded.sku != '' THEN excluded.sku ELSE cogs.sku END,
                    updated_at=excluded.updated_at
                """,
                (asin, float(cogs), sku.strip(), now),
            )

    def get(self, asin: str) -> float | None:
        asin = asin.strip().upper()
        if not asin:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT cogs FROM cogs WHERE asin = ?", (asin,)).fetchone()
            if row:
                return float(row["cogs"])
            row = conn.execute("SELECT cogs FROM cogs WHERE sku = ?", (asin,)).fetchone()
            return float(row["cogs"]) if row else None

    def get_for_asins(self, asins: list[str], sku_map: dict[str, str] | None = None) -> dict[str, float]:
        """Return COGS keyed by ASIN for briefing/profit snapshot."""
        sku_map = sku_map or {}
        out: dict[str, float] = {}
        for asin in asins:
            key = asin.strip().upper()
            val = self.get(key)
            if val is None:
                sku = sku_map.get(key, "")
                if sku:
                    val = self.get(sku)
            if val is not None:
                out[key] = val
        return out

    def list_all(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT asin, cogs, sku, updated_at FROM cogs ORDER BY asin"
            ).fetchall()
        return [dict(r) for r in rows]

    def import_csv(self, csv_content: str) -> dict[str, Any]:
        reader = csv.DictReader(io.StringIO(csv_content.strip()))
        if not reader.fieldnames:
            return {"ok": False, "error": "CSV header row required (asin,cogs or sku,cogs)"}
        imported = 0
        errors: list[str] = []
        for i, row in enumerate(reader, start=2):
            asin = (row.get("asin") or row.get("ASIN") or "").strip().upper()
            sku = (row.get("sku") or row.get("SKU") or "").strip()
            raw_cogs = row.get("cogs") or row.get("COGS") or row.get("cost")
            try:
                cogs = float(raw_cogs)
            except (TypeError, ValueError):
                errors.append(f"line {i}: invalid cogs {raw_cogs!r}")
                continue
            if not asin and not sku:
                errors.append(f"line {i}: missing asin/sku")
                continue
            if not asin:
                asin = sku.upper()
            try:
                self.upsert(asin, cogs, sku=sku)
                imported += 1
            except ValueError as exc:
                errors.append(f"line {i}: {exc}")
        return {
            "ok": True,
            "imported": imported,
            "errors": errors,
            "total_rows": imported + len(errors),
        }
