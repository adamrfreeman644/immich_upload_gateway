# Immich Upload Gateway

A lightweight self-hosted upload gateway for [Immich](https://immich.app/) that lets other people upload original photos and videos into your Immich library without giving them an Immich account.

**Current version: 0.5.4**

The gateway provides multiple independent upload portals, custom domains, QR codes, per-file upload progress and thumbnails, persistent fallback storage, a private admin interface and integration with a reusable shared updater.

> This project is an independent companion for Immich and is not part of the Immich project.

## What it does

A visitor opens a portal such as `https://uploadphotos.example.com`, selects photos/videos and uploads them. The browser shows a thumbnail and individual progress/result for every file. The original file is sent to Immich without recompression.

Each portal has its own Immich API key. **Assets are uploaded into the Immich library belonging to that API key.** If you want gateway uploads to appear in your normal Immich Photos timeline, create the API key while logged into the same Immich user whose timeline you use. Use the same API key on multiple portals if they should all feed the same Immich library.

If Immich cannot be reached, the gateway saves the original file to persistent fallback storage instead of silently losing it.

## Features

- Multiple independently configurable upload portals
- Original image/video upload without recompression
- Separate Immich API key per portal
- Uploads appear in the API-key owner's normal Immich library/timeline
- Successful uploads are automatically collected in **Uploaded though Portal**
- Custom domain(s) per portal
- Legacy private token URLs for portals without domains
- QR-code generation from Admin
- Per-file progress bars
- Local browser thumbnails/previews
- Individual retry for failed uploads
- Persistent fallback storage when Immich is unavailable
- Friendly and industrial portal designs with configurable accent colours
- Password-protected Admin interface
- Health/version endpoints
- Shared update service with backup, validation and rollback
- Docker Compose deployment
- Designed to work well on Unraid

## Requirements

You need:

- A working Immich server
- Docker with Docker Compose
- A machine capable of reaching the Immich server
- An Immich API key for each destination user/library
- Optional: a domain, DNS provider and reverse proxy such as Nginx Proxy Manager for public HTTPS portals

## 1. Create the Immich API key

Log into Immich as the **user who should own the uploaded photos** and create an API key in that user's account settings.

Keep the key private. Do not place it in DNS, Nginx Proxy Manager or a public URL. It is stored server-side by the gateway.

If Work and Personal portals should both upload into the same main Photos timeline, configure both portals with an API key belonging to that same Immich user.

## 2. Fresh installation

### Unraid / Linux command line

Choose a persistent application directory. On Unraid:

```bash
cd /mnt/user/appdata
git clone https://github.com/adamrfreeman644/immich_upload_gateway.git immich-upload-gateway
cd immich-upload-gateway
cp .env.example .env
```

Edit `.env`:

```bash
nano .env
```

At minimum change `ADMIN_PASSWORD`. Also set a long random `SESSION_SECRET` rather than leaving `CHANGE_ME`.

Typical Unraid configuration:

```dotenv
AUTH_ENABLED=false
ADMIN_PASSWORD=replace-with-a-strong-password
SESSION_SECRET=replace-with-a-long-random-secret
COOKIE_SECURE=false
MAX_FILE_MB=5000

GATEWAY_PORT=8092
COMPOSE_PROJECT_NAME=immich-upload-gateway
GATEWAY_CONTAINER_NAME=immich-gateway
APP_HOST_PATH=/mnt/user/appdata/immich-upload-gateway
UPDATER_URL=http://host.docker.internal:8093

CONFIG_HOST_PATH=/mnt/user/appdata/immich-upload-gateway/config
WORK_FALLBACK_HOST_PATH=/mnt/user/PhotoUploadFallback/Work
PERSONAL_FALLBACK_HOST_PATH=/mnt/user/PhotoUploadFallback/Personal
PORTAL_FALLBACK_HOST_PATH=/mnt/user/PhotoUploadFallback/Portals
```

Start the gateway:

```bash
docker compose up -d --build
```

Check it:

```bash
docker compose ps
curl http://YOUR-SERVER-IP:8092/health
```

The health response should report `status: ok` and version `0.5.4`.

## 3. Install the shared updater

Version 0.5.0 introduces a separate **AD53 Shared App Updater** that can eventually manage all compatible self-hosted apps on the server.

It replaces the need for one updater sidecar per application.

From the Gateway checkout:

```bash
cd /mnt/user/appdata/immich-upload-gateway/shared-updater
cp apps.example.json apps.json
mkdir -p state
```

Review `apps.json`. The default Immich Gateway entry expects:

```text
/mnt/user/appdata/immich-upload-gateway
```

as the Gateway source directory.

Start the shared updater:

```bash
docker compose up -d --build
```

Check it:

```bash
curl http://127.0.0.1:8093/health
curl http://127.0.0.1:8093/apps
curl http://127.0.0.1:8093/apps/immich-gateway/status
```

The updater runs with `network_mode: host`, so it can validate application health endpoints using localhost host ports.

The updater is intentionally **not public-facing**. It has access to `/var/run/docker.sock`, so keep port `8093` private to the server/LAN.

For full updater documentation see [`shared-updater/README.md`](shared-updater/README.md).

## 4. Open Admin

Open:

```text
http://YOUR-SERVER-IP:8092/admin
```

Sign in using `ADMIN_PASSWORD` from `.env`.

The default configuration contains **Work** and **Personal** portals. You can edit these, disable them, or create additional portals.

## 5. Configure the Immich server

At the top of Admin set **Immich URL** to an address reachable from the gateway container/host.

Example:

```text
http://192.168.1.187:8080
```

Do not use the public upload portal address here. This must point to the actual Immich server.

Use the final URL directly. If the address redirects from HTTP to HTTPS, configure its `https://` form instead; the gateway deliberately rejects redirects so a proxy redirect cannot be mistaken for a successful upload.

The gateway automatically handles the Immich `/api` path.

## 6. Configure a portal

For each portal configure:

- **Enabled** — whether the portal is active.
- **Name** — heading shown to visitors.
- **Subtitle** — explanatory text shown on the upload page.
- **Custom domains** — optional comma-separated hostnames, without `https://`.
- **Design** — friendly or industrial.
- **Accent** — portal colour.
- **Immich API key** — API key belonging to the Immich user who should receive the uploads.
- **Upload token** — private token used by legacy/token links.
- **Fallback path** — container-side location used if Immich cannot accept the file.

Press **Save settings**.

The API key field is intentionally blank after saving; entering nothing later keeps the existing stored key.

For automatic album assignment, the API key needs `asset.upload`, `album.read`, `album.create` and `albumAsset.create` permissions. The gateway creates the album empty before adding an asset, so `asset.share` is not required.

## 7. Test locally first

Before configuring a public domain, use the portal link shown in Admin or click **Open portal**.

Select a small test image. You should see:

1. A thumbnail beside the file.
2. The filename and size.
3. An individual upload progress bar.
4. `Uploaded` when Immich accepts it.

Then open Immich using the user that created the API key. The uploaded asset should appear in that user's normal Photos timeline.

If it appears under a different Immich user, the portal is using that other user's API key. Replace the portal key with one created by the intended user.

## 8. Custom domains and HTTPS

A portal can be served directly at a hostname such as:

```text
uploadphotos.example.com
workphotos.example.com
smith-wedding.example.com
```

Enter only the hostname in **Custom domains**. Do not include `https://`, ports or paths.

### DNS

Create a DNS record for the hostname pointing to the public IP/reverse proxy that serves the gateway.

### Nginx Proxy Manager

Create a Proxy Host for each portal domain:

- **Domain Names:** the portal hostname
- **Scheme:** `http`
- **Forward Hostname/IP:** IP address of the machine running the gateway
- **Forward Port:** `8092` (or your `GATEWAY_PORT`)

Under **SSL**:

- Request/select a Let's Encrypt certificate
- Enable **Force SSL**
- Enable HTTP/2 if desired

Nginx Proxy Manager normally preserves the incoming host information required by the gateway. The gateway matches the hostname against the domains configured for each portal and serves the matching portal directly at `/`.

For large uploads, make sure your reverse proxy does not impose a smaller request/body-size limit than the gateway's `MAX_FILE_MB` value.

After HTTPS is working you can set:

```dotenv
COOKIE_SECURE=true
```

and recreate the gateway:

```bash
cd /mnt/user/appdata/immich-upload-gateway
docker compose up -d
```

## 9. QR codes

Admin has a **QR code** button for each portal.

If a portal has a custom domain, the QR code uses its first configured domain. Otherwise it uses the gateway's fallback public URL plus the portal's private upload token.

You can print/display the QR code for events, customers, family uploads or temporary collection points.

## 10. How uploads are stored in Immich

The gateway sends accepted files to Immich's asset API using the portal's configured API key. It supplies the original file and its browser-provided modification timestamp and does not recompress the asset.

The Immich account that owns the API key owns the resulting asset. Every successful upload is also added to an album named **Uploaded though Portal** in that account. The gateway reuses that album, or creates it on the first successful upload.

Therefore:

- Same API key on Work + Personal = both feed the same Immich user's Photos timeline.
- Different API keys = each portal feeds its respective Immich user's library and each user receives their own **Uploaded though Portal** album.

## 11. Fallback storage

If the Immich connection fails or Immich returns an error, the gateway moves the original temporary upload into the portal's persistent fallback directory.

The UI reports **Saved safely** rather than pretending the asset reached Immich.

On Unraid the default host locations are:

```text
/mnt/user/PhotoUploadFallback/Work
/mnt/user/PhotoUploadFallback/Personal
/mnt/user/PhotoUploadFallback/Portals
```

These locations are bind-mounted and survive container recreation.

Unsupported extensions are also placed in fallback storage.

## 12. File support and upload size

The gateway currently accepts common photo, RAW and video formats including JPEG, PNG, WebP, HEIC/HEIF, GIF, TIFF, DNG, NEF, CR2/CR3, ARW, RAF, AVIF, MP4, MOV, M4V, 3GP, WebM, MKV and AVI.

`MAX_FILE_MB` controls the maximum file size accepted by the gateway. The default is 5000 MB.

Your reverse proxy may have its own independent upload limit/timeouts, so increase those if very large videos fail before reaching the gateway.

## 13. Updates in v0.5.0+

Open:

**Admin → Updates**

The Gateway now talks to the shared updater at the URL configured in `UPDATER_URL`.

For compatibility, the shared updater exposes the old Gateway endpoints:

```text
GET  /status
POST /install
```

internally mapped to the configured default app (`immich-gateway`). It also provides the reusable multi-app API:

```text
GET  /apps
GET  /apps/<app-id>/status
POST /apps/<app-id>/install
```

For each app the shared updater:

1. Checks the latest GitHub `VERSION`.
2. Creates a timestamped backup of managed files.
3. Downloads and validates the configured GitHub branch.
4. Runs configured preflight checks.
5. Replaces only explicitly managed files.
6. Rebuilds only the target Compose service.
7. Recreates only the target service.
8. Waits for its health endpoint.
9. Verifies the running version.
10. Restores the previous managed files and rebuilds if validation fails.

The Gateway itself does not receive `/var/run/docker.sock`.

## 14. Moving from 0.4.5 to 0.5.0

Because 0.4.5 still uses its dedicated updater sidecar, use this order for the first migration:

### A. Pull the new source files without stopping the running gateway

On Unraid:

```bash
cd /mnt/user/appdata/immich-upload-gateway
git pull
```

### B. Start the new shared updater first

```bash
cd /mnt/user/appdata/immich-upload-gateway/shared-updater
cp -n apps.example.json apps.json
mkdir -p state
docker compose up -d --build
```

Verify:

```bash
curl http://127.0.0.1:8093/apps/immich-gateway/status
```

### C. Recreate the Gateway using the new single-app Compose configuration

```bash
cd /mnt/user/appdata/immich-upload-gateway
docker compose up -d --build
```

### D. Remove the old dedicated updater container

Once **Admin → Updates** successfully shows status through the shared updater:

```bash
docker rm -f immich-gateway-updater 2>/dev/null || true
```

The old updater definition remains available only through the optional `legacy-updater` profile for migration/rollback troubleshooting. A fresh install does not start it.

From this point onward the Gateway itself is just one application container, while the single shared updater can manage it and additional applications.

## 15. Adding more apps to the shared updater

Edit:

```text
/mnt/user/appdata/immich-upload-gateway/shared-updater/apps.json
```

Add another app definition containing its:

- unique ID
- display name
- GitHub repository/branch
- mounted application directory
- `VERSION` file
- Compose file/service
- health endpoint
- managed files
- optional preflight commands

Then add that application's source directory as another bind mount in `shared-updater/docker-compose.yml` and recreate only the shared updater.

See [`shared-updater/README.md`](shared-updater/README.md) for a complete example.

## 16. Persistent data and backups

Important Gateway persistent data includes:

```text
/config/config.json
/config/session_secret
/fallback/work
/fallback/personal
/fallback/portals
```

The shared updater additionally stores update state and backups in its persistent `state` directory.

Back up at least the Gateway configuration directory, fallback folders containing pending files, and shared-updater state if you want to retain update history/backups.

## 17. Troubleshooting

### Upload says successful but I cannot see the photo in my main stream

Check which Immich user created the API key configured for that portal. The uploaded asset belongs to the API-key owner. Create a new API key while logged into the desired Immich user and save it on the portal.

### `No API key configured for this portal`

Open Admin, enter an Immich API key on that portal and save settings.

### Upload says `Saved safely`

The browser successfully sent the file to the gateway, but the gateway could not complete the Immich upload. Check Immich availability, `Immich URL`, API-key validity and container logs. The original should be in fallback storage.

### Admin → Updates says updater unavailable

Check the shared updater first:

```bash
curl http://127.0.0.1:8093/health
curl http://127.0.0.1:8093/apps/immich-gateway/status
```

Then confirm the Gateway `.env` contains:

```dotenv
UPDATER_URL=http://host.docker.internal:8093
```

and recreate the Gateway if the environment value changed.

### Portal domain shows the generic gateway page

Check that the exact hostname is entered under that portal's **Custom domains** and that the reverse proxy preserves the Host/X-Forwarded-Host header.

### Large uploads fail through the public domain but work locally

Check reverse-proxy body-size and timeout limits. `MAX_FILE_MB` only controls the gateway's own limit.

### Check Gateway logs

```bash
cd /mnt/user/appdata/immich-upload-gateway
docker compose logs -f immich-upload-gateway
```

### Check shared updater logs

```bash
cd /mnt/user/appdata/immich-upload-gateway/shared-updater
docker compose logs -f ad53-shared-updater
```

### Check Gateway health

```bash
curl http://YOUR-SERVER-IP:8092/health
```

## 18. Security notes

- Never expose Immich API keys to visitors or put them in URLs.
- Use HTTPS for public portals.
- Use a strong Admin password.
- Use a strong random session secret.
- Do not publicly expose `/config`, fallback host directories, the shared updater or Docker socket.
- **Only the shared updater should have Docker socket access.**
- Keep Immich itself updated and independently secured.
- A custom-domain portal is intentionally an upload endpoint for anyone who can reach that hostname. Use an unguessable/token portal instead when public discoverability is inappropriate.

## Repository layout

- `app.py` — gateway, portal UI and Admin UI
- `docker-compose.yml` — Gateway application Compose definition
- `Dockerfile` — Gateway image
- `shared-updater/` — reusable central updater service and app registry
- `Dockerfile.updater` — legacy per-Gateway updater image retained for migration/rollback only
- `updater_service.py` — legacy updater service retained for migration/rollback only
- `gateway-updater.sh` — legacy update script retained for migration/rollback only
- `.env.example` — Gateway deployment configuration template
- `VERSION` — current application version
- `CHANGELOG.md` — release history
- `tests/` — automated tests

## Version history

See [CHANGELOG.md](CHANGELOG.md) for release details.
