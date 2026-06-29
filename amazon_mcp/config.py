from __future__ import annotations

import os
from dataclasses import dataclass

_PLACEHOLDER_MARKERS = ("PLACEHOLDER", "XXXXX", "YOUR_", "EXAMPLE", "DUMMY")


def _is_placeholder(val: str) -> bool:
    up = val.upper()
    return any(m in up for m in _PLACEHOLDER_MARKERS)


@dataclass(frozen=True)
class AmazonConfig:
    # SP-API / LWA credentials
    lwa_client_id: str
    lwa_client_secret: str
    lwa_refresh_token: str
    sp_region: str
    marketplace_id: str
    seller_id: str

    # Advertising API credentials
    ads_client_id: str
    ads_client_secret: str
    ads_refresh_token: str
    ads_profile_id: str

    # Operational flags
    dry_run: bool
    cache_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "AmazonConfig":
        return cls(
            lwa_client_id=os.environ.get("AMAZON_LWA_CLIENT_ID", ""),
            lwa_client_secret=os.environ.get("AMAZON_LWA_CLIENT_SECRET", ""),
            lwa_refresh_token=os.environ.get("AMAZON_LWA_REFRESH_TOKEN", ""),
            sp_region=os.environ.get("AMAZON_SP_API_REGION", "na"),
            marketplace_id=os.environ.get("AMAZON_MARKETPLACE_ID", "ATVPDKIKX0DER"),
            seller_id=os.environ.get("AMAZON_SELLER_ID", ""),
            ads_client_id=os.environ.get("AMAZON_ADS_CLIENT_ID", ""),
            ads_client_secret=os.environ.get("AMAZON_ADS_CLIENT_SECRET", ""),
            ads_refresh_token=os.environ.get("AMAZON_ADS_REFRESH_TOKEN", ""),
            ads_profile_id=os.environ.get("AMAZON_ADS_PROFILE_ID", ""),
            dry_run=os.environ.get("AMAZON_MCP_DRY_RUN", "1") == "1",
            cache_ttl_seconds=int(os.environ.get("AMAZON_CACHE_TTL", "300")),
        )

    @property
    def sp_configured(self) -> bool:
        return bool(self.lwa_client_id and self.lwa_client_secret and self.lwa_refresh_token)

    @property
    def ads_configured(self) -> bool:
        return bool(self.ads_client_id and self.ads_refresh_token)

    @property
    def has_placeholder_credentials(self) -> bool:
        """True if any SP-API credential looks like a demo placeholder."""
        return any(
            _is_placeholder(v)
            for v in (self.lwa_client_id, self.lwa_client_secret, self.lwa_refresh_token, self.seller_id)
            if v
        )

    def validate_live(self) -> list[str]:
        """Return list of missing/invalid env vars when not in dry_run mode."""
        if self.dry_run:
            return []
        missing: list[str] = []
        checks = {
            "AMAZON_LWA_CLIENT_ID": self.lwa_client_id,
            "AMAZON_LWA_CLIENT_SECRET": self.lwa_client_secret,
            "AMAZON_LWA_REFRESH_TOKEN": self.lwa_refresh_token,
            "AMAZON_SELLER_ID": self.seller_id,
            "AMAZON_MARKETPLACE_ID": self.marketplace_id,
        }
        for env_var, val in checks.items():
            if not val:
                missing.append(env_var)
            elif _is_placeholder(val):
                missing.append(f"{env_var} (placeholder value — set a real credential)")
        return missing
