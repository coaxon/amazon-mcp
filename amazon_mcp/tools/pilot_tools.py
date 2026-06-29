"""Backward-compat shim — use domain_tools.register_domain_tools."""
from amazon_mcp.tools.domain_tools import EXPORTS, register_domain_tools, register_pilot_tools

__all__ = ["EXPORTS", "register_domain_tools", "register_pilot_tools"]
