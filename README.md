# Immich Upload Gateway v0.2.1

Two independent upload portals in one container: `/work` and `/personal`, plus the private `/admin` page. Each portal has its own Immich API key, upload token, fallback folder, design and accent colour.

## v0.2.1 fixes

- **Prevents upload loss when Immich is unreachable.** Connection errors and timeouts now move the original file into the configured fallback directory instead of deleting the temporary upload.
- Keeps the admin session secret persistent in `/config/session_secret` when `SESSION_SECRET` is not explicitly configured, so container restarts no longer invalidate every admin session.
- Escapes editable portal/admin text before rendering it into HTML.
- Admin settings use POST → redirect → GET, preventing browser refresh from accidentally submitting the previous settings form again.
- Updater now validates Python syntax and Compose configuration before deployment, waits for health, verifies the installed version and rolls back on failure.
- Updater temporary staging is always cleaned up.

## Immich compatibility

The uploader uses `POST /api/assets` and sends `assetData`, `fileCreatedAt`, `fileModifiedAt` and `isFavorite`. This matches the current Immich asset-upload endpoint; Immich v3 removed the old `deviceId` and `deviceAssetId` upload fields.

## Configuration

Copy `.env.example` to `.env` and change at least:

- `ADMIN_PASSWORD`
- `SESSION_SECRET` (recommended; if omitted, v0.2.1 generates a persistent secret under `/config`)
- fallback host paths as required

In `/admin`, configure a separate Immich API key for each destination portal. Give each key only the permissions needed to upload assets.

`public_base_url` must be the URL guests can actually reach when scanning a QR code. For remote uploads, use the externally accessible HTTPS gateway URL rather than a LAN-only address.

## Install from GitHub

```bash
cd /mnt/user/appdata
git clone https://github.com/adamrfreeman644/immich_upload_gateway.git immich-upload-gateway
cd immich-upload-gateway
cp .env.example .env
# Edit .env before starting
docker compose up -d --build
```

The persistent configuration and fallback directories are bind-mounted and are intentionally ignored by Git. Never commit `.env`, API keys, the admin password, session secrets, uploads or fallback media.

## Update behaviour

`gateway-updater.sh` now checks the public GitHub repository directly. It compares the installed `VERSION` with `main/VERSION`, downloads the GitHub branch archive only when the version changes, validates Python and Compose, rebuilds the container, verifies `/health`, checks the running version and rolls back if deployment fails.

Defaults:

- repository: `adamrfreeman644/immich_upload_gateway`
- branch: `main`
- app directory: `/mnt/user/appdata/immich-upload-gateway`
- health URL: `http://127.0.0.1:8092/health`

Override `REPO`, `BRANCH`, `APP_DIR` or `HEALTH_URL` with environment variables if needed. The updater preserves `.env`, `/config`, fallback data and any other unmanaged files. Managed-file backups are created under `backups/`.
