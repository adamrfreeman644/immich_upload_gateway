from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import secrets
import time
from urllib.parse import urlencode, urlparse

import httpx
from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

import app as legacy

app = legacy.app
log = logging.getLogger("gateway-auth")
INTEGRATION_VERSION = "shared-auth-1"


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


AUTH_ENABLED = env_bool("AUTH_ENABLED", False)
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "").strip().rstrip("/")
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "").strip()
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "").strip()
OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "").strip()
OIDC_POST_LOGOUT_REDIRECT_URI = os.getenv("OIDC_POST_LOGOUT_REDIRECT_URI", "").strip()
COOKIE_SECURE = env_bool("COOKIE_SECURE", legacy.COOKIE_SECURE)
SESSION_COOKIE = "gateway_oidc_state"


def missing_config() -> list[str]:
    if not AUTH_ENABLED:
        return []
    values = {
        "OIDC_ISSUER": OIDC_ISSUER,
        "OIDC_CLIENT_ID": OIDC_CLIENT_ID,
        "OIDC_CLIENT_SECRET": OIDC_CLIENT_SECRET,
        "OIDC_REDIRECT_URI": OIDC_REDIRECT_URI,
    }
    return [k for k, v in values.items() if not v]


def issuer_host() -> str:
    try:
        return urlparse(OIDC_ISSUER).hostname or OIDC_ISSUER
    except Exception:
        return OIDC_ISSUER


# Authlib stores only the short-lived OIDC transaction state in this signed,
# HttpOnly cookie. Access/refresh/ID tokens are never persisted by the app.
app.add_middleware(
    SessionMiddleware,
    secret_key=legacy.SESSION_SECRET,
    session_cookie=SESSION_COOKIE,
    same_site="lax",
    https_only=COOKIE_SECURE,
    max_age=900,
)

oauth = OAuth()
client = None
if AUTH_ENABLED and not missing_config():
    oauth.register(
        name="authentik",
        server_metadata_url=f"{OIDC_ISSUER}/.well-known/openid-configuration",
        client_id=OIDC_CLIENT_ID,
        client_secret=OIDC_CLIENT_SECRET,
        client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
    )
    client = oauth.create_client("authentik")


def admin_identity(request: Request) -> dict:
    try:
        value = legacy.ser.loads(request.cookies.get("admin_session", ""), max_age=43200)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def login_page(error: str = "") -> HTMLResponse:
    err = f'<p class="bad">{html.escape(error)}</p>' if error else ""
    start = "/auth/start"
    body = f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>{legacy.ACSS}</style></head><body><main class="shell" style="max-width:470px;padding-top:12vh"><section class="panel"><h1>Gateway administration</h1><p class="muted">Admin sign-in is handled by Authentik. Public upload links do not require login.</p>{err}<button id="oidc" style="width:100%;margin-top:14px">Continue with Authentik</button></section></main><script>document.getElementById('oidc').onclick=()=>{{const w=window.open({json.dumps(start)},'gateway-auth','popup=yes,width=520,height=720,resizable=yes,scrollbars=yes');if(!w)location.href={json.dumps(start)};}};window.addEventListener('message',e=>{{if(e.origin===location.origin&&e.data&&e.data.type==='gateway-auth-complete')location.replace('/admin');}});</script></body></html>'''
    return HTMLResponse(body, status_code=503 if error else 401)


def config_error() -> HTMLResponse:
    missing = missing_config()
    msg = "Authentication is enabled but OIDC configuration is incomplete."
    if missing:
        msg += " Missing: " + ", ".join(missing)
    log.error("Gateway OIDC configuration error; protected admin access denied")
    return login_page(msg)


_original_admin_page = legacy.admin_page


def admin_page_with_auth(c, msg=""):
    page = _original_admin_page(c, msg)
    # The identity is injected per request by middleware into a small process
    # local variable? No: use a neutral panel and fill the current user with JS
    # from the protected status endpoint, keeping secrets out of the HTML.
    panel = f'''<section class="panel full"><h2>Authentication</h2><p><strong>Provider:</strong> Authentik</p><p><strong>Status:</strong> <span id="auth-state">Checking…</span></p><p><strong>OIDC issuer:</strong> {html.escape(issuer_host() or 'Not configured')}</p><p><strong>Signed in as:</strong> <span id="auth-user">Checking…</span></p><p><strong>Integration:</strong> {INTEGRATION_VERSION}</p><script>fetch('/admin/auth/status').then(r=>r.json()).then(j=>{{document.getElementById('auth-state').textContent=j.connected?'Connected':'Configuration error';document.getElementById('auth-user').textContent=j.current_user||'Signed in';}}).catch(()=>{{document.getElementById('auth-state').textContent='Configuration error';}})</script></section>'''
    return page.replace('</div></form>', panel + '</div></form>')


legacy.admin_page = admin_page_with_auth


@app.middleware("http")
async def protect_admin_routes(request: Request, call_next):
    path = request.url.path
    # Explicit public groups: health/info, root, public portal pages and upload
    # APIs never depend on Authentik and continue working during an IdP outage.
    if not path.startswith("/admin"):
        return await call_next(request)
    if not AUTH_ENABLED:
        # Upgrade-safe migration mode: retain the existing local admin password
        # until Authentik has been configured and AUTH_ENABLED is deliberately set.
        return await call_next(request)
    if missing_config() or client is None:
        return config_error()
    if path == "/admin/login":
        return JSONResponse({"detail": "Local password login is disabled while Authentik authentication is enabled."}, status_code=410)
    if path == "/admin/logout":
        return await oidc_logout(request)
    if not legacy.admin_ok(request):
        if path == "/admin":
            return login_page()
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return await call_next(request)


@app.get("/auth/start")
async def oidc_start(request: Request):
    if not AUTH_ENABLED or missing_config() or client is None:
        return config_error()
    nonce = secrets.token_urlsafe(24)
    request.session["oidc_nonce"] = nonce
    try:
        return await client.authorize_redirect(request, OIDC_REDIRECT_URI, nonce=nonce)
    except Exception as exc:
        log.warning("OIDC authorization start failed: %s", exc.__class__.__name__)
        return login_page("Could not contact the authentication provider.")


@app.get("/auth/callback")
async def oidc_callback(request: Request):
    if not AUTH_ENABLED or missing_config() or client is None:
        return config_error()
    try:
        token = await client.authorize_access_token(request)
        user = token.get("userinfo") or {}
        if not user:
            user = await client.parse_id_token(request, token, nonce=request.session.get("oidc_nonce"))
        subject = str(user.get("sub", "")).strip()
        if not subject:
            raise ValueError("OIDC subject missing")
        display = str(user.get("name") or user.get("preferred_username") or user.get("email") or "Authentik user")
        email_value = str(user.get("email") or "")
        request.session.clear()
        payload = {
            "t": time.time(),
            "sub": hashlib.sha256(subject.encode()).hexdigest()[:16],
            "name": display[:160],
            "email": email_value[:254],
            "provider": "authentik",
        }
        response = HTMLResponse("""<!doctype html><html><body style='font-family:system-ui;padding:24px'>Signed in. You can close this window.<script>(function(){if(window.opener&&!window.opener.closed){window.opener.postMessage({type:'gateway-auth-complete'},location.origin);window.close();}else{location.replace('/admin');}})();</script></body></html>""")
        response.set_cookie("admin_session", legacy.ser.dumps(payload), httponly=True, samesite="strict", secure=COOKIE_SECURE, max_age=43200, path="/")
        return response
    except Exception as exc:
        log.warning("OIDC callback failed: %s", exc.__class__.__name__)
        return login_page("Sign-in failed. Please try again or check Authentik configuration.")


async def oidc_logout(request: Request):
    target = OIDC_POST_LOGOUT_REDIRECT_URI or str(request.base_url).rstrip("/") + "/admin"
    end_session = ""
    if OIDC_ISSUER:
        try:
            async with httpx.AsyncClient(timeout=5) as http:
                r = await http.get(f"{OIDC_ISSUER}/.well-known/openid-configuration")
                if r.is_success:
                    end_session = str(r.json().get("end_session_endpoint") or "")
        except Exception as exc:
            log.warning("OIDC logout discovery failed: %s", exc.__class__.__name__)
    destination = end_session + "?" + urlencode({"client_id": OIDC_CLIENT_ID, "post_logout_redirect_uri": target}) if end_session else target
    response = RedirectResponse(destination, status_code=303)
    response.delete_cookie("admin_session", path="/")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/admin/auth/status")
async def auth_status(request: Request):
    if AUTH_ENABLED and not legacy.admin_ok(request):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    ident = admin_identity(request)
    return {
        "provider": "Authentik" if AUTH_ENABLED else "Legacy migration mode",
        "enabled": AUTH_ENABLED,
        "connected": bool(AUTH_ENABLED and not missing_config() and client is not None),
        "configuration_error": bool(AUTH_ENABLED and (missing_config() or client is None)),
        "issuer_hostname": issuer_host(),
        "current_user": ident.get("name") or ident.get("email") or "",
        "integration_version": INTEGRATION_VERSION,
    }
