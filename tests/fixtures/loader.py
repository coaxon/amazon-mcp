"""Load official-format Amazon API response fixtures for contract/integration tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_FIXTURES_ROOT = Path(__file__).parent


def load_fixture(*parts: str) -> dict[str, Any] | list[Any]:
    """Load a JSON fixture by path segments, e.g. load_fixture('sp_api', 'product_pricing.json')."""
    path = _FIXTURES_ROOT.joinpath(*parts)
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def fixture_path(*parts: str) -> Path:
    return _FIXTURES_ROOT.joinpath(*parts)
