#!/bin/bash
set -u

USER_MOUNT="/mnt/user"
APP_DIR="${APP_DIR:-/mnt/user/appdata/immich-upload-gateway}"
SOURCE="$APP_DIR/gateway-updater.sh"
TARGET="/usr/local/sbin/immich-upload-gateway-updater"

log() {
  logger -t immich-upload-gateway "$*" 2>/dev/null || true
}

# Never create anything under /mnt/user. During early Unraid boot this path
# can exist on the RAM root filesystem before the real user-share filesystem
# has been mounted. Wait for the genuine mount instead.
for _ in $(seq 1 180); do
  if mountpoint -q "$USER_MOUNT"; then
    break
  fi
  sleep 2
done

if ! mountpoint -q "$USER_MOUNT"; then
  log "User-share filesystem did not mount; updater bootstrap skipped"
  exit 0
fi

if [[ ! -f "$SOURCE" ]]; then
  log "Gateway updater not found at $SOURCE; bootstrap skipped"
  exit 0
fi

if ! install -m 0755 "$SOURCE" "$TARGET"; then
  log "Failed to install gateway updater to $TARGET"
  exit 1
fi

log "Gateway updater installed after /mnt/user became available"
