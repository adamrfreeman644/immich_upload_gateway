#!/bin/bash
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
BOOT_DIR="/boot/config/immich-upload-gateway"
GO_FILE="/boot/config/go"
START_LINE="bash $BOOT_DIR/unraid-startup.sh &"

[[ -f "$GO_FILE" ]] || { echo "Unraid go file not found: $GO_FILE" >&2; exit 1; }

install -d -m 700 "$BOOT_DIR"
install -m 0755 "$here/unraid-startup.sh" "$BOOT_DIR/unraid-startup.sh"

# Remove the old unsafe direct /mnt/user access, including the temporary
# disabled form used during recovery, and replace it with the flash-based
# helper. The helper itself waits for /mnt/user to become a real mountpoint.
sed -i '\#^[[:space:]]*install -m 755 /mnt/user/appdata/immich-upload-gateway/gateway-updater.sh /usr/local/sbin/immich-upload-gateway-updater[[:space:]]*$#d' "$GO_FILE"
sed -i '\#^[[:space:]]*# TEMP DISABLED: install -m 755 /mnt/user/appdata/immich-upload-gateway/gateway-updater.sh /usr/local/sbin/immich-upload-gateway-updater[[:space:]]*$#d' "$GO_FILE"
sed -i '\#/boot/config/immich-upload-gateway/unraid-startup.sh#d' "$GO_FILE"
printf '%s\n' "$START_LINE" >> "$GO_FILE"

# Install it now as well when possible, without requiring a reboot.
bash "$BOOT_DIR/unraid-startup.sh"

echo "Installed safe Immich Upload Gateway Unraid startup bootstrap."
