#!/usr/bin/env python3
"""One-shot migration: encrypt plaintext sensitive fields in data/tenants.json."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from amazon_mcp.gateway.tenant_credentials import TenantCredentialStore, get_default_credential_store


def main() -> int:
    parser = argparse.ArgumentParser(description="Encrypt tenant credentials in tenants.json")
    parser.add_argument(
        "--path",
        default=str(ROOT / "data" / "tenants.json"),
        help="Path to tenants.json (default: data/tenants.json)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not write")
    parser.add_argument("--key-path", default="", help="Override credential key file path")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"[migrate] no file at {path} — nothing to do")
        return 0

    store = (
        TenantCredentialStore(key_path=Path(args.key_path))
        if args.key_path
        else get_default_credential_store()
    )

    raw = json.loads(path.read_text())
    tenants = raw.get("tenants", [])
    if not tenants:
        print("[migrate] empty tenants list — nothing to do")
        return 0

    migrated = 0
    encrypted_tenants = []
    for item in tenants:
        if store.record_needs_migration(item):
            migrated += 1
        encrypted_tenants.append(store.encrypt_record(item))

    print(f"[migrate] tenants={len(tenants)} need_encryption={migrated}")
    if migrated == 0:
        print("[migrate] already encrypted — no changes")
        return 0

    payload = {
        "tenants": encrypted_tenants,
        "credentials_version": 1,
        "encryption": "fernet-local",
    }

    if args.dry_run:
        print("[migrate] dry-run — would write encrypted tenants.json")
        return 0

    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    path.write_text(json.dumps(payload, indent=2))
    print(f"[migrate] backup → {backup}")
    print(f"[migrate] encrypted {migrated} tenant record(s) → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
