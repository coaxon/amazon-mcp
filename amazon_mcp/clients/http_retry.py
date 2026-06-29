from __future__ import annotations

import httpx

from amazon_mcp.clients.rate_limit import RateLimitError


def raise_on_429(resp: httpx.Response) -> None:
    if resp.status_code == 429:
        retry_after = float(resp.headers.get("Retry-After", "1") or 1)
        raise RateLimitError(f"HTTP 429 Too Many Requests", retry_after=retry_after)
    resp.raise_for_status()
