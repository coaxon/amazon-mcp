"""Tenant credential encryption and migration tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from amazon_mcp.gateway.router import GatewayRouter
from amazon_mcp.gateway.tenant import TenantContext, TenantRegistry
from amazon_mcp.gateway.tenant_credentials import (
    LocalFernetEncryptor,
    TenantCredentialStore,
    reset_default_credential_store,
)


@pytest.fixture
def cred_store(tmp_path: Path) -> TenantCredentialStore:
    reset_default_credential_store()
    return TenantCredentialStore(key_path=tmp_path / "key.bin")


def test_encrypt_decrypt_roundtrip(cred_store: TenantCredentialStore):
    plain = "super-secret-refresh-token"
    enc = cred_store.encrypt_field(plain)
    assert enc.startswith("enc:v1:")
    assert cred_store.decrypt_field(enc) == plain


def test_encrypt_record_preserves_plaintext_fields(cred_store: TenantCredentialStore):
    record = {
        "tenant_id": "t1",
        "marketplace_id": "ATVPDKIKX0DER",
        "dry_run": True,
        "lwa_client_secret": "sec-abc",
        "lwa_refresh_token": "rt-xyz",
    }
    enc = cred_store.encrypt_record(record)
    assert enc["tenant_id"] == "t1"
    assert enc["marketplace_id"] == "ATVPDKIKX0DER"
    assert enc["lwa_client_secret"].startswith("enc:v1:")
    dec = cred_store.decrypt_record(enc)
    assert dec["lwa_client_secret"] == "sec-abc"
    assert dec["lwa_refresh_token"] == "rt-xyz"


def test_registry_persists_encrypted_on_disk(cred_store: TenantCredentialStore, tmp_path: Path):
    reg_path = tmp_path / "tenants.json"
    reg = TenantRegistry(path=reg_path, credential_store=cred_store)
    reg.register(TenantContext(
        tenant_id="enc-tenant",
        lwa_client_id="cid",
        lwa_client_secret="secret-one",
        lwa_refresh_token="refresh-one",
        dry_run=True,
    ))
    raw = json.loads(reg_path.read_text())
    stored = raw["tenants"][0]
    assert stored["lwa_client_secret"].startswith("enc:v1:")
    assert raw.get("encryption") == "fernet-local"

    reloaded = TenantRegistry(path=reg_path, credential_store=cred_store)
    ctx = reloaded.get("enc-tenant")
    assert ctx is not None
    assert ctx.lwa_client_secret == "secret-one"


def test_gateway_resolve_after_encrypted_registry(cred_store: TenantCredentialStore, tmp_path: Path):
    GatewayRouter.reset_singleton()
    reg_path = tmp_path / "tenants.json"
    reg = TenantRegistry(path=reg_path, credential_store=cred_store)
    reg.register(TenantContext(
        tenant_id="router-test",
        lwa_client_id="client-router",
        lwa_client_secret="sec-router",
        lwa_refresh_token="rt-router",
        dry_run=True,
    ))
    router = GatewayRouter(registry=reg)
    cfg, sp, ads = router.resolve("router-test")
    assert cfg.lwa_client_id == "client-router"
    assert sp.cfg.lwa_client_secret == "sec-router"
    assert ads is not None
    GatewayRouter.reset_singleton()


def test_migration_script_encrypts_plaintext(tmp_path: Path, cred_store: TenantCredentialStore):
    tenants_path = tmp_path / "tenants.json"
    tenants_path.write_text(json.dumps({
        "tenants": [{
            "tenant_id": "migrate-me",
            "lwa_client_id": "c1",
            "lwa_client_secret": "plain-secret",
            "lwa_refresh_token": "plain-rt",
            "dry_run": True,
        }]
    }))
    assert cred_store.record_needs_migration(json.loads(tenants_path.read_text())["tenants"][0])
    payload = json.loads(tenants_path.read_text())
    encrypted = [cred_store.encrypt_record(t) for t in payload["tenants"]]
    assert encrypted[0]["lwa_client_secret"].startswith("enc:v1:")
