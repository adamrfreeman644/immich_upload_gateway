# Immich Upload Gateway v0.4.0

Immich Upload Gateway provides public upload portals backed by Immich, with a private administration area, persistent fallback storage, Authentik-capable admin authentication, custom portal domains and an in-app updater.

## What is new in v0.4.0

- Existing 0.2.x/0.3.x `/config/config.json` files migrate in place without deleting portal tokens, API keys or fallback settings.
- The running version now comes from the repository `VERSION` file, fixing the old updater rollback caused by the application reporting a different hard-coded version.
- Portals are no longer limited to only `work` and `personal`.
- Add and remove portals from Admin.
- Give each portal one or more custom hostnames such as `wedding.ad53app.com`.
- Visiting an exact configured hostname serves that portal at `/`.
- Existing token links such as `/work?t=...` and `/personal?t=...` continue to work.
- QR codes automatically use the portal's first custom domain when one is configured.
- Admin now includes an **Updates** page with **Check for updates** and **Install update**.
- Update installation is handled by a separate Docker sidecar rather than exposing the Docker socket to the public gateway container.
- Compose no longer hard-codes container names, so a new release can run beside an existing 0.2.0 installation on another host port.

## Security model

Public upload portals do not require an Immich account. A legacy token URL authorises its portal only. A portal reached through an exact configured custom hostname is intentionally usable from that hostname without exposing the token in the address bar; the upload request still uses that portal's server-generated token internally.

Admin authentication remains separate from public upload access. When `AUTH_ENABLED=true`, Authentik OIDC protects `/admin` and `/admin/...`. During migration, `AUTH_ENABLED=false` keeps the legacy admin password available.

Do not expose Immich API keys, `.env`, `/config`, the updater sidecar or the Docker socket publicly.

## Custom portal domains

In Admin, open a portal and enter one or more hostnames in **Custom domains**, separated by commas:

```text
wedding.ad53app.com, photos.client-example.co.uk
```

Do not include `https://` or a path.

For each hostname:

1. Point DNS at the same public IP/reverse proxy used by the Gateway.
2. Add the hostname to Nginx Proxy Manager.
3. Forward it to the Gateway host and port.
4. Request an SSL certificate and enable Force SSL.
5. Keep the incoming `Host` header intact. Nginx Proxy Manager does this normally.

The Gateway matches the incoming hostname to the configured portal and serves that portal at the domain root.

## Safe side-by-side migration from 0.2.0

Do **not** delete the old container or its appdata first.

Create a separate folder for v0.4.0:

```bash
cd /mnt/user/appdata
git clone https://github.com/adamrfreeman644/immich_upload_gateway.git immich-upload-gateway-v040
cd immich-upload-gateway-v040
cp .env.example .env
```

Edit `.env` for the test installation. The important values are:

```text
GATEWAY_PORT=8093
COMPOSE_PROJECT_NAME=immich-gateway-v040
APP_HOST_PATH=/mnt/user/appdata/immich-upload-gateway-v040
CONFIG_HOST_PATH=/mnt/user/appdata/immich-upload-gateway/config
```

`CONFIG_HOST_PATH` should point to the existing persistent config used by 0.2.0. v0.4.0 adds missing schema fields while preserving existing values. The old application ignores the extra fields, so the old installation can remain stopped or available for rollback during testing.

Set the existing work/personal fallback paths to their current locations and choose a persistent `PORTAL_FALLBACK_HOST_PATH` for newly-created portals.

Start the new installation:

```bash
docker compose up -d --build
```

Open:

```text
http://YOUR-UNRAID-IP:8093/admin
```

Before removing 0.2.0, verify:

- Work portal opens and uploads correctly.
- Personal portal opens and uploads correctly.
- Existing API keys and portal settings are present.
- `/health` reports version `0.4.0`.
- Admin → Updates loads successfully.
- A temporary custom domain resolves to the expected portal.

When satisfied, stop the old 0.2.0 container. Change the new installation to `GATEWAY_PORT=8092` if you want to retain the old external port, recreate it with `docker compose up -d`, update Nginx Proxy Manager if required, retest, and only then delete the old **container**.

Do not remove the persistent config/fallback directories when deleting the old container.

## Update page

Admin → **Updates** asks the internal updater sidecar for the installed and latest GitHub versions.

When **Install update** is pressed, the sidecar:

1. Downloads the current GitHub branch archive.
2. Confirms the archive version matches GitHub `VERSION`.
3. Syntax-checks the Python application/updater.
4. Backs up managed application files.
5. Rebuilds only the Gateway service.
6. Waits for `/health`.
7. Confirms the running application reports the expected version.
8. Rolls back managed files and rebuilds the previous Gateway if validation fails.

The public Gateway container itself does not receive `/var/run/docker.sock`; only the internal updater sidecar does.

## Authentik configuration

Example `.env` values:

```text
AUTH_ENABLED=true
OIDC_ISSUER=https://auth.example.com/application/o/image-upload-gateway
OIDC_CLIENT_ID=image-upload-gateway
OIDC_CLIENT_SECRET=<secret from Authentik>
OIDC_REDIRECT_URI=https://uploads.example.com/auth/callback
OIDC_POST_LOGOUT_REDIRECT_URI=https://uploads.example.com/admin
COOKIE_SECURE=true
```

The public upload flow remains independent of Authentik availability. Admin routes fail closed if Authentik is enabled but incorrectly configured.

## Persistent data

The following are intentionally outside the image:

- `/config/config.json`
- `/config/session_secret`
- Existing Work fallback folder
- Existing Personal fallback folder
- Dynamic portal fallback folder

Removing/recreating the Docker containers does not remove these bind-mounted paths unless you manually delete the host directories.
