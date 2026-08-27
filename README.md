# Immich Upload Gateway v0.3.0

Image Upload Gateway provides independent public upload portals plus a private administration area. Each portal retains its own Immich API key, unguessable upload token, fallback folder, design and accent colour.

## Security model

The Gateway deliberately has **two different security areas**.

### Public upload links — no login

Guests using a valid upload/QR link do **not** register, sign in to Authentik, create a password or need an Immich account. The existing flow remains:

1. Open the secure event/portal link.
2. Capture/select photos or video.
3. Upload originals.
4. Receive the existing completion result.

Public routes are the portal pages such as `/work?t=...` and `/personal?t=...`, the corresponding `/api/upload/{slug}?t=...` upload endpoint, `/`, `/health`, `/api/info`, and the OIDC start/callback routes needed for the separate admin login flow.

Each public portal token authorises only that configured upload destination. It does not grant Immich browsing, access to other uploads/events, admin settings, API credentials or another portal. Keep QR/upload URLs private enough for their intended audience and rotate a portal token from Admin if a link should no longer be usable.

An Authentik outage or admin OIDC configuration fault does **not** block a valid public upload link. Public upload processing continues as long as that portal and its Immich/fallback configuration are otherwise valid.

### Administration — Authentik OIDC

`/admin` and every `/admin/...` route are protected with Authentik when `AUTH_ENABLED=true`, including settings, QR/event/destination configuration and API credential management. Authentication uses OpenID Connect Authorization Code flow, state/nonce validation through Authlib, provider discovery/token validation and PKCE support.

The main Gateway page stays in place during login. **Continue with Authentik** opens a small popup window; the OIDC callback completes in the popup, which then closes and returns control to `/admin`. If the browser blocks popups, the flow falls back to a normal redirect.

Admin application sessions are local HttpOnly cookies. OIDC access, refresh and ID tokens are not persisted by the Gateway. Secrets and tokens are not shown in status output or intentionally logged.

## Authentik configuration

Create a separate OAuth2/OpenID Provider/Application in Authentik for the Gateway admin area. Register the exact externally reachable callback, for example:

```text
https://uploads.example.com/auth/callback
```

Configure the deployment environment from `.env.example`:

```text
AUTH_ENABLED=true
OIDC_ISSUER=https://auth.example.com/application/o/image-upload-gateway
OIDC_CLIENT_ID=image-upload-gateway
OIDC_CLIENT_SECRET=<secret from Authentik>
OIDC_REDIRECT_URI=https://uploads.example.com/auth/callback
OIDC_POST_LOGOUT_REDIRECT_URI=https://uploads.example.com/admin
COOKIE_SECURE=true
```

Never commit the OIDC client secret, Immich API keys, `SESSION_SECRET`, upload tokens or fallback media to Git. Keep them in `.env`, Docker secrets or the existing secure host configuration.

### Safe migration from the old admin password

v0.3.0 is non-destructive. Existing `/config/config.json`, portal tokens, Immich keys, fallback paths and uploader/update state are preserved. While `AUTH_ENABLED=false`, the previous `ADMIN_PASSWORD` login remains available specifically so an existing installation can configure/test Authentik without being locked out.

Once the Authentik client is configured, set `AUTH_ENABLED=true` and rebuild/restart. At that point the legacy `/admin/login` password endpoint is disabled; administrative routes fail closed if OIDC is incomplete. Do not remove your rollback copy of the old environment until the Authentik status panel shows **Connected**.

The Admin page displays only provider, connection/configuration state, issuer hostname, signed-in user and integration version. It never displays secrets or tokens.

## Logout and recovery

Admin **Log out** deletes the local Gateway session and uses the Authentik OIDC end-session endpoint when advertised. Password reset, recovery, MFA and passkeys belong to Authentik rather than the Gateway.

## Immich compatibility and upload safety

The uploader sends originals through Immich's asset upload API. If Immich is unreachable or an upload fails in a supported fallback case, the original file is moved into the configured fallback directory instead of being discarded. In `/admin`, each Immich API key remains masked; leaving the key field blank keeps the current value.

`public_base_url` must be the address guests can actually reach from a QR code. For remote uploads use the externally reachable HTTPS Gateway URL, not a LAN-only address.

## Install / upgrade

```bash
cd /mnt/user/appdata
git clone https://github.com/adamrfreeman644/immich_upload_gateway.git immich-upload-gateway
cd immich-upload-gateway
cp .env.example .env
# Edit .env before starting
docker compose up -d --build
```

Persistent configuration/fallback directories are bind-mounted and intentionally ignored by Git.

### One-time v0.3.0 steps

1. Keep `AUTH_ENABLED=false` initially and preserve your current `.env` and `/config` backup.
2. Create the Gateway admin Provider/Application in Authentik.
3. Register the exact `/auth/callback` URL and add the OIDC environment values.
4. Use HTTPS and set `COOKIE_SECURE=true` for externally accessible deployments.
5. Set `AUTH_ENABLED=true`, rebuild/restart, then open `/admin` and complete popup sign-in.
6. Confirm the Authentication panel says **Connected** and confirm both public upload links still work without login.

## Update behaviour

`gateway-updater.sh` continues to compare the installed `VERSION` with GitHub, validates Python/Compose, rebuilds only on a requested version change, verifies `/health` and rolls back on deployment failure. Authentication was added as a wrapper entrypoint; the updater implementation and persistent configuration paths were not replaced.
