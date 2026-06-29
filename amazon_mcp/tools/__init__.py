"""Domain tool registry — gradual migration from monolithic server.py."""
from amazon_mcp.tools.registry import (
    DOMAIN_HANDLERS,
    LEGACY_TOOL_ALIASES,
    bootstrap_domains,
    dispatch_domain,
    dispatch_legacy,
    list_domain_actions,
    list_domains,
)

__all__ = [
    "DOMAIN_HANDLERS",
    "LEGACY_TOOL_ALIASES",
    "bootstrap_domains",
    "dispatch_domain",
    "dispatch_legacy",
    "list_domain_actions",
    "list_domains",
]
