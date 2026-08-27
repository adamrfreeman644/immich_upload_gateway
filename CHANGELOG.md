# Changelog

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
