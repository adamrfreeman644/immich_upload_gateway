#!/bin/bash
set -euo pipefail

APP_DIR="${APP_DIR:-/mnt/user/appdata/immich-upload-gateway}"
REPO="${REPO:-adamrfreeman644/immich_upload_gateway}"
BRANCH="${BRANCH:-main}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8092/health}"
RAW_BASE="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
ARCHIVE_URL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.zip"

log(){ printf '[immich-gateway-updater] %s\n' "$*"; }

# If this script is launched from Unraid's boot sequence, do not touch
# /mnt/user until the user-share filesystem is genuinely mounted. Accessing
# it early can create ordinary directories on the root filesystem and prevent
# Unraid's real user-share mount from being established.
if [[ "$APP_DIR" == /mnt/user/* ]]; then
  timeout="${UNRAID_USER_SHARE_WAIT_SECONDS:-300}"
  waited=0
  while (( waited < timeout )); do
    if mountpoint -q /mnt/user; then
      break
    fi
    sleep 2
    waited=$((waited + 2))
  done
  if ! mountpoint -q /mnt/user; then
    log "/mnt/user did not become a mountpoint within ${timeout}s; updater will not run."
    exit 0
  fi
fi

[[ -d "$APP_DIR" ]] || { log "App directory not found: $APP_DIR"; exit 1; }

current="$(cat "$APP_DIR/VERSION" 2>/dev/null || echo 0.0.0)"
latest="$(curl -fsSL --connect-timeout 10 --max-time 30 "$RAW_BASE/VERSION" | tr -d '[:space:]')"
[[ -n "$latest" ]] || { log 'Could not determine latest GitHub version'; exit 1; }
[[ "$current" == "$latest" ]] && { log "Already current: $current"; exit 0; }

stamp="$(date +%Y%m%d-%H%M%S)"
backup="$APP_DIR/backups/$stamp"
stage="$(mktemp -d)"
archive="$stage/update.zip"
cleanup(){ rm -rf "$stage"; }
trap cleanup EXIT
mkdir -p "$backup"

managed=(app.py Dockerfile docker-compose.yml requirements.txt VERSION README.md gateway-updater.sh .env.example)
for f in "${managed[@]}"; do
  [[ -f "$APP_DIR/$f" ]] && cp -a "$APP_DIR/$f" "$backup/"
done

log "Downloading $REPO@$BRANCH ($current -> $latest)"
curl -fsSL --connect-timeout 10 --max-time 120 "$ARCHIVE_URL" -o "$archive"
unzip -q "$archive" -d "$stage"
src="$(find "$stage" -mindepth 1 -maxdepth 1 -type d | head -1)"
[[ -n "$src" && -f "$src/app.py" && -f "$src/VERSION" ]] || { log 'GitHub archive does not contain a valid gateway build'; exit 1; }

archive_version="$(tr -d '[:space:]' < "$src/VERSION")"
[[ "$archive_version" == "$latest" ]] || { log "Archive version '$archive_version' does not match '$latest'"; exit 1; }
python3 -m py_compile "$src/app.py"

rollback(){
  log "Update failed; rolling back to $current"
  for f in "${managed[@]}"; do
    if [[ -f "$backup/$f" ]]; then cp -af "$backup/$f" "$APP_DIR/$f"; else rm -f "$APP_DIR/$f"; fi
  done
  cd "$APP_DIR"
  docker compose build
  docker compose up -d
}

for f in "${managed[@]}"; do [[ -f "$src/$f" ]] && cp -f "$src/$f" "$APP_DIR/$f"; done
chmod +x "$APP_DIR/gateway-updater.sh" 2>/dev/null || true
cd "$APP_DIR"

if ! docker compose config >/dev/null; then rollback; exit 1; fi
if ! docker compose build --pull; then rollback; exit 1; fi
if ! docker compose up -d; then rollback; exit 1; fi

healthy=0
for _ in {1..30}; do
  if curl -fsS "$HEALTH_URL" 2>/dev/null | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'; then healthy=1; break; fi
  sleep 1
done
if [[ "$healthy" != 1 ]]; then rollback; exit 1; fi

installed="$(curl -fsS "$HEALTH_URL" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)"
if [[ "$installed" != "$latest" ]]; then
  log "Health check returned version '$installed', expected '$latest'"
  rollback
  exit 1
fi

log "Updated $current -> $latest from GitHub"
