# AD53 Shared App Updater

One isolated updater container manages the local Docker application updates for the self-hosted AD53 apps on the same Unraid/Docker host.

Current registered apps:

- `immich-gateway` — Immich Upload Gateway
- `inventory-manager` — Inventory Manager / stock-take
- `rip-manager` — Rip Manager local container

Rip Node updates remain handled by Rip Manager because those updates target separate node machines rather than the local Docker host.

## Security model

`ad53-shared-updater` is the only application updater container that needs `/var/run/docker.sock`. Because Docker socket access is powerful, keep updater port `8093` private to the host/LAN and do not expose it directly to the internet.

Application containers do not need Docker socket access. Their Updates pages call the shared updater HTTP API.

Private GitHub repositories are supported through an optional per-app read-only token file. Rip Manager uses the existing host token mounted at `/run/secrets/rip-github-token`.

## Install / refresh on Unraid

```bash
cd /mnt/user/appdata/immich-upload-gateway
git pull
cd shared-updater
cp apps.example.json apps.json
mkdir -p state
docker compose up -d --build
```

If you have manually customised `apps.json`, merge the new entries instead of blindly overwriting it.

The default host paths are:

```text
/mnt/user/appdata/immich-upload-gateway
/mnt/user/appdata/stock-take
/mnt/user/appdata/rip-manager
```

They can be overridden with:

```text
IMMICH_GATEWAY_APP_PATH
INVENTORY_MANAGER_APP_PATH
RIP_MANAGER_APP_PATH
RIP_GITHUB_TOKEN_PATH
```

## Verify all apps

```bash
curl http://127.0.0.1:8093/health
curl http://127.0.0.1:8093/apps
curl http://127.0.0.1:8093/apps/immich-gateway/status
curl http://127.0.0.1:8093/apps/inventory-manager/status
curl http://127.0.0.1:8093/apps/rip-manager/status
```

`/apps` should show all three applications.

## API

```text
GET  /health
GET  /apps
GET  /apps/<app-id>/status
POST /apps/<app-id>/install
```

For backwards compatibility with the Immich Gateway migration, `DEFAULT_APP_ID` also provides:

```text
GET  /status
POST /install
```

## Update flow

For each registered application the updater:

1. Reads the running/local version.
2. Reads the latest repository `VERSION` marker.
3. Backs up only that app's configured managed files.
4. Downloads the configured GitHub branch.
5. Supports authenticated download for private repositories when a token is configured.
6. Verifies the downloaded version.
7. Runs configured preflight checks.
8. Replaces only explicitly managed source files/directories.
9. Builds only the target Compose service.
10. Recreates only that service.
11. Checks the configured health/version endpoint.
12. Automatically restores the backup and rebuilds the previous version if validation fails.

State and source backups are stored under the updater's persistent `/state` directory.

## Application-specific behaviour

### Immich Upload Gateway

Uses `/health` on port 8092 and updates only the gateway service.

### Inventory Manager

Uses `/health` on port 1975. The old `inventory-updater` sidecar is no longer required; the application's Updates page now calls `ad53-shared-updater`.

### Rip Manager

Uses `/api/info` on port 8088 so the updater can validate the exact running Manager version. The repository is private, so the existing GitHub token is mounted read-only into the shared updater.

Only the local `rip-manager` Docker service is managed here. Remote Rip Node deployment/update remains inside the Rip Manager node workflow.

## Adding another app

Add a new entry to `apps.json` and mount its project directory into `shared-updater/docker-compose.yml`.

A normal entry contains:

```json
{
  "id": "my-app",
  "name": "My App",
  "repo": "owner/repository",
  "branch": "main",
  "app_dir": "/apps/my-app",
  "version_file": "VERSION",
  "compose_file": "docker-compose.yml",
  "compose_service": "my-app",
  "health_url": "http://127.0.0.1:1234/health",
  "health_version_field": "version",
  "managed_files": ["app", "Dockerfile", "docker-compose.yml", "VERSION"],
  "preflight": [["python3", "-m", "py_compile", "app/main.py"]]
}
```

For a private repository also configure `github_token_file` and mount that token read-only into the updater container.

## Important deployment rule

Run only **one `ad53-shared-updater` per Docker host**. Do not run the old per-app Docker updater sidecars against the same application directory at the same time.
