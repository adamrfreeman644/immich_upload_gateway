# Changelog

## 0.5.3 — Album permission fix

- Create **Uploaded though Portal** empty before adding the uploaded asset, avoiding Immich's additional `asset.share` permission requirement.
- Show an **Uploaded — album failed** warning and the failure type in the portal when Immich accepts the file but album assignment fails.

## 0.5.2 — Portal upload album

- Automatically add every successful Immich upload to the album `Uploaded though Portal`.
- Reuse the existing album for the API-key owner or create it on the first successful upload.
- Keep assets in the owner's normal timeline at their original capture date.
- Treat album-assignment failure separately so an asset already accepted by Immich is never moved to fallback storage or uploaded twice.

All notable changes to Immich Upload Gateway are recorded here.

## 0.5.0 — Shared updater architecture

- Add a reusable manifest-driven **AD53 Shared App Updater** under `shared-updater/`.
- Allow one updater container to manage multiple self-hosted applications on the same Docker host.
- Keep Docker socket access isolated to the shared updater rather than exposing it to public application containers.
- Add per-app status and install APIs: `GET /apps/<id>/status` and `POST /apps/<id>/install`.
- Keep compatibility `GET /status` and `POST /install` endpoints for the Gateway using `DEFAULT_APP_ID=immich-gateway`.
- Add per-app GitHub version checks, timestamped managed-file backups, archive validation, preflight commands, Compose rebuild/recreate, health/version verification and automatic rollback.
- Change the Gateway Compose file to use the shared updater on the Docker host by default.
- Keep the previous dedicated Gateway updater as an optional `legacy-updater` Compose profile for migration/rollback only.
- Add `host.docker.internal:host-gateway` mapping so the Gateway can reach the host-side shared updater on Linux/Unraid.
- Add complete shared-updater deployment and app-registry documentation.

## 0.4.5 — Upload thumbnails and documentation

- Add a small local preview thumbnail beside every selected file's individual progress bar.
- Generate image previews in the browser without recompressing or separately uploading thumbnails.
- Attempt browser-native video previews with a clear fallback icon when preview generation is unsupported.
- Keep existing per-file progress, failure reasons and retry behaviour.
- Rewrite the main README as a complete fresh-install, configuration, reverse-proxy, usage, update, migration and troubleshooting guide.
- Clarify that Immich assets belong to the user who owns the API key configured for the portal and therefore appear in that user's normal Photos timeline.

## 0.4.4 — Cross-filesystem fallback uploads

- Fix fallback saves from container `/tmp` to bind-mounted Unraid storage by handling cross-device moves safely.

## 0.4.3 — Collision-free container naming

- Use `immich-gateway` as the short default gateway container name so migration can complete while the legacy `immich-upload-gateway` container still exists.

## 0.4.2 — Clear uploads and reliable update detection

- Show a progress bar and result for every selected upload.
- Display per-file failure reasons and allow individual retries.
- Generate QR codes from the first custom domain currently entered in Admin.
- Compare the latest release with the version reported by the running gateway, not only the source directory.
- Rebuild when source files are current but the running gateway image is stale.
- Use short configurable container names by default.

## 0.4.0 — Multi-portal domains and in-app updater

- Fix updater rollback caused by the application reporting a hard-coded version different from the repository `VERSION` file.
- Read the running application version directly from `VERSION`.
- Migrate existing 0.2.x/0.3.x config in place without removing existing portal tokens, API keys, fallback paths or settings.
- Add dynamic portal creation and deletion from Admin.
- Add one-or-more custom hostname mappings per portal.
- Serve a matched portal directly at the custom domain root while preserving legacy token URLs.
- Make QR codes use a portal's custom domain when configured.
- Add an Admin Updates page with check/install controls.
- Add an isolated updater sidecar so Docker control is not exposed to the public gateway container.
- Remove hard-coded container names and make the host port configurable for side-by-side migration from 0.2.0.
- Add a persistent fallback root for newly-created portals.
- Document the safe 0.2.0 → 0.4.x parallel-container migration procedure.

## 0.3.1 — Unraid startup safety

- Wait for `/mnt/user` to be a genuine mounted user-share filesystem before the updater touches appdata.
- Add a flash-based Unraid startup helper that never creates paths under `/mnt/user` during early boot.
- Add an installer that removes the old unsafe direct `/mnt/user` startup line and installs the safe helper.
- Fail safely when user shares do not mount instead of creating directories on Unraid's RAM root filesystem.
