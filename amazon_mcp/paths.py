"""Runtime path resolution — works from source tree or pip site-packages."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def package_root() -> Path:
    """Directory containing the amazon_mcp package."""
    return _PKG_ROOT


@lru_cache(maxsize=1)
def project_root() -> Path:
    """Repo/install root (parent of amazon_mcp package). Used for legacy layouts."""
    explicit = os.environ.get("AMAZON_MCP_PROJECT_ROOT", "").strip()
    if explicit:
        return Path(explicit).resolve()
    return _PKG_ROOT.parent


@lru_cache(maxsize=1)
def data_dir() -> Path:
    """Writable data directory (SQLite, tenant files, caches)."""
    raw = os.environ.get("AMAZON_MCP_DATA_DIR", "").strip()
    if raw:
        p = Path(raw)
    else:
        p = project_root() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()


@lru_cache(maxsize=1)
def fixtures_dir() -> Path:
    """Bundled dry-run SP-API / Ads fixtures (shipped inside the package)."""
    return package_root() / "fixtures"


def data_path(*parts: str) -> Path:
    p = data_dir().joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def fixture_path(*parts: str) -> Path:
    return fixtures_dir().joinpath(*parts)
