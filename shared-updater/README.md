# AD53 Shared App Updater

One isolated updater container can manage multiple self-hosted applications on the same Docker host.

The updater is manifest-driven. Each managed app declares its GitHub repository, local source directory, Compose service, health/version endpoint, files that may be replaced, and optional preflight checks. This keeps Docker socket access out of public application containers while avoiding one updater sidecar per app.

## Security model

The shared updater has access to `/var/run/docker.sock` and therefore has powerful control over Docker on the host. Keep port `8093` private to the LAN/host. Do not expose it directly to the public internet.

Application containers do not need Docker socket access. They only call the updater HTTP API to read status or request an update.

## Install on Unraid

From the Immich Upload Gateway checkout:

```bash
cd /mnt/user/appdata/immich-upload-gateway/shared-updater
cp apps.example.json apps.json
mkdir -p state
```

Review `apps.json`. For the default Immich Gateway entry, the expected host application directory is:

```text
/mnt/user/appdata/immich-upload-gateway
```

Start the updater:

```bash
docker compose up -d --build
```

Check it:

```bash
curl http://127.0.0.1:8093/health
curl http://127.0.0.1:8093/apps
curl http://127.0.0.1:8093/apps/immich-gateway/status
```

The Gateway's older updater API is also supported through the configured `DEFAULT_APP_ID`:

```text
GET  /status
POST /install
```

This compatibility path lets the existing Immich Gateway Admin → Updates page work without requiring an immediate UI rewrite.

## Adding another app

Add another object to the `apps` array in `apps.json`, then mount that application's host source directory into the updater container.

Example registry entry:

```json
{
  "id": "inventory-manager",
  "name": "Inventory Manager",
  "repo": "your-user/inventory-manager",
  "branch": "main",
  "app_dir": "/apps/inventory-manager",
  "version_file": "VERSION",
  "compose_file": "docker-compose.yml",
  "compose_service": "inventory-manager",
  "health_url": "http://127.0.0.1:1975/health",
  "health_version_field": "version",
  "managed_files": [
    "app.py",
    "Dockerfile",
    "docker-compose.yml",
    "requirements.txt",
    "VERSION"
  ],
  "preflight": [
    ["python3", "-m", "py_compile", "app.py"]
  ]
}
```

Then add the corresponding bind mount to `shared-updater/docker-compose.yml`:

```yaml
- /mnt/user/appdata/inventory-manager:/apps/inventory-manager
```

Recreate only the updater:

```bash
docker compose up -d --build
```

No Docker socket or updater sidecar needs to be added to the Inventory Manager application itself.

## API

### List all apps

```text
GET /apps
```

### App status

```text
GET /apps/<app-id>/status
```

Returns the running version, local source version, latest GitHub version, update availability and last update state/log.

### Install update

```text
POST /apps/<app-id>/install
```

Starts that app's update. Only one update for a given app can run at a time.

### Health

```text
GET /health
```

## Update flow

For each app the updater:

1. Reads the currently installed/running version.
2. Reads the latest version from the app repository's `VERSION` file.
3. Creates a timestamped backup of the configured managed files.
4. Downloads the configured GitHub branch as a ZIP archive.
5. Confirms the archive version matches the expected latest version.
6. Runs configured preflight checks.
7. Copies only the explicitly listed managed files into the application directory.
8. Runs `docker compose build --pull <service>`.
9. Recreates only the target service with `docker compose up -d --no-deps <service>`.
10. Waits for the configured health endpoint to report the expected version.
11. Restores the backup and rebuilds the previous service if validation fails.

Backups and update state are stored under the shared updater's persistent `/state` volume.

## Registry fields

- `id`: unique updater ID used in the API.
- `name`: display name.
- `repo`: GitHub `owner/repository`.
- `branch`: source branch, normally `main`.
- `app_dir`: directory as mounted inside the updater container.
- `version_file`: version marker in the repository, normally `VERSION`.
- `compose_file`: Compose file inside the application directory.
- `compose_service`: service to rebuild/recreate.
- `health_url`: URL reachable from the updater. With `network_mode: host`, localhost host ports work on Linux/Unraid.
- `health_version_field`: JSON field returned by the health endpoint containing the running version.
- `managed_files`: files/directories the updater is allowed to replace and roll back.
- `preflight`: optional commands run against the downloaded source before installation.
- `health_timeout_seconds`: optional validation timeout; default 90 seconds.

## Important deployment rule

Do not point multiple independently running updater containers at the same app directory. The goal of this project is one shared updater per Docker host.
