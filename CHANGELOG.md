# Changelog

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
- Document the safe 0.2.0 → 0.4.0 parallel-container migration procedure.

## 0.3.1 — Unraid startup safety

- Wait for `/mnt/user` to be a genuine mounted user-share filesystem before the updater touches appdata.
- Add a flash-based Unraid startup helper that never creates paths under `/mnt/user` during early boot.
- Add an installer that removes the old unsafe direct `/mnt/user` startup line and installs the safe helper.
- Fail safely when user shares do not mount instead of creating directories on Unraid's RAM root filesystem.

## 0.3.0 — Shared authentication architecture

- Keep public upload links account-free and independent of Authentik availability.
- Protect `/admin` and `/admin/...` with Authentik OpenID Connect when enabled.
- Use Authorization Code flow, PKCE support, validated OIDC state/nonce/provider tokens and secure local admin sessions.
- Open Authentik sign-in in a popup so the Gateway page remains in place.
- Fail admin access closed on enabled-but-invalid OIDC configuration without breaking valid public upload routes.
- Preserve the previous local admin password only while `AUTH_ENABLED=false` for migration/rollback.
- Add non-secret authentication provider/status information and OIDC-aware logout.
- Preserve existing portal tokens, Immich keys, fallback directories, configuration and updater behavior.
- Add automated public/admin boundary, OIDC failure and health secrecy checks.

