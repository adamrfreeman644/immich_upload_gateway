import importlib
import json
import sys

import pytest
from fastapi.testclient import TestClient


def load_gateway(monkeypatch, tmp_path, *, auth_enabled, complete=True):
    monkeypatch.setenv("AUTH_ENABLED", "true" if auth_enabled else "false")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-that-is-long-enough")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    if complete:
        monkeypatch.setenv("OIDC_ISSUER", "https://auth.example.test/application/o/gateway")
        monkeypatch.setenv("OIDC_CLIENT_ID", "gateway-test")
        monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setenv("OIDC_REDIRECT_URI", "http://testserver/auth/callback")
    else:
        for name in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI"):
            monkeypatch.delenv(name, raising=False)
    sys.modules.pop("secure_app", None)
    sys.modules.pop("app", None)
    legacy = importlib.import_module("app")
    legacy.CFG = tmp_path / "config.json"
    legacy.save({
        "immich_url": "http://immich.invalid",
        "public_base_url": "http://testserver",
        "portals": {
            "work": {"enabled": True, "name": "Work", "subtitle": "Upload", "design": "industrial", "accent": "#123456", "api_key": "immich-secret", "upload_token": "public-token", "fallback_dir": str(tmp_path / "fallback")},
            "personal": {"enabled": False, "name": "Personal", "subtitle": "", "design": "friendly", "accent": "#654321", "api_key": "", "upload_token": "other-token", "fallback_dir": str(tmp_path / "fallback2")},
        },
    })
    secure = importlib.import_module("secure_app")
    return legacy, secure, TestClient(secure.app)


def test_valid_public_upload_page_never_requires_authentik(monkeypatch, tmp_path):
    _, _, client = load_gateway(monkeypatch, tmp_path, auth_enabled=True)
    response = client.get("/work?t=public-token")
    assert response.status_code == 200
    assert "Upload files" in response.text


def test_public_uploader_cannot_open_admin(monkeypatch, tmp_path):
    _, _, client = load_gateway(monkeypatch, tmp_path, auth_enabled=True)
    response = client.get("/admin")
    assert response.status_code == 401
    assert "Continue with Authentik" in response.text


def test_public_token_does_not_browse_other_portal(monkeypatch, tmp_path):
    _, _, client = load_gateway(monkeypatch, tmp_path, auth_enabled=True)
    assert client.get("/personal?t=public-token").status_code in (403, 404)


def test_admin_auth_misconfiguration_fails_closed_but_public_stays_up(monkeypatch, tmp_path):
    _, _, client = load_gateway(monkeypatch, tmp_path, auth_enabled=True, complete=False)
    admin = client.get("/admin")
    public = client.get("/work?t=public-token")
    assert admin.status_code == 503
    assert "configuration is incomplete" in admin.text
    assert public.status_code == 200


def test_authenticated_admin_session_succeeds(monkeypatch, tmp_path):
    legacy, _, client = load_gateway(monkeypatch, tmp_path, auth_enabled=True)
    cookie = legacy.ser.dumps({"t": 1, "sub": "fingerprint", "name": "Owner", "provider": "authentik"})
    client.cookies.set("admin_session", cookie)
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Authentication" in response.text


def test_invalid_or_expired_oidc_exchange_is_rejected(monkeypatch, tmp_path):
    _, secure, client = load_gateway(monkeypatch, tmp_path, auth_enabled=True)

    class BrokenClient:
        async def authorize_access_token(self, request):
            raise ValueError("expired or invalid token")

    monkeypatch.setattr(secure, "client", BrokenClient())
    response = client.get("/auth/callback?code=invalid&state=invalid")
    assert response.status_code == 401
    assert "Sign-in failed" in response.text
    assert "expired or invalid token" not in response.text


def test_health_never_exposes_secrets(monkeypatch, tmp_path):
    _, _, client = load_gateway(monkeypatch, tmp_path, auth_enabled=True)
    response = client.get("/health")
    body = json.dumps(response.json())
    assert response.status_code == 200
    assert "immich-secret" not in body
    assert "test-client-secret" not in body
    assert "public-token" not in body
