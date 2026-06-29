"""Input validation helpers for domain handlers."""
from __future__ import annotations

import re

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


def require_positive_price(price: float, field: str = "price") -> dict | None:
    if price <= 0:
        return {"ok": False, "error": f"{field} must be greater than 0 (got {price})"}
    if price > 100_000:
        return {"ok": False, "error": f"{field} value {price} is implausibly large"}
    return None


def require_valid_asin(asin: str) -> dict | None:
    if not asin:
        return {"ok": False, "error": "asin must be a non-empty string"}
    normalized = asin.strip().upper()
    if not _ASIN_RE.match(normalized):
        return {"ok": False, "error": f"Invalid ASIN format '{asin}' — must be 10 alphanumeric characters (A-Z0-9)"}
    return None
